"""Render parts (MIDI plus a sound) to WAV stems."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import __version__, elevenlabs
from ..errors import BackendUnavailable, StemmaError
from ..midi import NoteEvent, read_notes
from ..paths import stems_dir
from ..spec import Spec, is_audio_part
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


def _audio_cache_key(spec: Spec, part: dict, source_file: Path, start: float,
                     length: float) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"v": __version__, "sr": spec.sample_rate, "start": start,
                         "len": length, "source": part["source"],
                         "sound": part.get("sound", {})}, sort_keys=True).encode())
    h.update(source_file.read_bytes())
    return h.hexdigest()


def generated_part(spec: Spec, part: dict, source_file: Path, start: float,
                   length: float) -> np.ndarray:
    """Slice generated audio to [start, start + length), after ``offset_seconds``."""
    sound = part.get("sound", {})
    sr = spec.sample_rate
    full = external.read_wav(source_file, sr, sf.info(str(source_file)).duration)
    offset = int(round(sound.get("offset_seconds", 0) * sr))
    if offset > 0:
        full = full[offset:]
    elif offset < 0:
        full = np.pad(full, ((-offset, 0), (0, 0)))
    i0, n = int(round(start * sr)), int(round(length * sr))
    out = full[i0:i0 + n]
    if len(out) < n:
        out = np.pad(out, ((0, n - len(out)), (0, 0)))
    if out.shape[1] == 1:
        out = np.repeat(out, 2, axis=1)
    return out * 10 ** (sound.get("gain_db", 0) / 20)


def render_part(spec: Spec, part: dict, section: str | None = None,
                force: bool = False, force_generate: bool = False) -> dict:
    name = part["name"]
    start, end = spec.section_span(section)
    length = (end - start) + spec.master["tail_seconds"]
    out_dir = stems_dir(spec.dir, section)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav, meta = out_dir / f"{name}.wav", out_dir / f"{name}.json"
    source = part["source"]
    extra: dict = {}
    try:
        if is_audio_part(part):
            notes = []
            source_file, cached = elevenlabs.part_audio(spec, part, force_generate)
            extra = {"generated": str(source_file.relative_to(spec.dir)),
                     "generation": "cached" if cached else "new"}
            key = _audio_cache_key(spec, part, source_file, start, length)
        else:
            notes = select_notes(read_notes(spec.midi_path(part)), start, end)
            key = _cache_key(spec, part, notes, length)
        if not force and wav.is_file() and meta.is_file():
            if json.loads(meta.read_text()).get("key") == key:
                return {"part": name, "status": "cached",
                        "stem": str(wav.relative_to(spec.dir)), **extra}
        seed = (spec.seed * 1_000_003 + sum(map(ord, name))) % 2**32
        if is_audio_part(part):
            audio = generated_part(spec, part, source_file, start, length)
        elif source == "builtin":
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
    info = {"key": key, "source": source, **extra, "notes": len(notes),
            "channels": audio.shape[1],
            "seconds": round(len(audio) / spec.sample_rate, 3),
            "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None}
    meta.write_text(json.dumps(info, indent=2) + "\n")
    return {"part": name, "status": "rendered", "stem": str(wav.relative_to(spec.dir)),
            **{k: v for k, v in info.items() if k != "key"}}


def render(spec: Spec, part: str | None = None, section: str | None = None,
           force: bool = False, force_generate: bool = False) -> list[dict]:
    """Render parts to stems. ``force`` ignores the stem cache; ``force_generate``
    also calls the ElevenLabs API again for generated parts, which costs credits."""
    parts = [spec.part(part)] if part else spec.parts
    if section:
        spec.section(section)  # validate early
    return [render_part(spec, p, section, force or force_generate, force_generate)
            for p in parts]
