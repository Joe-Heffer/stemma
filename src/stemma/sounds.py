"""Resolve and fetch shared sounds listed in ``sounds/manifest.yaml``."""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path

import yaml

from .errors import BackendUnavailable, StemmaError
from .paths import sounds_dir


def manifest() -> dict[str, dict]:
    path = sounds_dir() / "manifest.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {s["name"]: s for s in data.get("sounds", [])}


def cache_dir() -> Path:
    return sounds_dir() / "cache"


def candidates(name: str) -> list[Path]:
    entry = manifest().get(name)
    if entry is None:
        return [Path(name)]
    out = []
    if entry.get("path"):
        out.append(sounds_dir() / entry["path"])
    if entry.get("file"):
        out.append(cache_dir() / entry["file"])
    out += [Path(p).expanduser() for p in entry.get("system_paths", [])]
    return out


def resolve(name: str, base: Path | None = None) -> Path:
    """Find a sound by manifest name or path, raising if it is not present."""
    p = Path(name)
    for c in ([base / p] if base else []) + [sounds_dir() / p] + candidates(name):
        if c.is_file():
            return c
    hint = (f"run `stemma sounds fetch {name}` or install it (see sounds/README.md)"
            if name in manifest() else "check the path")
    raise BackendUnavailable(f"sound {name!r} not found; {hint}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str) -> Path:
    entry = manifest().get(name)
    if entry is None:
        raise StemmaError(f"{name!r} is not in sounds/manifest.yaml")
    if not entry.get("url"):
        raise StemmaError(f"{name!r} has no download url; see its notes in the manifest")
    dest = cache_dir() / entry["file"]
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {entry['url']}")
    with urllib.request.urlopen(entry["url"]) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    digest = sha256(tmp)
    if entry.get("sha256") and digest != entry["sha256"]:
        tmp.unlink()
        raise StemmaError(f"checksum mismatch for {name}: got {digest}")
    if not entry.get("sha256"):
        print(f"  no checksum recorded; add `sha256: {digest}` to the manifest")
    tmp.rename(dest)
    return dest
