"""Short-term and momentary loudness and loudness range (EBU R128, Tech 3342).

Uses the BS.1770 K-weighting filters as pyloudnorm does (RBJ high shelf,
+4 dB at 1.5 kHz, and a 38 Hz highpass), with channel weights of 1, so
figures agree with ``pyloudnorm`` integrated loudness for stereo.
"""

from __future__ import annotations

import numpy as np

from . import dsp

ABS_GATE = -70.0
LRA_REL_GATE = -20.0


def k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    y = dsp.filt(dsp.as_2d(x), "highshelf", 1500.0, sr, 1 / np.sqrt(2), 4.0)
    return dsp.filt(y, "highpass", 38.0, sr, 0.5)


def block_loudness(x: np.ndarray, sr: int, window: float, hop: float = 0.1
                   ) -> tuple[np.ndarray, np.ndarray]:
    """(start times in seconds, LUFS) of sliding ``window``-second blocks."""
    y = k_weight(x, sr)
    power = np.sum(y**2, axis=1)  # channel weights 1
    w, h = int(window * sr), max(1, int(hop * sr))
    if len(power) < w:
        return np.array([]), np.array([])
    c = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, len(power) - w + 1, h)
    ms = (c[starts + w] - c[starts]) / w
    return starts / sr, -0.691 + 10 * np.log10(np.maximum(ms, 1e-20))


def loudness_range(short_term: np.ndarray) -> float | None:
    """LRA in LU from short-term (3 s) loudness values."""
    st = short_term[short_term > ABS_GATE]
    if len(st) < 2:
        return None
    mean = 10 * np.log10(np.mean(10 ** (st / 10)))
    st = st[st > mean + LRA_REL_GATE]
    if len(st) < 2:
        return None
    return float(np.percentile(st, 95) - np.percentile(st, 10))


def loudness_stats(x: np.ndarray, sr: int) -> dict:
    _, st = block_loudness(x, sr, 3.0)
    _, mo = block_loudness(x, sr, 0.4)

    def top(v):
        v = v[v > ABS_GATE]
        return round(float(v.max()), 2) if len(v) else None

    lra = loudness_range(st) if len(st) else None
    return {"loudness_range_lu": None if lra is None else round(lra, 2),
            "short_term_lufs_max": top(st), "momentary_lufs_max": top(mo)}
