"""API for part generator scripts.

A generator is a Python file in ``tracks/<slug>/parts/`` that defines::

    def build(ctx):
        for bar in ctx.bars():           # every bar, or ctx.bars("groove")
            ctx.add("A1", bar + 0, 0.5)  # pitch, start beat, length in beats
        # nothing to return: notes collected on ctx are written to MIDI

Times are in beats (quarter notes) from the start of the track. ``ctx.rng`` is
a seeded ``numpy.random.Generator``, so humanisation is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spec import Section, Spec
from .theory import Scale, note


@dataclass
class Note:
    pitch: int
    start: float  # beats
    length: float  # beats
    velocity: int = 90


class Context:
    def __init__(self, spec: Spec, part: dict):
        self.spec = spec
        self.part = part
        self.name: str = part["name"]
        self.tempo = spec.tempo
        self.beats_per_bar = spec.beats_per_bar
        self.total_bars = spec.total_bars
        self.sections: list[Section] = spec.sections
        self.scale = Scale(spec.key)
        seed = (spec.seed * 1_000_003 + sum(map(ord, self.name))) % 2**32
        self.rng = np.random.default_rng(seed)
        self.notes: list[Note] = []

    # Navigation -----------------------------------------------------------
    def section(self, name: str) -> Section:
        return self.spec.section(name)

    def bars(self, *sections: str) -> list[float]:
        """Start beat of each bar, in order, optionally limited to some sections."""
        chosen = [self.section(s) for s in sections] if sections else self.sections
        return [
            (s.start_bar + i) * self.beats_per_bar for s in chosen for i in range(s.bars)
        ]

    def section_at(self, beat: float) -> Section:
        bar = int(beat // self.beats_per_bar)
        for s in self.sections:
            if s.start_bar <= bar < s.start_bar + s.bars:
                return s
        return self.sections[-1]

    def bar_in_section(self, beat: float) -> int:
        """0-based index of the bar within its section."""
        return int(beat // self.beats_per_bar) - self.section_at(beat).start_bar

    # Writing --------------------------------------------------------------
    def add(self, pitch: int | str, start: float, length: float, velocity: int = 90) -> Note:
        n = Note(note(pitch), float(start), float(length), int(np.clip(velocity, 1, 127)))
        self.notes.append(n)
        return n

    def chord(self, pitches, start: float, length: float, velocity: int = 80, strum: float = 0):
        for i, p in enumerate(pitches):
            self.add(p, start + i * strum, length - i * strum, velocity)

    def humanise(self, timing: float = 0.01, velocity: int = 6):
        """Jitter start times (in beats) and velocities of all notes so far."""
        for n in self.notes:
            n.start = max(0.0, n.start + self.rng.normal(0, timing))
            n.velocity = int(np.clip(n.velocity + self.rng.normal(0, velocity), 1, 127))
