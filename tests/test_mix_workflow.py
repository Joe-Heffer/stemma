"""Sidechain, automation and the mastering chain, through the CLI."""

import json

import numpy as np
import pytest
import yaml

from stemma import dsp
from stemma.cli import main
from stemma.spec import validate

SR = 48000


def edit_spec(root, fn):
    path = root / "tracks/demo/track.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def part(data, name):
    return next(p for p in data["parts"] if p["name"] == name)


@pytest.fixture
def demo(scratch_root, capsys):
    main(["new", "demo"])
    main(["midi", "demo"])
    main(["render", "demo"])
    capsys.readouterr()
    return scratch_root


def run(capsys, *args):
    assert main(list(args)) == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def test_duck_gain_follows_trigger():
    trig = np.zeros(SR)
    trig[SR // 4: SR // 4 + 2400] = 0.9
    g = dsp.duck_gain(trig, SR, depth_db=8, threshold_db=-30, ratio=20)
    assert 20 * np.log10(g[SR // 4 + 1200]) == pytest.approx(-8, abs=0.2)
    assert g[0] == 1.0 and g[-1] == pytest.approx(1.0, abs=1e-3)


def test_sidechain_validation(example_spec_data):
    bass = part(example_spec_data, "bass")
    bass["mix"]["sidechain"] = {"source": "drums", "depth_db": 6}
    assert validate(example_spec_data) == []
    bass["mix"]["sidechain"] = {"source": "bass"}
    assert any("duck itself" in e for e in validate(example_spec_data))
    bass["mix"]["sidechain"] = {"source": "kick"}
    assert any("unknown part" in e for e in validate(example_spec_data))


def test_sidechain_ducks_bass_under_drums(demo, capsys):
    before = run(capsys, "analyse", "demo", "--stem", "bass")
    run(capsys, "mix", "demo")
    plain = run(capsys, "analyse", "demo", "--stem", "bass")["stems"]["bass"]
    edit_spec(demo, lambda d: part(d, "bass").setdefault("mix", {}).update(
        sidechain={"source": "drums", "depth_db": 6, "filter_hz": 120}))
    report = run(capsys, "mix", "demo")
    sc = next(p for p in report["parts"] if p["part"] == "bass")["sidechain"]
    assert sc["source"] == "drums"
    assert 3 < sc["max_duck_db"] <= 6.05
    ducked = run(capsys, "analyse", "demo", "--stem", "bass")["stems"]["bass"]
    assert ducked["lufs_integrated"] < plain["lufs_integrated"] - 0.5
    assert before  # raw-stem analysis worked before any mix


def test_automation_validation(example_spec_data):
    d = example_spec_data
    d["automation"] = [{"part": "lead", "section": "outro", "gain_db": -4, "ramp_beats": 2},
                       {"bus": "verb", "section": "intro", "mute": True}]
    assert validate(d) == []
    d["automation"] = [{"part": "lead", "bus": "verb", "section": "outro"}]
    assert any("exactly one" in e for e in validate(d))
    d["automation"] = [{"part": "nope", "section": "outro"}, {"part": "lead", "section": "x"}]
    errs = validate(d)
    assert any("unknown part" in e for e in errs) and any("unknown section" in e for e in errs)
    d["automation"] = [{"part": "lead", "section": "outro"}] * 2
    assert any("already automated" in e for e in validate(d))


def test_automation_curve(demo):
    from stemma.mix import automation_curve
    from stemma.spec import load

    edit_spec(demo, lambda d: d.update(automation=[
        {"part": "bass", "section": "b", "gain_db": -6, "ramp_beats": 2}]))
    spec = load(demo / "tracks/demo")
    n = int((spec.duration + spec.master["tail_seconds"]) * SR)
    g = automation_curve(spec, "part", "bass", None, n)
    b0 = int(spec.section_span("b")[0] * SR)
    ramp = int(2 * spec.seconds_per_beat * SR)
    assert g[b0 - 1] == 1.0
    assert 20 * np.log10(g[b0 + ramp // 2]) == pytest.approx(-3, abs=0.1)
    assert 20 * np.log10(g[b0 + ramp + 10]) == pytest.approx(-6, abs=1e-6)
    assert g[-1] == pytest.approx(g[b0 + ramp + 10])  # the tail holds
    # A section render is a slice of the same curve.
    m = int((spec.section_span("b")[1] - spec.section_span("b")[0]) * SR)
    gb = automation_curve(spec, "part", "bass", "b", m)
    assert np.allclose(gb[:1000], g[b0:b0 + 1000])
    assert automation_curve(spec, "part", "drums", None, n) is None


def test_automation_mutes_a_section(demo, capsys):
    edit_spec(demo, lambda d: d.update(automation=[
        {"part": "bass", "section": "b", "mute": True}]))
    report = run(capsys, "mix", "demo")
    assert next(p for p in report["parts"] if p["part"] == "bass")["automation"] == ["b"]
    import soundfile as sf

    from stemma.spec import load

    spec = load(demo / "tracks/demo")
    x, sr = sf.read(str(demo / "tracks/demo/renders/post-mix/bass.wav"))
    b0, b1 = (int(t * sr) for t in spec.section_span("b"))
    assert np.abs(x[:b0]).max() > 0.01
    assert np.abs(x[b0 + 100:b1]).max() == 0


def test_limiter_stats_in_master_audio():
    from stemma.master import master_audio

    rng = np.random.default_rng(3)
    t = np.arange(SR * 6) / SR
    quiet = 0.05 * np.sin(2 * np.pi * 110 * t)[:, None] * np.ones((1, 2))
    _, easy = master_audio(quiet, SR, lufs=-20, true_peak=-1)
    assert easy["limiter"]["max_db"] < 0.5 and easy["warnings"] == []
    # Sparse loud spikes: hitting -8 LUFS needs heavy limiting.
    spiky = quiet + (rng.random((len(t), 1)) > 0.999) * 0.9
    _, hard = master_audio(spiky, SR, lufs=-8, true_peak=-1)
    assert hard["limiter"]["max_db"] > 6
    assert any("working too hard" in w for w in hard["warnings"])
    _, kept = master_audio(quiet, SR, lufs=-8, true_peak=-1, normalise=False)
    assert kept["gain_db"] == 0 and kept["lufs"] < -20


def test_master_chain_and_formats(demo, capsys):
    run(capsys, "mix", "demo")
    edit_spec(demo, lambda d: d["master"].update(
        fx=[{"type": "stereo_width", "mono_below_hz": 120},
            {"type": "compressor", "threshold_db": -12, "ratio": 2}],
        limiter={"release_ms": 80}, formats=["wav", "mp3"]))
    report = run(capsys, "master", "demo")
    assert report["chain"] == ["stereo_width", "compressor"]
    assert report["dynamics"][0]["type"] == "compressor"
    assert set(report["limiter"]) == {"max_db", "mean_db", "percent_over_1db"}
    assert (demo / "tracks/demo/renders/master.mp3").stat().st_size > 1000
    assert abs(report["lufs"] + 14) < 0.5


def test_analyse_sections_and_delta(demo, capsys):
    run(capsys, "mix", "demo")
    run(capsys, "master", "demo")
    first = run(capsys, "analyse", "demo")
    assert first["delta"] is None
    assert set(first["sections"]) == {"a", "b"}
    assert first["sections"]["a"]["lufs_integrated"] is not None
    assert "max_db" in first["master"]["limiter"]
    assert first["master"]["loudness_range_lu"] is not None
    edit_spec(demo, lambda d: part(d, "bass")["mix"].update(gain_db=-10))
    run(capsys, "mix", "demo")
    run(capsys, "master", "demo")
    second = run(capsys, "analyse", "demo")
    change = second["delta"]["changed"]["stems.bass.lufs_integrated"]
    assert change["diff"] == pytest.approx(-6, abs=0.3)
    # Re-running with nothing changed still reports the last change.
    third = run(capsys, "analyse", "demo")
    assert third["delta"]["changed"]["stems.bass.lufs_integrated"] == change
