"""Load and validate ``track.yaml`` and derive timing from it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .errors import StemmaError

DEFAULT_MASTER = {
    "lufs": -14.0,
    "true_peak": -1.0,
    "formats": ["wav", "flac"],
    "bit_depth": 24,
    "tail_seconds": 2.0,
    "fade_out_seconds": 0.5,
}

DEFAULT_SCORE = {"grid": 16, "formats": ["musicxml", "ly", "pdf"]}


@cache
def schema() -> dict:
    text = resources.files("stemma").joinpath("schema/track.schema.json").read_text()
    return json.loads(text)


def _path_str(path) -> str:
    out = "$"
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def validate(data: Any) -> list[str]:
    """Return a list of human-readable validation errors (empty when valid)."""
    v = Draft202012Validator(schema())
    errors = [
        f"{_path_str(e.absolute_path)}: {e.message}"
        for e in sorted(v.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if errors or not isinstance(data, dict):
        return errors
    # Rules JSON Schema cannot express.
    for kind in ("sections", "parts", "buses"):
        names = [x["name"] for x in data.get(kind, [])]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            errors.append(f"$.{kind}: duplicate names {dupes}")
    buses = {b["name"] for b in data.get("buses", [])} | {"master"}
    for i, part in enumerate(data["parts"]):
        mix = part.get("mix", {})
        if mix.get("bus", "master") not in buses:
            errors.append(f"$.parts[{i}].mix.bus: unknown bus {mix['bus']!r}")
        for send in mix.get("sends", {}):
            if send not in buses - {"master"}:
                errors.append(f"$.parts[{i}].mix.sends: unknown bus {send!r}")
        sc = mix.get("sidechain")
        if sc:
            names = {p["name"] for p in data["parts"]}
            if sc["source"] == part["name"]:
                errors.append(f"$.parts[{i}].mix.sidechain.source: a part cannot duck itself")
            elif sc["source"] not in names:
                errors.append(f"$.parts[{i}].mix.sidechain.source: unknown part "
                              f"{sc['source']!r}")
        if part["source"] in ("sfizz", "csound", "faust") and "path" not in part.get("sound", {}):
            errors.append(f"$.parts[{i}].sound.path: required for source {part['source']!r}")
        if part["source"] == "elevenlabs":
            if "prompt" not in part.get("sound", {}):
                errors.append(f"$.parts[{i}].sound.prompt: required for source 'elevenlabs'")
            for k in ("generator", "midi"):
                if k in part:
                    errors.append(f"$.parts[{i}].{k}: not used by source 'elevenlabs', "
                                  "which generates audio from sound.prompt")
    sections = {s["name"] for s in data["sections"]}
    parts = {p["name"] for p in data["parts"]}
    seen = set()
    for i, a in enumerate(data.get("automation", [])):
        where = f"$.automation[{i}]"
        if ("part" in a) == ("bus" in a):
            errors.append(f"{where}: give exactly one of part or bus")
            continue
        kind, name = ("part", a["part"]) if "part" in a else ("bus", a["bus"])
        if name not in (parts if kind == "part" else buses - {"master"}):
            errors.append(f"{where}.{kind}: unknown {kind} {name!r}")
        if a["section"] not in sections:
            errors.append(f"{where}.section: unknown section {a['section']!r}")
        if (kind, name, a["section"]) in seen:
            errors.append(f"{where}: {kind} {name!r} already automated in {a['section']!r}")
        seen.add((kind, name, a["section"]))
    return errors


AUDIO_SOURCES = ("elevenlabs",)


def is_audio_part(part: dict) -> bool:
    """True for parts whose audio is generated directly, with no MIDI."""
    return part["source"] in AUDIO_SOURCES


@dataclass(frozen=True)
class Section:
    name: str
    bars: int
    start_bar: int

    def start_beat(self, beats_per_bar: float) -> float:
        return self.start_bar * beats_per_bar


class Spec:
    """A validated track spec with timing helpers."""

    def __init__(self, data: dict, track_dir: Path):
        self.data = data
        self.dir = track_dir
        self.slug = track_dir.name
        self.title: str = data["title"]
        self.tempo: float = float(data["tempo"])
        self.key: str = data["key"]
        self.numerator, self.denominator = data["time_signature"]
        self.sample_rate: int = data.get("sample_rate", 48000)
        self.seed: int = data.get("seed", 0)
        self.master = {**DEFAULT_MASTER, **data.get("master", {})}
        self.mix = {"engine": "auto", "gain_db": 0.0, "fx": [], **data.get("mix", {})}
        self.buses = data.get("buses", [])
        self.score = {**DEFAULT_SCORE, **data.get("score", {})}
        self.targets = data.get("targets", {})
        self.automation = data.get("automation", [])
        self.parts = data["parts"]
        bar = 0
        self.sections: list[Section] = []
        for s in data["sections"]:
            self.sections.append(Section(s["name"], s["bars"], bar))
            bar += s["bars"]
        self.total_bars = bar

    # Timing. Beats are quarter notes; a bar of 6/8 is 3 beats.
    @property
    def beats_per_bar(self) -> float:
        return self.numerator * 4 / self.denominator

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / self.tempo

    def beat_to_seconds(self, beat: float) -> float:
        return beat * self.seconds_per_beat

    def bar_to_seconds(self, bar: float) -> float:
        return self.beat_to_seconds(bar * self.beats_per_bar)

    @property
    def duration(self) -> float:
        """Length of the music in seconds, excluding the tail."""
        return self.bar_to_seconds(self.total_bars)

    def section(self, name: str) -> Section:
        for s in self.sections:
            if s.name == name:
                return s
        raise StemmaError(f"no section {name!r}; sections are {[s.name for s in self.sections]}")

    def section_span(self, name: str | None) -> tuple[float, float]:
        """Return (start, end) seconds for a section, or the whole track."""
        if name is None:
            return 0.0, self.duration
        s = self.section(name)
        return self.bar_to_seconds(s.start_bar), self.bar_to_seconds(s.start_bar + s.bars)

    def part(self, name: str) -> dict:
        for p in self.parts:
            if p["name"] == name:
                return p
        raise StemmaError(f"no part {name!r}; parts are {[p['name'] for p in self.parts]}")

    def midi_path(self, part: dict) -> Path:
        return self.dir / part.get("midi", f"midi/{part['name']}.mid")

    def resolve(self, rel: str) -> Path:
        """Resolve a path relative to the track folder, then the repo ``sounds/``."""
        p = Path(rel)
        if p.is_absolute():
            return p
        for base in (self.dir, self.dir.parent.parent / "sounds", self.dir.parent.parent):
            if (base / p).exists():
                return base / p
        return self.dir / p


def load(track_dir: Path) -> Spec:
    path = track_dir / "track.yaml"
    if not path.is_file():
        raise StemmaError(f"{path} not found; create a track with `stemma new <slug>`")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise StemmaError(f"{path}: invalid YAML: {e}") from e
    errors = validate(data)
    if errors:
        raise StemmaError(f"{path} failed validation:\n  " + "\n  ".join(errors))
    return Spec(data, track_dir)
