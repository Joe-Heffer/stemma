"""Render parts (MIDI plus a sound) to WAV stems."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import __version__
from ..errors import BackendUnavailable, StemmaError
from ..midi import NoteEvent, read_notes
from ..paths import stems_dir
from ..spec import Spec
from . import builtin, external


def select_notes(notes: list[NoteEvent], start: float, end: float) -> list[NoteEvent]:
    """Notes sounding within [start, end), shifted so ``start`` becomes 0.

    A note that began before the section is clipped to start at 0, so held
    notes and pads are heard when rendering a section on its own.
    """
    out = []
    for n in notes:
        if n.end > start and n.start < end:
            out.append(NoteEvent(n.pitch, max(n.start, start) - start, n.end - start, n.velocity))
    return out


def _cache_key(spec: Spec, part: dict, notes, length: float) -> str:
    sound = part.get("sound", {})
    h = hashlib.sha256()
    h.update(json.dumps({"v": __version__, "sr": spec.sample_rate, "len": length,
                         "source": part["source"], "sound": sound, "seed": spec.seed},
                        sort_keys=True).encode())
    h.update(repr([(n.pitch, round(n.start, 6), round(n.end, 6), n.velocity)
                   for n in notes]).encode())
    if "path" in sound:
        p = spec.resolve(sound["path"])
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def render_part(spec: Spec, part: dict, section: str | None = None,
                force: bool = False) -> dict:
    name = part["name"]
    start, end = spec.section_span(section)
    length = (end - start) + spec.master["tail_seconds"]
    notes = select_notes(read_notes(spec.midi_path(part)), start, end)
    out_dir = stems_dir(spec.dir, section)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav, meta = out_dir / f"{name}.wav", out_dir / f"{name}.json"
    key = _cache_key(spec, part, notes, length)
    if not force and wav.is_file() and meta.is_file():
        if json.loads(meta.read_text()).get("key") == key:
            return {"part": name, "status": "cached", "stem": str(wav.relative_to(spec.dir))}
    source = part["source"]
    seed = (spec.seed * 1_000_003 + sum(map(ord, name))) % 2**32
    try:
        if source == "builtin":
            audio = builtin.render(notes, part.get("sound", {}), spec.sample_rate, length, seed)
        else:
            with tempfile.TemporaryDirectory(prefix="stemma-") as tmp:
                audio = external.RENDERERS[source](notes, spec, part, length, Path(tmp))
    except BackendUnavailable as e:
        if part.get("optional"):
            print(f"  skipping optional part {name!r}: {e}", file=sys.stderr)
            for f in (wav, meta):
                f.unlink(missing_ok=True)
            return {"part": name, "status": "skipped", "reason": str(e)}
        raise StemmaError(f"part {name!r}: {e}") from e
    audio = np.asarray(audio, dtype=np.float32)
    if not np.all(np.isfinite(audio)):
        raise StemmaError(f"part {name!r}: renderer produced NaN or infinite samples")
    sf.write(str(wav), audio, spec.sample_rate, subtype="FLOAT")
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    info = {"key": key, "source": source, "notes": len(notes), "channels": audio.shape[1],
            "seconds": round(len(audio) / spec.sample_rate, 3),
            "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None}
    meta.write_text(json.dumps(info, indent=2) + "\n")
    return {"part": name, "status": "rendered", "stem": str(wav.relative_to(spec.dir)),
            **{k: v for k, v in info.items() if k != "key"}}


def render(spec: Spec, part: str | None = None, section: str | None = None,
           force: bool = False) -> list[dict]:
    parts = [spec.part(part)] if part else spec.parts
    if section:
        spec.section(section)  # validate early
    return [render_part(spec, p, section, force) for p in parts]
