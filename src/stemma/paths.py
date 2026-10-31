"""Locate the repository, tracks and build directories."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Return the stemma project root.

    Uses ``STEMMA_ROOT`` if set, otherwise walks up from the working directory
    looking for a ``tracks/`` folder next to a ``pyproject.toml``.
    """
    env = os.environ.get("STEMMA_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / "tracks").is_dir() and (p / "pyproject.toml").is_file():
            return p
    return here


def track_dir(slug: str) -> Path:
    return repo_root() / "tracks" / slug


def sounds_dir() -> Path:
    return repo_root() / "sounds"


def render_root(track: Path, section: str | None = None) -> Path:
    """Build directory for a full render or for one section."""
    base = track / "renders"
    return base / "sections" / section if section else base


def stems_dir(track: Path, section: str | None = None) -> Path:
    return render_root(track, section) / "stems"
