"""Small music-theory helpers: note names, scales and chords."""

from __future__ import annotations

import re

PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

MODES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
}

_NOTE_RE = re.compile(r"^([A-Ga-g])(#|b)?(-?\d+)$")


def pitch_class(name: str) -> int:
    pc = PITCH_CLASSES[name[0].upper()]
    if len(name) > 1:
        pc += {"#": 1, "b": -1}[name[1]]
    return pc % 12


def note(name: str | int) -> int:
    """MIDI note number from a name such as ``"A2"`` or ``"F#4"`` (C4 = 60)."""
    if isinstance(name, int):
        return name
    m = _NOTE_RE.match(name)
    if not m:
        raise ValueError(f"bad note name {name!r}")
    letter, acc, octave = m.groups()
    return pitch_class(letter + (acc or "")) + 12 * (int(octave) + 1)


def note_name(midi: int) -> str:
    return f"{NAMES_SHARP[midi % 12]}{midi // 12 - 1}"


def parse_key(key: str) -> tuple[int, str]:
    tonic, mode = key.split()
    return pitch_class(tonic), mode


class Scale:
    """A key such as ``Scale("A minor")``; degrees are 0-based and may be negative."""

    def __init__(self, key: str):
        self.tonic, self.mode = parse_key(key)
        self.steps = MODES[self.mode]

    def degree(self, degree: int, octave: int = 4) -> int:
        """MIDI note for a scale degree (0 = tonic) in the given octave."""
        o, d = divmod(degree, 7)
        return 12 * (octave + 1 + o) + self.tonic + self.steps[d]

    def chord(self, degree: int, octave: int = 3, size: int = 3) -> list[int]:
        """Diatonic chord built in thirds on a degree, e.g. ``chord(0)`` is the tonic triad."""
        return [self.degree(degree + 2 * i, octave) for i in range(size)]

    def contains(self, midi: int) -> bool:
        return (midi - self.tonic) % 12 in self.steps

    def nearest(self, midi: int) -> int:
        """Snap a note to the nearest scale tone (ties go down)."""
        for delta in (0, -1, 1, -2, 2):
            if self.contains(midi + delta):
                return midi + delta
        return midi
