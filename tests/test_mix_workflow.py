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
