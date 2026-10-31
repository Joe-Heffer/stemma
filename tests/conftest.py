import shutil
from pathlib import Path

import pytest

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
