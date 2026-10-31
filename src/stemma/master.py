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


def master_audio(x: np.ndarray, sr: int, lufs: float, true_peak: float,
                 fade_out: float = 0.0, iterations: int = 6) -> tuple[np.ndarray, dict]:
    """Return (mastered audio, report). Gain toward the target, then limit."""
    x = dsp.as_2d(x).astype(np.float64)
    start = integrated_lufs(x, sr)
    if not np.isfinite(start):
        raise StemmaError("mix is too quiet to measure loudness")
    gain_db = lufs - start
    y = x
    for _ in range(iterations):
        y = dsp.limiter(x * dsp.db_to_amp(gain_db), sr, ceiling_db=true_peak)
        got = integrated_lufs(y, sr)
        if abs(got - lufs) < 0.1:
            break
        gain_db += lufs - got
    if fade_out > 0:
        k = min(len(y), int(fade_out * sr))
        y[-k:] *= np.linspace(1, 0, k)[:, None] ** 2
    tp = dsp.amp_to_db(float(dsp.true_peak_envelope(y).max()))
    return y, {"input_lufs": round(start, 2), "gain_db": round(gain_db, 2),
               "lufs": round(integrated_lufs(y, sr), 2), "true_peak_dbtp": round(tp, 2)}


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
    y, report = master_audio(x, sr, m["lufs"], m["true_peak"], m["fade_out_seconds"])
    bits = m["bit_depth"]
    if bits == 16:
        y = tpdf_dither(y, 16, spec.seed)
    y = np.clip(y, -1.0, 1.0 - 2.0**-23)
    written = []
    for fmt in m["formats"]:
        out = root / f"master.{fmt}"
        sf.write(str(out), y, sr, subtype=f"PCM_{bits}", format=fmt.upper())
        written.append(str(out.relative_to(spec.dir)))
    report.update({"target_lufs": m["lufs"], "target_true_peak": m["true_peak"],
                   "files": written})
    (root / "master.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
