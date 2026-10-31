import json

import numpy as np
import pytest
import soundfile as sf
import yaml
from conftest import FakeAPI

from stemma.cli import main
from stemma.elevenlabs import part_prompt
from stemma.paths import track_dir
from stemma.render import generated_part
from stemma.spec import load, validate

KEYS = {"name": "keys", "role": "harmony", "source": "elevenlabs",
        "sound": {"prompt": "warm Rhodes electric piano comping on the chords"},
        "mix": {"gain_db": -6}}


def _add_part(part: dict) -> None:
    path = track_dir("demo") / "track.yaml"
    data = yaml.safe_load(path.read_text())
    data["parts"].append(part)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.fixture
def demo(scratch_root, capsys):
    main(["new", "demo"])
    _add_part(KEYS)
    capsys.readouterr()
    return load(track_dir("demo"))


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI(seconds=25)  # longer than the 19.2 s demo track
    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test-secret")
    return fake


def _out(capsys) -> dict | list:
    return json.loads(capsys.readouterr().out)


def test_schema_and_rules(example_spec_data):
    data = {**example_spec_data, "parts": [*example_spec_data["parts"], KEYS]}
    assert validate(data) == []
    no_prompt = {**KEYS, "sound": {}}
    errs = validate({**example_spec_data, "parts": [no_prompt]})
    assert any("sound.prompt" in e for e in errs)
    with_gen = {**KEYS, "generator": "parts/keys.py"}
    errs = validate({**example_spec_data, "parts": [with_gen]})
    assert any("generator" in e for e in errs)


def test_prompt_is_one_instrument(demo):
    p = part_prompt(demo, demo.part("keys"))
    assert "Rhodes" in p and f"{demo.tempo:g} bpm" in p and demo.key in p
    assert "one instrument only" in p and "no drums" in p and "no vocals" in p


def test_render_generates_once_then_caches(demo, api, capsys):
    assert main(["render", "demo", "--part", "keys"]) == 0
    [r] = _out(capsys)
    assert r["status"] == "rendered" and r["generation"] == "new" and r["notes"] == 0
    assert len(api.requests) == 1
    body = json.loads(api.requests[0].data)
    assert body["music_length_ms"] == round(demo.duration * 1000)
    assert "Rhodes" in body["prompt"]

    x, sr = sf.read(str(demo.dir / "renders/stems/keys.wav"), always_2d=True)
    assert sr == demo.sample_rate and x.shape[1] == 2
    assert len(x) == round((demo.duration + demo.master["tail_seconds"]) * sr)

    meta = next((demo.dir / "generated").glob("keys-*.json"))
    assert "sk-test-secret" not in meta.read_text()

    assert main(["render", "demo", "--part", "keys"]) == 0
    assert _out(capsys)[0]["status"] == "cached"
    assert main(["render", "demo", "--part", "keys", "--force"]) == 0
    assert _out(capsys)[0]["generation"] == "cached"
    assert len(api.requests) == 1  # --force re-renders but does not spend credits

    assert main(["render", "demo", "--part", "keys", "--force-generate"]) == 0
    assert _out(capsys)[0]["generation"] == "new"
    assert len(api.requests) == 2


def test_section_is_a_slice_of_the_whole(demo, api, capsys):
    main(["render", "demo", "--part", "keys"])
    main(["render", "demo", "--part", "keys", "--section", "b"])
    capsys.readouterr()
    full, sr = sf.read(str(demo.dir / "renders/stems/keys.wav"), always_2d=True)
    sec, _ = sf.read(str(demo.dir / "renders/sections/b/stems/keys.wav"), always_2d=True)
    i0 = round(demo.section_span("b")[0] * sr)
    np.testing.assert_allclose(sec, full[i0:i0 + len(sec)], atol=1e-6)
    assert len(api.requests) == 1  # one generation serves every section


def test_offset_shifts_audio(demo, api, capsys):
    main(["render", "demo", "--part", "keys"])
    path = demo.dir / "renders/stems/keys.wav"
    base, sr = sf.read(str(path), always_2d=True)
    _add_part({**KEYS, "name": "keys2", "sound": {**KEYS["sound"], "offset_seconds": 0.5}})
    spec = load(track_dir("demo"))
    # Same prompt text apart from the part name, so point keys2 at keys' audio.
    src = next((spec.dir / "generated").glob("keys-*.mp3"))
    shifted = generated_part(spec, spec.part("keys2"), src, 0.0, 2.0)
    n = round(0.5 * sr)
    np.testing.assert_allclose(shifted[: len(shifted) - n], base[n:len(shifted)], atol=1e-6)
    capsys.readouterr()


def test_missing_key(demo, monkeypatch, capsys):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert main(["render", "demo", "--part", "keys"]) == 1
    assert "ELEVENLABS_API_KEY" in capsys.readouterr().err

    path = track_dir("demo") / "track.yaml"
    data = yaml.safe_load(path.read_text())
    data["parts"][-1]["optional"] = True
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert main(["render", "demo", "--part", "keys"]) == 0
    assert _out(capsys)[0]["status"] == "skipped"


def test_whole_chain(demo, api, capsys):
    assert main(["all", "demo"]) == 0
    out = _out(capsys)
    midi = {m["part"]: m for m in out["midi"]}
    assert midi["keys"]["origin"] == "audio"
    assert "keys" in out["analysis"]["stems"]
    assert out["analysis"]["stems"]["keys"]["tempo_bpm"] is not None
    # A steady tone has no 100 bpm pulse, so the drift warning should fire.
    assert any(w.startswith("keys: generated audio runs at") for w in out["analysis"]["warnings"])

    assert main(["score", "demo", "--format", "musicxml"]) == 0
    score = _out(capsys)
    assert score["not_scored"] == {"keys": "generated audio, no notes"}
    assert "keys" not in {p["part"] for p in score["parts"]}
    assert main(["score", "demo", "--part", "keys"]) == 1
