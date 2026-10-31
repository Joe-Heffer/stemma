"""Build MIDI parts from generator scripts and read them back for rendering."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pretty_midi

from .compose import Context
from .errors import StemmaError
from .spec import Spec
from .theory import note_name

# An unused controller, written after the last note so renderers that stop at the
# end of the MIDI file (FluidSynth) keep running through release tails.
END_MARKER_CC = 110


@dataclass
class NoteEvent:
    pitch: int
    start: float  # seconds
    end: float  # seconds
    velocity: int


def is_drum(part: dict) -> bool:
    """True when a part is written on MIDI channel 10 (GM percussion)."""
    sound = part.get("sound", {})
    return bool(sound.get("drums", part.get("role") in ("drums", "percussion")))


def run_generator(spec: Spec, part: dict) -> Context:
    path = spec.dir / part["generator"]
    if not path.is_file():
        raise StemmaError(f"generator {path} not found for part {part['name']!r}")
    mod_name = f"stemma_gen_{spec.slug}_{part['name']}".replace("-", "_")
    module_spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[mod_name] = module
    try:
        module_spec.loader.exec_module(module)
        if not hasattr(module, "build"):
            raise StemmaError(f"{path} must define build(ctx)")
        ctx = Context(spec, part)
        module.build(ctx)
    finally:
        sys.modules.pop(mod_name, None)
    return ctx


def write_part(spec: Spec, part: dict, ctx: Context, path: Path) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=spec.tempo, resolution=960)
    pm.time_signature_changes.append(
        pretty_midi.TimeSignature(spec.numerator, spec.denominator, 0.0)
    )
    sound = part.get("sound", {})
    inst = pretty_midi.Instrument(program=sound.get("program", 0), is_drum=is_drum(part),
                                  name=part["name"])
    bank = sound.get("bank")
    if bank is not None:
        inst.control_changes += [
            pretty_midi.ControlChange(0, bank >> 7, 0.0),
            pretty_midi.ControlChange(32, bank & 127, 0.0),
        ]
    for n in sorted(ctx.notes, key=lambda n: (n.start, n.pitch)):
        start = spec.beat_to_seconds(n.start)
        end = spec.beat_to_seconds(n.start + n.length)
        if end <= start:
            continue
        inst.notes.append(pretty_midi.Note(n.velocity, n.pitch, start, end))
    end_t = spec.duration + spec.master["tail_seconds"]
    inst.control_changes.append(pretty_midi.ControlChange(END_MARKER_CC, 0, end_t))
    pm.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(path))
    return pm


def build(spec: Spec, only: str | None = None) -> list[dict]:
    """Run generators for every part (or one) and return a summary per part."""
    report = []
    for part in spec.parts:
        if only and part["name"] != only:
            continue
        path = spec.midi_path(part)
        if "generator" in part:
            ctx = run_generator(spec, part)
            write_part(spec, part, ctx, path)
            origin = "generated"
        elif path.is_file():
            origin = "hand-written"
        else:
            raise StemmaError(
                f"part {part['name']!r} has no generator and {path} does not exist"
            )
        report.append({"part": part["name"], "midi": str(path.relative_to(spec.dir)),
                       "origin": origin, **summarise(read_notes(path))})
    return report


def read_notes(path: Path) -> list[NoteEvent]:
    if not path.is_file():
        raise StemmaError(f"{path} missing; run `stemma midi` first")
    pm = pretty_midi.PrettyMIDI(str(path))
    return sorted(
        (NoteEvent(n.pitch, n.start, n.end, n.velocity) for i in pm.instruments for n in i.notes),
        key=lambda n: n.start,
    )


def summarise(notes: list[NoteEvent]) -> dict:
    if not notes:
        return {"notes": 0}
    pitches = [n.pitch for n in notes]
    vels = [n.velocity for n in notes]
    return {
        "notes": len(notes),
        "range": [note_name(min(pitches)), note_name(max(pitches))],
        "velocity": [min(vels), max(vels)],
        "first_s": round(notes[0].start, 3),
        "last_end_s": round(max(n.end for n in notes), 3),
    }
