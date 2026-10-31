import io
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_spec_data():
    import yaml

    return yaml.safe_load((ROOT / "tracks/example-sketch/track.yaml").read_text())


@pytest.fixture
def scratch_root(tmp_path, monkeypatch):
    """An isolated stemma root with a copy of the sounds manifest."""
    (tmp_path / "tracks").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    shutil.copytree(ROOT / "sounds", tmp_path / "sounds", ignore=shutil.ignore_patterns("cache"))
    monkeypatch.setenv("STEMMA_ROOT", str(tmp_path))
    return tmp_path


def wav_bytes(seconds=6.0, sr=44100, freq=220.0) -> bytes:
    """A short stereo test tone, standing in for audio from the ElevenLabs API."""
    t = np.arange(int(seconds * sr)) / sr
    tone = 0.3 * np.sin(2 * np.pi * freq * t) + 0.1 * np.sin(2 * np.pi * 8 * freq * t)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([tone, tone]), sr, format="WAV")
    return buf.getvalue()


class FakeAPI:
    """Replaces ``urllib.request.urlopen`` and records each request."""

    def __init__(self, seconds=6.0):
        self.requests = []
        self.seconds = seconds

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return io.BytesIO(wav_bytes(self.seconds))
