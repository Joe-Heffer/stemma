"""Loudness-normalise the mixdown and limit true peaks."""

from __future__ import annotations

import json

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from . import dsp
from .errors import StemmaError
from .paths import render_root
from .spec import Spec


def integrated_lufs(x: np.ndarray, sr: int) -> float:
    meter = pyln.Meter(sr)
    return float(meter.integrated_loudness(dsp.as_2d(x)))


# The limiter is working too hard above these (dB of gain reduction).
LIMITER_MAX_DB = 6.0
LIMITER_MEAN_DB = 2.0

FORMATS = {"wav": ("WAV", None), "flac": ("FLAC", None),
           "mp3": ("MP3", "MPEG_LAYER_III"), "ogg": ("OGG", "VORBIS")}


def limiter_stats(x: np.ndarray, gain: np.ndarray) -> dict:
    """Gain reduction of the limiter over the audible part of ``x``."""
    gr = -20 * np.log10(np.maximum(gain, 1e-9))
    audible = np.max(np.abs(dsp.as_2d(x)), axis=1) > 1e-4
    sel = gr[audible] if audible.any() else gr
    return {"max_db": round(float(sel.max()), 2), "mean_db": round(float(sel.mean()), 2),
            "percent_over_1db": round(float(np.mean(sel > 1) * 100), 1)}


def master_audio(x: np.ndarray, sr: int, lufs: float, true_peak: float,
                 fade_out: float = 0.0, iterations: int = 6, normalise: bool = True,
                 release_ms: float = 60.0, lookahead_ms: float = 4.0
                 ) -> tuple[np.ndarray, dict]:
    """Return (mastered audio, report). Gain toward the target, then limit."""
    x = dsp.as_2d(x).astype(np.float64)
    start = integrated_lufs(x, sr)
    if not np.isfinite(start):
        raise StemmaError("mix is too quiet to measure loudness")
    gain_db = lufs - start if normalise else 0.0

    def limit(g):
        return dsp.limiter(x * dsp.db_to_amp(g), sr, ceiling_db=true_peak,
                           release_ms=release_ms, lookahead_ms=lookahead_ms,
                           return_gain=True)

    y, gain = limit(gain_db)
    for _ in range(iterations if normalise else 0):
        got = integrated_lufs(y, sr)
        if abs(got - lufs) < 0.1:
            break
        gain_db += lufs - got
        y, gain = limit(gain_db)
    stats = limiter_stats(x * dsp.db_to_amp(gain_db), gain)
    if fade_out > 0:
        k = min(len(y), int(fade_out * sr))
        y[-k:] *= np.linspace(1, 0, k)[:, None] ** 2
    tp = dsp.amp_to_db(float(dsp.true_peak_envelope(y).max()))
    warnings_ = []
    if stats["max_db"] > LIMITER_MAX_DB or stats["mean_db"] > LIMITER_MEAN_DB:
        warnings_.append(f"limiter: up to {stats['max_db']} dB of gain reduction "
                         f"(mean {stats['mean_db']} dB); it is working too hard. Tame the "
                         "loudest part or the peaks in the mix, or lower master.lufs")
    return y, {"input_lufs": round(start, 2), "gain_db": round(gain_db, 2),
               "lufs": round(integrated_lufs(y, sr), 2), "true_peak_dbtp": round(tp, 2),
               "limiter": stats, "warnings": warnings_}


def tpdf_dither(x: np.ndarray, bits: int, seed: int = 0) -> np.ndarray:
    lsb = 2.0 / 2**bits
    rng = np.random.default_rng(seed)
    return x + (rng.random(x.shape) - rng.random(x.shape)) * lsb


def master(spec: Spec, section: str | None = None) -> dict:
    root = render_root(spec.dir, section)
    src = root / "mix.wav"
    if not src.is_file():
        raise StemmaError(f"{src} missing; run `stemma mix {spec.slug}` first")
    x, sr = sf.read(str(src), dtype="float64", always_2d=True)
    m = spec.master
    meter: list = []
    chain = m.get("fx", [])
    if chain:
        from .fx import apply_chain, choose_engine

        x = apply_chain(x, chain, sr, spec.tempo, choose_engine(spec.mix.get("engine", "auto")),
                        spec.resolve, meter)
    lim = m.get("limiter", {})
    y, report = master_audio(x, sr, m["lufs"], m["true_peak"], m["fade_out_seconds"],
                             normalise=m.get("normalise", True),
                             release_ms=lim.get("release_ms", 60),
                             lookahead_ms=lim.get("lookahead_ms", 4))
    if chain:
        report["chain"] = [fx["type"] for fx in chain if not fx.get("bypass")]
    if meter:
        report["dynamics"] = meter
    bits = m["bit_depth"]
    if bits == 16:
        y = tpdf_dither(y, 16, spec.seed)
    y = np.clip(y, -1.0, 1.0 - 2.0**-23)
    written = []
    available = sf.available_formats()
    for fmt in m["formats"]:
        container, subtype = FORMATS[fmt]
        if container not in available:
            raise StemmaError(f"this libsndfile cannot write {fmt}; drop it from master.formats")
        out = root / f"master.{fmt}"
        sf.write(str(out), y, sr, subtype=subtype or f"PCM_{bits}", format=container)
        written.append(str(out.relative_to(spec.dir)))
    report.update({"target_lufs": m["lufs"], "target_true_peak": m["true_peak"],
                   "files": written})
    (root / "master.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
