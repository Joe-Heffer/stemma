"""ElevenLabs Music API: build prompts from the spec and fetch audio, cached by request.

Used by ``stemma reference`` (a full-mix reference to measure against) and by
parts with ``source: elevenlabs`` (one instrument per part, used in the track).
Needs ``ELEVENLABS_API_KEY``. Only the standard library is used for HTTP.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .errors import BackendUnavailable, StemmaError
from .spec import Spec

API_URL = "https://api.elevenlabs.io/v1/music"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL = "music_v1"
KEY_ENV = "ELEVENLABS_API_KEY"
MAX_PROMPT = 4100
MIN_MS, MAX_MS = 3_000, 600_000

ROLE_WORDS = {"drums": "drum kit", "percussion": "percussion", "bass": "bass",
              "lead": "lead melody", "harmony": "chordal accompaniment", "pad": "pad",
              "arp": "arpeggio", "fx": "sound effects and textures", "vocal": "vocal line",
              "other": "instrument"}


def brief_text(spec: Spec) -> str:
    """The text under ``## Brief`` in the track's notes.md, or an empty string."""
    notes = spec.dir / "notes.md"
    if not notes.is_file():
        return ""
    m = re.search(r"^## Brief\s*\n(.*?)(?=^## |\Z)", notes.read_text(), re.M | re.S)
    return " ".join(m.group(1).split()) if m else ""


def _track_lines(spec: Spec, what: str) -> list[str]:
    lines = [f"{what} for a track titled “{spec.title}”, {spec.tempo:g} bpm, "
             f"in {spec.key}, {spec.numerator}/{spec.denominator} time, "
             f"about {round(spec.duration)} seconds long."]
    brief = brief_text(spec)
    if brief:
        lines.append(f"Brief: {brief}")
    form = []
    for sec, raw in zip(spec.sections, spec.data["sections"], strict=True):
        desc = raw.get("description")
        form.append(f"{sec.name} ({sec.bars} bars{': ' + desc if desc else ''})")
    lines.append("Form: " + "; ".join(form) + ".")
    return lines


def build_prompt(spec: Spec) -> str:
    """Prompt for a full instrumental mix (the reference track)."""
    lines = _track_lines(spec, "An instrumental")
    lines.append("Instrumental only, no vocals.")
    return "\n".join(lines)[:MAX_PROMPT]


def part_prompt(spec: Spec, part: dict) -> str:
    """Prompt for one instrument on its own, from the spec and the part's ``sound.prompt``."""
    role = part.get("role", "other")
    word = ROLE_WORDS.get(role, "instrument")
    lines = _track_lines(spec, f"A solo {word} part ({part['name']})")
    lines.append(f"This part: {part['sound']['prompt'].strip()}")
    rules = ["Play this one instrument only, with no other instruments"]
    if role not in ("drums", "percussion"):
        rules.append("no drums or percussion")
    if role != "vocal":
        rules.append("no vocals")
    rules.append("start on the first beat and hold the tempo steadily throughout")
    lines.append(", ".join(rules) + ".")
    return "\n".join(lines)[:MAX_PROMPT]


def request_body(prompt: str, seconds: float, model: str | None = None) -> dict:
    ms = int(round(seconds * 1000))
    return {"prompt": prompt[:MAX_PROMPT], "music_length_ms": max(MIN_MS, min(MAX_MS, ms)),
            "model_id": model or DEFAULT_MODEL, "force_instrumental": True}


def digest(body: dict) -> str:
    blob = json.dumps({**body, "output_format": OUTPUT_FORMAT}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def generate(body: dict, folder: Path, prefix: str = "ref",
             force: bool = False) -> tuple[Path, bool]:
    """Call the API unless an identical request is already on disk. Returns (file, cached)."""
    stem = f"{prefix}-{digest(body)}"
    dest = folder / f"{stem}.mp3"
    if dest.is_file() and not force:
        return dest, True
    key = os.environ.get(KEY_ENV)
    if not key:
        raise BackendUnavailable(f"set {KEY_ENV} to generate audio with ElevenLabs")
    req = urllib.request.Request(
        f"{API_URL}?output_format={OUTPUT_FORMAT}", data=json.dumps(body).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"}, method="POST")
    folder.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".mp3.part")
    try:
        with urllib.request.urlopen(req, timeout=600) as r, tmp.open("wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        detail = e.read().decode(errors="replace")[:500]
        raise StemmaError(f"ElevenLabs API returned {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        raise StemmaError(f"could not reach the ElevenLabs API: {e.reason}") from None
    tmp.rename(dest)
    meta = {**body, "output_format": OUTPUT_FORMAT, "url": API_URL,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (folder / f"{stem}.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest, False


def generated_dir(spec: Spec) -> Path:
    """Where generated part audio is kept: gitignored, and outside renders/ so
    ``make clean`` does not throw away audio that cost credits."""
    return spec.dir / "generated"


def part_audio(spec: Spec, part: dict, force: bool = False) -> tuple[Path, bool]:
    """The generated audio file for an ``elevenlabs`` part (from the cache or the API)."""
    sound = part.get("sound", {})
    body = request_body(part_prompt(spec, part), spec.duration, sound.get("model"))
    return generate(body, generated_dir(spec), prefix=part["name"], force=force)
