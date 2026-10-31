import json

import pytest
from conftest import FakeAPI, wav_bytes

from stemma.cli import main
from stemma.elevenlabs import MAX_PROMPT, build_prompt
from stemma.paths import track_dir
from stemma.spec import load


@pytest.fixture
def demo(scratch_root, capsys):
    main(["new", "demo"])
    notes = track_dir("demo") / "notes.md"
    notes.write_text(notes.read_text().replace(
        "What is this track for?", "Moody night-drive synthwave. What is this track for?"))
    capsys.readouterr()
    return load(track_dir("demo"))


def test_prompt_uses_spec_and_brief(demo):
    p = build_prompt(demo)
    assert f"{demo.tempo:g} bpm" in p and demo.key in p
    assert all(s.name in p for s in demo.sections)
    assert "night-drive synthwave" in p
    assert "no vocals" in p
    assert len(p) <= MAX_PROMPT


def test_compare_with_file(demo, scratch_root, capsys):
    ref = scratch_root / "ref.wav"
    ref.write_bytes(wav_bytes())
    assert main(["reference", "demo", "--file", str(ref)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["reference"]["bands_db"] and out["compare"] is None
    assert out["cached"] is None and "prompt" not in out

    main(["all", "demo"])
    capsys.readouterr()
    assert main(["reference", "demo", "--file", str(ref)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out["compare"]["bands_db"]) == {"sub", "low", "low_mid", "high_mid", "air"}
    assert out["compare"]["spectral_centroid_hz"]["diff"] is not None
    assert (track_dir("demo") / "renders/reference/analysis.json").is_file()


def test_generate_calls_api_once(demo, monkeypatch, capsys):
    fake = FakeAPI()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test-secret")

    assert main(["reference", "demo", "--seconds", "5"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cached"] is False and len(fake.requests) == 1
    req = fake.requests[0]
    assert req.get_header("Xi-api-key") == "sk-test-secret"
    body = json.loads(req.data)
    assert body["music_length_ms"] == 5000 and body["force_instrumental"] is True
    meta = next((track_dir("demo") / "renders/reference").glob("ref-*.json"))
    assert "sk-test-secret" not in meta.read_text()

    assert main(["reference", "demo", "--seconds", "5"]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] is True
    assert len(fake.requests) == 1

    assert main(["reference", "demo", "--seconds", "5", "--force"]) == 0
    capsys.readouterr()
    assert len(fake.requests) == 2


def test_length_is_clamped(demo, monkeypatch, capsys):
    fake = FakeAPI()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    main(["reference", "demo", "--seconds", "1"])
    capsys.readouterr()
    assert json.loads(fake.requests[0].data)["music_length_ms"] == 3000


def test_missing_key(demo, monkeypatch, capsys):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert main(["reference", "demo"]) == 1
    assert "ELEVENLABS_API_KEY" in capsys.readouterr().err
