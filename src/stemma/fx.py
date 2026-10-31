"""Effect chains with two interchangeable engines.

``pedalboard`` (Spotify, GPL-3.0, optional extra ``stemma[fx]``) is used when
installed; the ``scipy`` engine in :mod:`stemma.dsp` is always available.
Both read the same parameter names from ``track.yaml``.
"""

from __future__ import annotations

import numpy as np

from . import dsp
from .errors import StemmaError


def pedalboard_available() -> bool:
    try:
        import pedalboard  # noqa: F401
    except ImportError:
        return False
    return True


def choose_engine(requested: str = "auto") -> str:
    if requested == "pedalboard" and not pedalboard_available():
        raise StemmaError("mix.engine is 'pedalboard' but it is not installed; "
                          "run `uv sync --extra fx`")
    if requested == "auto":
        return "pedalboard" if pedalboard_available() else "scipy"
    return requested


def _delay_seconds(fx: dict, tempo: float) -> float:
    if "seconds" in fx:
        return fx["seconds"]
    return fx.get("beats", 0.75) * 60.0 / tempo


def _scipy_fx(x: np.ndarray, fx: dict, sr: int, tempo: float) -> np.ndarray:
    t = fx["type"]
    if t == "gain":
        return x * dsp.db_to_amp(fx["gain_db"])
    if t in ("highpass", "lowpass"):
        return dsp.filt(x, t, fx["cutoff_hz"], sr, fx.get("q", 0.7071))
    if t in ("peak", "lowshelf", "highshelf"):
        return dsp.filt(x, t, fx["freq_hz"], sr, fx.get("q", 0.7071), fx["gain_db"])
    if t == "compressor":
        return dsp.compressor(x, sr, fx.get("threshold_db", -18), fx.get("ratio", 4),
                              fx.get("attack_ms", 10), fx.get("release_ms", 120),
                              fx.get("makeup_db", 0))
    if t == "limiter":
        return dsp.limiter(x, sr, fx.get("threshold_db", -1), fx.get("release_ms", 60))
    if t == "reverb":
        return dsp.reverb(x, sr, fx.get("room_size", 0.5), fx.get("damping", 0.5),
                          fx.get("wet", 0.33), fx.get("dry", 0.4), fx.get("width", 1.0))
    if t == "delay":
        return dsp.delay(x, sr, _delay_seconds(fx, tempo), fx.get("feedback", 0.3),
                         fx.get("mix", 0.25))
    if t == "distortion":
        k = dsp.db_to_amp(fx.get("drive_db", 12))
        return np.tanh(x * k) / np.tanh(k)
    if t == "chorus":
        return dsp.chorus(x, sr, fx.get("rate_hz", 0.8), fx.get("depth", 0.25),
                          fx.get("mix", 0.5))
    raise StemmaError(f"unknown effect {t!r}")


def _pedalboard_plugin(fx: dict, tempo: float):
    import pedalboard as pb

    t = fx["type"]
    if t == "gain":
        return pb.Gain(gain_db=fx["gain_db"])
    if t == "highpass":
        return pb.HighpassFilter(cutoff_frequency_hz=fx["cutoff_hz"])
    if t == "lowpass":
        return pb.LowpassFilter(cutoff_frequency_hz=fx["cutoff_hz"])
    if t == "peak":
        return pb.PeakFilter(cutoff_frequency_hz=fx["freq_hz"], gain_db=fx["gain_db"],
                             q=fx.get("q", 0.7071))
    if t == "lowshelf":
        return pb.LowShelfFilter(cutoff_frequency_hz=fx["freq_hz"], gain_db=fx["gain_db"],
                                 q=fx.get("q", 0.7071))
    if t == "highshelf":
        return pb.HighShelfFilter(cutoff_frequency_hz=fx["freq_hz"], gain_db=fx["gain_db"],
                                  q=fx.get("q", 0.7071))
    if t == "compressor":
        comp = pb.Compressor(threshold_db=fx.get("threshold_db", -18), ratio=fx.get("ratio", 4),
                             attack_ms=fx.get("attack_ms", 10),
                             release_ms=fx.get("release_ms", 120))
        if fx.get("makeup_db"):
            return [comp, pb.Gain(gain_db=fx["makeup_db"])]
        return comp
    if t == "limiter":
        return pb.Limiter(threshold_db=fx.get("threshold_db", -1),
                          release_ms=fx.get("release_ms", 60))
    if t == "reverb":
        return pb.Reverb(room_size=fx.get("room_size", 0.5), damping=fx.get("damping", 0.5),
                         wet_level=fx.get("wet", 0.33), dry_level=fx.get("dry", 0.4),
                         width=fx.get("width", 1.0))
    if t == "delay":
        return pb.Delay(delay_seconds=_delay_seconds(fx, tempo),
                        feedback=fx.get("feedback", 0.3), mix=fx.get("mix", 0.25))
    if t == "distortion":
        return pb.Distortion(drive_db=fx.get("drive_db", 12))
    if t == "chorus":
        return pb.Chorus(rate_hz=fx.get("rate_hz", 0.8), depth=fx.get("depth", 0.25),
                         mix=fx.get("mix", 0.5))
    raise StemmaError(f"unknown effect {t!r}")


def apply_chain(x: np.ndarray, chain: list[dict], sr: int, tempo: float,
                engine: str) -> np.ndarray:
    """Apply effects in order. ``x`` is (samples, channels)."""
    chain = [fx for fx in chain or [] if not fx.get("bypass")]
    if not chain:
        return x
    x = dsp.as_2d(x)
    # Reverb and chorus create stereo from mono.
    if x.shape[1] == 1 and any(fx["type"] in ("reverb", "chorus") for fx in chain):
        x = np.repeat(x, 2, axis=1)
    if engine == "pedalboard":
        import pedalboard as pb

        plugins = []
        for fx in chain:
            p = _pedalboard_plugin(fx, tempo)
            plugins += p if isinstance(p, list) else [p]
        y = pb.Pedalboard(plugins)(x.T.astype(np.float32), sr)
        return y.T.astype(np.float64)
    for fx in chain:
        x = dsp.as_2d(_scipy_fx(x, fx, sr, tempo))
    return x
