"""Effect chains with two interchangeable engines.

``pedalboard`` (Spotify, GPL-3.0, optional extra ``stemma[fx]``) is used when
installed; the ``scipy`` engine in :mod:`stemma.dsp` is always available.
Both read the same parameter names from ``track.yaml``. Effects Pedalboard
has no equivalent for (``NUMPY_ONLY``) run through :mod:`stemma.dsp` on
either engine.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

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


# Effects that always run through stemma.dsp, whatever the engine.
NUMPY_ONLY = {"gate", "transient", "stereo_width", "mid_side_eq", "convolution"}
# Effects whose gain reduction is measured and reported.
DYNAMICS = {"compressor", "limiter", "gate"}
# Effects allowed inside mid_side_eq.
MS_EFFECTS = {"gain", "highpass", "lowpass", "peak", "lowshelf", "highshelf"}
# Effects that turn a mono signal into stereo.
STEREO_MAKERS = {"reverb", "chorus", "convolution", "mid_side_eq"}


@lru_cache(maxsize=16)
def load_ir(path: str, sr: int) -> np.ndarray:
    """Read an impulse response and resample it to ``sr``."""
    from math import gcd

    from scipy.signal import resample_poly

    try:
        ir, file_sr = sf.read(path, dtype="float64", always_2d=True)
    except (OSError, RuntimeError) as e:
        raise StemmaError(f"cannot read impulse response {path}: {e}") from e
    if file_sr != sr:
        g = gcd(sr, file_sr)
        ir = resample_poly(ir, sr // g, file_sr // g, axis=0)
    return ir


def _delay_seconds(fx: dict, tempo: float) -> float:
    if "seconds" in fx:
        return fx["seconds"]
    return fx.get("beats", 0.75) * 60.0 / tempo


def _scipy_fx(x: np.ndarray, fx: dict, sr: int, tempo: float,
              resolve: Callable[[str], Path] | None = None) -> np.ndarray:
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
    if t == "gate":
        return dsp.gate(x, sr, fx.get("threshold_db", -50), fx.get("ratio", 10),
                        fx.get("attack_ms", 1), fx.get("release_ms", 80),
                        fx.get("hold_ms", 0), fx.get("range_db", 40))
    if t == "transient":
        return dsp.transient_shaper(x, sr, fx.get("attack_db", 0), fx.get("sustain_db", 0))
    if t == "stereo_width":
        return dsp.stereo_width(x, sr, fx.get("width", 1.0), fx.get("mono_below_hz"))
    if t == "mid_side_eq":
        x2 = dsp.as_2d(x)
        if x2.shape[1] == 1:
            x2 = np.repeat(x2, 2, axis=1)
        mid, side = dsp.ms_encode(x2)
        for sub in fx.get("mid", []):
            mid = _scipy_fx(mid, sub, sr, tempo)
        for sub in fx.get("side", []):
            side = _scipy_fx(side, sub, sr, tempo)
        return dsp.ms_decode(mid, side)
    if t == "convolution":
        path = resolve(fx["ir"]) if resolve else Path(fx["ir"])
        if not Path(path).is_file():
            raise StemmaError(f"impulse response {fx['ir']!r} not found (looked for {path})")
        predelay = int(sr * fx.get("predelay_ms", 0) / 1000)
        return dsp.convolve(x, load_ir(str(path), sr), fx.get("mix", 0.3), predelay)
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


def _run_one(x: np.ndarray, fx: dict, sr: int, tempo: float, engine: str,
             resolve) -> np.ndarray:
    if engine == "pedalboard" and fx["type"] not in NUMPY_ONLY:
        import pedalboard as pb

        p = _pedalboard_plugin(fx, tempo)
        board = pb.Pedalboard(p if isinstance(p, list) else [p])
        return board(x.T.astype(np.float32), sr).T.astype(np.float64)
    return dsp.as_2d(_scipy_fx(x, fx, sr, tempo, resolve))


def apply_chain(x: np.ndarray, chain: list[dict], sr: int, tempo: float,
                engine: str, resolve: Callable[[str], Path] | None = None,
                meter: list | None = None) -> np.ndarray:
    """Apply effects in order. ``x`` is (samples, channels).

    ``resolve`` maps file names (impulse responses) to paths. When ``meter``
    is a list, one entry per compressor, limiter or gate is appended with the
    gain reduction it applied.
    """
    chain = [fx for fx in chain or [] if not fx.get("bypass")]
    if not chain:
        return x
    x = dsp.as_2d(x)
    # Reverb, chorus and convolution create stereo from mono.
    if x.shape[1] == 1 and any(fx["type"] in STEREO_MAKERS for fx in chain):
        x = np.repeat(x, 2, axis=1)
    for i, fx in enumerate(chain):
        y = _run_one(x, fx, sr, tempo, engine, resolve)
        if meter is not None and fx["type"] in DYNAMICS:
            gr = dsp.gain_reduction(x, y, sr, fx.get("makeup_db", 0))
            meter.append({"fx": i, "type": fx["type"], "gain_reduction_db": gr})
        x = y
    return x
