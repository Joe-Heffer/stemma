"""Reference tracks: generate (or load) audio from the brief and compare the master with it.

The reference is a measuring stick, not material: it stays in the gitignored
``renders/reference/`` folder and is never mixed, sampled or rendered into a part.
Generation uses the ElevenLabs Music API and needs ``ELEVENLABS_API_KEY``.
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

from .analyse import BANDS, analyse_file, keys_compatible
from .errors import BackendUnavailable, StemmaError
from .paths import render_root
from .spec import Spec

API_URL = "https://api.elevenlabs.io/v1/music"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL = "music_v1"
KEY_ENV = "ELEVENLABS_API_KEY"
MAX_PROMPT = 4100
MIN_MS, MAX_MS = 3_000, 600_000

BAND_GAP_DB = 3.0  # warn when a band differs from the reference by more than this
CENTROID_RATIO = (0.8, 1.25)


def brief_text(spec: Spec) -> str:
    """The text under ``## Brief`` in the track's notes.md, or an empty string."""
    notes = spec.dir / "notes.md"
    if not notes.is_file():
        return ""
    m = re.search(r"^## Brief\s*\n(.*?)(?=^## |\Z)", notes.read_text(), re.M | re.S)
    return " ".join(m.group(1).split()) if m else ""


def build_prompt(spec: Spec) -> str:
    lines = [f"An instrumental track titled “{spec.title}”, {spec.tempo:g} bpm, "
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
    lines.append("Instrumental only, no vocals.")
    return "\n".join(lines)[:MAX_PROMPT]


def request_body(spec: Spec, prompt: str | None, seconds: float | None,
                 model: str | None) -> dict:
    prompt = (prompt or build_prompt(spec))[:MAX_PROMPT]
    ms = int(round((seconds if seconds else spec.duration) * 1000))
    return {"prompt": prompt, "music_length_ms": max(MIN_MS, min(MAX_MS, ms)),
            "model_id": model or DEFAULT_MODEL, "force_instrumental": True}


def _digest(body: dict) -> str:
    blob = json.dumps({**body, "output_format": OUTPUT_FORMAT}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def generate(body: dict, folder: Path, force: bool = False) -> tuple[Path, bool]:
    """Call the API unless an identical request is already on disk. Returns (file, cached)."""
    stem = f"ref-{_digest(body)}"
    dest = folder / f"{stem}.mp3"
    if dest.is_file() and not force:
        return dest, True
    key = os.environ.get(KEY_ENV)
    if not key:
        raise BackendUnavailable(f"set {KEY_ENV} to generate a reference, or pass --file "
                                 "to compare with audio you already have")
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


def _diff(a, b, nd=2):
    return None if a is None or b is None else round(a - b, nd)


def compare(master: dict, ref: dict) -> dict:
    """Master minus reference for the figures that survive loudness normalisation."""
    out = {"bands_db": {}}
    for band in BANDS:
        m, r = master["bands_db"][band], ref["bands_db"][band]
        out["bands_db"][band] = {"master": m, "reference": r, "diff": _diff(m, r)}
    for key in ("spectral_centroid_hz", "stereo_width_above_300hz", "crest_factor_db",
                "tempo_bpm"):
        m, r = master.get(key), ref.get(key)
        out[key] = {"master": m, "reference": r, "diff": _diff(m, r, 3)}
    return out


def _warnings(spec: Spec, ref: dict, cmp: dict | None) -> list[str]:
    warn = []
    if ref.get("silent"):
        return ["reference: silent"]
    if ref.get("tempo_bpm"):
        ratio = ref["tempo_bpm"] / spec.tempo
        if min(abs(ratio - r) for r in (0.5, 1, 2)) > 0.04:
            warn.append(f"reference: estimated tempo {ref['tempo_bpm']} vs spec {spec.tempo}; "
                        "the generated audio may not follow the brief")
    if ref.get("key") and not keys_compatible(ref["key"], spec.key):
        warn.append(f"reference: estimated key {ref['key']} vs spec {spec.key}")
    if cmp:
        for band, v in cmp["bands_db"].items():
            if v["diff"] is not None and abs(v["diff"]) > BAND_GAP_DB:
                side = "above" if v["diff"] > 0 else "below"
                warn.append(f"master {band} band is {abs(v['diff'])} dB {side} the reference")
        c = cmp["spectral_centroid_hz"]
        if c["master"] and c["reference"]:
            ratio = c["master"] / c["reference"]
            if not CENTROID_RATIO[0] <= ratio <= CENTROID_RATIO[1]:
                word = "brighter" if ratio > 1 else "darker"
                warn.append(f"master is {word} than the reference: centroid {c['master']} Hz "
                            f"vs {c['reference']} Hz")
    return warn


def reference(spec: Spec, prompt: str | None = None, seconds: float | None = None,
              model: str | None = None, force: bool = False,
              file: Path | None = None) -> dict:
    folder = render_root(spec.dir) / "reference"
    report: dict = {"track": spec.slug}
    if file:
        if not file.is_file():
            raise StemmaError(f"{file} not found")
        path, cached = file, None
    else:
        body = request_body(spec, prompt, seconds, model)
        report["prompt"] = body["prompt"]
        report["model"] = body["model_id"]
        path, cached = generate(body, folder, force)
    report["file"] = str(path)
    report["cached"] = cached
    ref = analyse_file(path)
    report["reference"] = ref
    master_wav = render_root(spec.dir) / "master.wav"
    cmp = None
    if master_wav.is_file() and not ref.get("silent"):
        master = analyse_file(master_wav)
        if not master.get("silent"):
            cmp = compare(master, ref)
    report["compare"] = cmp
    report["warnings"] = _warnings(spec, ref, cmp)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
