import io
import json

import numpy as np
import pytest
import soundfile as sf

from stemma.cli import main
from stemma.paths import track_dir
from stemma.reference import MAX_PROMPT, build_prompt
from stemma.spec import load


def _wav_bytes(seconds=6.0, sr=44100) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    tone = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 1760 * t)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([tone, tone]), sr, format="WAV")
    return buf.getvalue()


@pytest.fixture
def demo(scratch_root, capsys):
    main(["new", "demo"])
    notes = track_dir("demo") / "notes.md"
    notes.write_text(notes.read_text().replace(
        "What is this track for?", "Moody night-drive synthwave. What is this track for?"))
    capsys.readouterr()
    return load(track_dir("demo"))


class FakeAPI:
    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return io.BytesIO(_wav_bytes())


def test_prompt_uses_spec_and_brief(demo):
    p = build_prompt(demo)
    assert f"{demo.tempo:g} bpm" in p and demo.key in p
    assert all(s.name in p for s in demo.sections)
    assert "night-drive synthwave" in p
    assert "no vocals" in p
    assert len(p) <= MAX_PROMPT


def test_compare_with_file(demo, scratch_root, capsys):
    ref = scratch_root / "ref.wav"
    ref.write_bytes(_wav_bytes())
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
