"""Reference tracks: generate (or load) audio from the brief and compare the master with it.

The reference is a measuring stick, not material: it stays in the gitignored
``renders/reference/`` folder and is never mixed into the track. To use generated
audio in a track, give a part ``source: elevenlabs`` instead (one instrument per
part). Generation uses the ElevenLabs Music API and needs ``ELEVENLABS_API_KEY``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .analyse import BANDS, analyse_file, keys_compatible, tempo_matches
from .elevenlabs import build_prompt, generate, request_body
from .errors import BackendUnavailable, StemmaError
from .paths import render_root
from .spec import Spec

BAND_GAP_DB = 3.0  # warn when a band differs from the reference by more than this
CENTROID_RATIO = (0.8, 1.25)


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
        if not tempo_matches(ref["tempo_bpm"], spec.tempo):
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
        body = request_body(prompt or build_prompt(spec), seconds or spec.duration, model)
        report["prompt"] = body["prompt"]
        report["model"] = body["model_id"]
        try:
            path, cached = generate(body, folder, "ref", force)
        except BackendUnavailable as e:
            raise BackendUnavailable(f"{e}, or pass --file to compare with audio you "
                                     "already have") from None
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
