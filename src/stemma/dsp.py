"""Pure numpy/scipy DSP used by the built-in synth and the fallback mix engine."""

from __future__ import annotations

import numpy as np
from scipy import signal


def db_to_amp(db: float) -> float:
    return float(10 ** (db / 20))


def amp_to_db(a: float, floor: float = -120.0) -> float:
    return float(20 * np.log10(a)) if a > 10 ** (floor / 20) else floor


def as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


# Biquads (RBJ Audio EQ Cookbook) -----------------------------------------

def biquad(kind: str, freq: float, sr: int, q: float = 0.7071, gain_db: float = 0.0):
    """Return (b, a) for a biquad filter."""
    freq = min(freq, 0.49 * sr)
    w0 = 2 * np.pi * freq / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(A) * alpha
        s = 1 if kind == "lowshelf" else -1
        b = [A * ((A + 1) - s * (A - 1) * cw + sq),
             s * 2 * A * ((A - 1) - s * (A + 1) * cw),
             A * ((A + 1) - s * (A - 1) * cw - sq)]
        a = [(A + 1) + s * (A - 1) * cw + sq,
             -s * 2 * ((A - 1) + s * (A + 1) * cw),
             (A + 1) + s * (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b, a = np.asarray(b), np.asarray(a)
    return b / a[0], a / a[0]


def filt(x: np.ndarray, kind: str, freq: float, sr: int, q: float = 0.7071,
         gain_db: float = 0.0) -> np.ndarray:
    b, a = biquad(kind, freq, sr, q, gain_db)
    return signal.lfilter(b, a, x, axis=0)


def varying_lowpass(x: np.ndarray, cutoff: np.ndarray, sr: int, q: float,
                    block: int = 128) -> np.ndarray:
    """Lowpass a mono signal with a time-varying cutoff, updated per block."""
    out = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), block):
        b, a = biquad("lowpass", float(cutoff[i]), sr, q)
        out[i:i + block], zi = signal.lfilter(b, a, x[i:i + block], zi=zi)
    return out


# Oscillators --------------------------------------------------------------

def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1
    m = t > 1 - dt
    x = (t[m] - 1) / dt[m]
    out[m] = x * x + x + x + 1
    return out


def oscillator(wave: str, freq: np.ndarray, sr: int, phase0: float = 0.0,
               pulse_width: float = 0.5) -> np.ndarray:
    """Band-limited (PolyBLEP) oscillator; ``freq`` is per-sample Hz."""
    dt = freq / sr
    t = (phase0 + np.cumsum(dt) - dt[0]) % 1.0
    if wave == "sine":
        return np.sin(2 * np.pi * t)
    if wave == "triangle":
        return 1 - 4 * np.abs(t - 0.5)
    if wave == "saw":
        return 2 * t - 1 - _polyblep(t, dt)
    if wave in ("square", "pulse"):
        pw = pulse_width if wave == "pulse" else 0.5
        sq = np.where(t < pw, 1.0, -1.0)
        # Subtract the DC offset of an asymmetric pulse.
        return sq + _polyblep(t, dt) - _polyblep((t + 1 - pw) % 1.0, dt) - (2 * pw - 1)
    raise ValueError(f"unknown wave {wave!r}")


def adsr(gate: int, total: int, sr: int, attack: float, decay: float, sustain: float,
         release: float) -> np.ndarray:
    """Exponential-segment ADSR envelope; ``gate`` and ``total`` are in samples."""
    t = np.arange(total) / sr
    a = max(attack, 1e-4)
    env = np.where(
        t < a, t / a, sustain + (1 - sustain) * np.exp(-(t - a) / max(decay / 4, 1e-4))
    )
    g = min(gate, total) - 1
    if g + 1 < total:
        level = env[max(g, 0)]
        tr = t[g + 1:] - t[g]
        env[g + 1:] = level * np.exp(-tr / max(release / 4, 1e-4))
    # Short fade to exactly zero at the end, so voices never click off.
    fade = min(total, int(0.003 * sr))
    if fade:
        env[-fade:] *= np.linspace(1, 0, fade)
    return env


# Dynamics and time-based effects -----------------------------------------

def envelope_follower(level: np.ndarray, sr: int, attack_ms: float,
                      release_ms: float) -> np.ndarray:
    """Peak-ish envelope: attack via running max, release via one-pole smoothing."""
    from scipy.ndimage import maximum_filter1d

    att = max(1, int(sr * attack_ms / 1000))
    held = maximum_filter1d(level, size=att, origin=-(att // 2))
    coef = np.exp(-1.0 / (sr * release_ms / 1000))
    return signal.lfilter([1 - coef], [1, -coef], held)


def compressor(x: np.ndarray, sr: int, threshold_db=-18.0, ratio=4.0, attack_ms=10.0,
               release_ms=120.0, makeup_db=0.0) -> np.ndarray:
    x2 = as_2d(x)
    level = np.max(np.abs(x2), axis=1)
    env = envelope_follower(level, sr, attack_ms, release_ms)
    env_db = 20 * np.log10(np.maximum(env, 1e-9))
    over = np.maximum(env_db - threshold_db, 0)
    gain_db = -over * (1 - 1 / ratio) + makeup_db
    y = x2 * (10 ** (gain_db / 20))[:, None]
    return y if x.ndim == 2 else y[:, 0]


def window_min(x: np.ndarray, before: int, after: int) -> np.ndarray:
    """Minimum of ``x`` over the window ``[n - before, n + after]`` for each n."""
    from scipy.ndimage import minimum_filter1d

    size = before + after + 1
    return minimum_filter1d(x, size=size, origin=before - size // 2, mode="nearest")


def true_peak_envelope(x: np.ndarray, oversample: int = 4) -> np.ndarray:
    """Per-sample absolute peak of the oversampled signal (all channels)."""
    x2 = as_2d(x)
    over = signal.resample_poly(x2, oversample, 1, axis=0)
    peak = np.max(np.abs(over), axis=1)
    peak = peak[: len(x2) * oversample].reshape(-1, oversample).max(axis=1)
    return np.pad(peak, (0, len(x2) - len(peak)))


def limiter(x: np.ndarray, sr: int, ceiling_db: float = -1.0, release_ms: float = 60.0,
            lookahead_ms: float = 4.0, oversample: int = 4, return_gain: bool = False):
    """Look-ahead brickwall limiter on the true (oversampled) peak.

    The gain needed at each sample is held for the look-ahead before and the
    release time after it, then smoothed with a window shorter than the
    look-ahead, so gain is always at or below what each peak needs. With
    ``return_gain`` it returns ``(audio, gain)``, the per-sample linear gain.
    """
    x2 = as_2d(x)
    ceiling = db_to_amp(ceiling_db) * 0.995  # margin for inter-sample error
    need = np.minimum(1.0, ceiling / np.maximum(true_peak_envelope(x2, oversample), 1e-12))
    la = max(2, int(sr * lookahead_ms / 1000))
    la += la % 2
    rel = max(1, int(sr * release_ms / 1000))
    held = window_min(need, before=rel, after=la)
    k = np.hanning(la + 1)
    k /= k.sum()
    gain = np.convolve(np.pad(held, (la // 2, la // 2), mode="edge"), k, mode="valid")
    y = x2 * gain[:, None]
    y = y if x.ndim == 2 else y[:, 0]
    return (y, gain) if return_gain else y


def feedback_comb(x: np.ndarray, delay: int, feedback: float,
                  damp: float = 0.0) -> np.ndarray:
    """y[n] = x[n] + feedback * lp(y[n - delay]), computed one delay-length block at a time.

    ``damp`` (0..1) is a one-pole lowpass inside the loop, as in Freeverb, applied
    per block so it costs one short ``lfilter`` per block.
    """
    y = np.array(x, dtype=np.float64, copy=True)
    zi = np.zeros((1,) + y.shape[1:])
    for i in range(delay, len(y), delay):
        prev = y[i - delay:i]
        if damp:
            prev, zi = signal.lfilter([1 - damp], [1, -damp], prev, axis=0, zi=zi)
        seg = y[i:i + delay]
        seg += feedback * prev[: len(seg)]
    return y


def allpass(x: np.ndarray, delay: int, g: float = 0.5) -> np.ndarray:
    """Schroeder allpass y[n] = -g x[n] + x[n-D] + g y[n-D], block-recursive."""
    y = -g * np.asarray(x, dtype=np.float64)
    for i in range(delay, len(y), delay):
        seg = y[i:i + delay]
        k = len(seg)
        seg += x[i - delay:i - delay + k] + g * y[i - delay:i - delay + k]
    return y


_COMBS = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
_ALLPASSES = [556, 441, 341, 225]


def reverb(x: np.ndarray, sr: int, room_size=0.5, damping=0.5, wet=0.33, dry=0.4,
           width=1.0) -> np.ndarray:
    """Freeverb-style Schroeder reverb: eight damped combs into four allpasses per side."""
    x2 = as_2d(x)
    mono = x2.mean(axis=1) * 0.015
    scale = sr / 44100
    fb = 0.7 + 0.28 * room_size
    outs = []
    for spread in (0, 23):
        acc = np.zeros_like(mono)
        for d in _COMBS:
            acc += feedback_comb(mono, int((d + spread) * scale), fb, 0.2 + 0.6 * damping)
        for d in _ALLPASSES:
            acc = allpass(acc, int((d + spread) * scale))
        outs.append(acc)
    wl, wr = outs
    w1, w2 = wet * (width / 2 + 0.5), wet * ((1 - width) / 2)
    left = wl * w1 + wr * w2
    right = wr * w1 + wl * w2
    if x2.shape[1] == 1:
        x2 = np.repeat(x2, 2, axis=1)
    return x2 * dry + np.stack([left, right], axis=1)


def delay(x: np.ndarray, sr: int, seconds: float, feedback=0.3, mix=0.25) -> np.ndarray:
    """Feedback echo: wet[n] = x[n - d] + feedback * wet[n - d]."""
    d = max(1, int(seconds * sr))
    x = np.asarray(x, dtype=np.float64)
    shifted = np.zeros_like(x)
    shifted[d:] = x[:-d]
    wet = feedback_comb(shifted, d, feedback)
    return x * (1 - mix) + wet * mix


def chorus(x: np.ndarray, sr: int, rate_hz=0.8, depth=0.25, mix=0.5) -> np.ndarray:
    x2 = as_2d(x)
    if x2.shape[1] == 1:
        x2 = np.repeat(x2, 2, axis=1)
    n = len(x2)
    t = np.arange(n) / sr
    base, span = 0.012 * sr, 0.006 * sr * depth
    out = np.empty_like(x2)
    for ch, ph in enumerate((0, np.pi / 2)):
        d = base + span * np.sin(2 * np.pi * rate_hz * t + ph)
        idx = np.arange(n) - d
        out[:, ch] = np.interp(idx, np.arange(n), x2[:, ch], left=0)
    return x2 * (1 - mix) + out * mix


def pan_stereo(x: np.ndarray, pan: float, width: float = 1.0) -> np.ndarray:
    """Equal-power pan for mono; balance plus mid/side width for stereo."""
    theta = (pan + 1) * np.pi / 4
    gl, gr = np.cos(theta), np.sin(theta)
    if x.ndim == 1 or x.shape[1] == 1:
        m = x.reshape(-1)
        return np.stack([m * gl, m * gr], axis=1)
    mid = (x[:, 0] + x[:, 1]) / 2
    side = (x[:, 0] - x[:, 1]) / 2 * width
    left, right = mid + side, mid - side
    norm = np.sqrt(2)  # balance law that leaves centre at unity
    return np.stack([left * gl * norm, right * gr * norm], axis=1)


# Mix tools: gate, transients, stereo image, convolution ---------------------

def gate(x: np.ndarray, sr: int, threshold_db=-50.0, ratio=10.0, attack_ms=1.0,
         release_ms=80.0, hold_ms=0.0, range_db=40.0) -> np.ndarray:
    """Downward expander: below the threshold, gain falls by ``ratio`` dB per dB.

    ``range_db`` caps the attenuation; ``hold_ms`` keeps the gate open after
    the level drops.
    """
    from scipy.ndimage import maximum_filter1d

    x2 = as_2d(x)
    # A 10 ms running peak first, so the threshold compares with signal peaks
    # rather than the average of one cycle.
    peak = maximum_filter1d(np.max(np.abs(x2), axis=1), size=max(1, int(0.01 * sr)))
    env = envelope_follower(peak, sr, attack_ms, release_ms)
    hold = int(sr * hold_ms / 1000)
    if hold > 1:
        env = maximum_filter1d(env, size=hold, origin=-(hold // 2))
    env_db = 20 * np.log10(np.maximum(env, 1e-9))
    under = np.maximum(threshold_db - env_db, 0)
    gain_db = -np.minimum(under * (ratio - 1), range_db)
    y = x2 * (10 ** (gain_db / 20))[:, None]
    return y if x.ndim == 2 else y[:, 0]


def transient_shaper(x: np.ndarray, sr: int, attack_db=0.0, sustain_db=0.0) -> np.ndarray:
    """Boost or cut onsets (``attack_db``) and tails (``sustain_db``).

    Compares a fast and a slow envelope: the fast one leads at onsets and
    falls below the slow one as a note decays. Gain moves fully once the two
    are 6 dB apart.
    """
    x2 = as_2d(x)
    level = np.max(np.abs(x2), axis=1)
    fast = envelope_follower(level, sr, 0.5, 20)
    slow = envelope_follower(level, sr, 25, 250)
    diff = 20 * np.log10(np.maximum(fast, 1e-9) / np.maximum(slow, 1e-9))
    gain_db = attack_db * np.clip(diff / 6, 0, 1) + sustain_db * np.clip(-diff / 6, 0, 1)
    # Smooth so gain changes do not click.
    k = max(1, int(0.002 * sr))
    gain_db = np.convolve(gain_db, np.ones(k) / k, mode="same")
    y = x2 * (10 ** (gain_db / 20))[:, None]
    return y if x.ndim == 2 else y[:, 0]


def crossover(x: np.ndarray, freq: float, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Linkwitz–Riley 4th-order split into (low, high); their sum is allpass."""
    q = 0.7071
    low = filt(filt(x, "lowpass", freq, sr, q), "lowpass", freq, sr, q)
    high = filt(filt(x, "highpass", freq, sr, q), "highpass", freq, sr, q)
    return low, high


def ms_encode(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2


def ms_decode(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
    return np.stack([mid + side, mid - side], axis=1)


def stereo_width(x: np.ndarray, sr: int, width=1.0, mono_below_hz=None) -> np.ndarray:
    """Scale side energy by ``width``; optionally sum everything below a crossover to mono."""
    x2 = as_2d(x)
    if x2.shape[1] < 2:
        return x2
    if mono_below_hz:
        low, high = crossover(x2[:, :2], mono_below_hz, sr)
        low_mid, _ = ms_encode(low)
        mid, side = ms_encode(high)
        return ms_decode(mid + low_mid, side * width)
    mid, side = ms_encode(x2[:, :2])
    return ms_decode(mid, side * width)


def convolve(x: np.ndarray, ir: np.ndarray, mix=0.3, predelay: int = 0) -> np.ndarray:
    """Convolution reverb. ``ir`` is (samples, channels) at the signal's rate.

    The IR is scaled to unit energy so ``mix`` behaves the same across IRs.
    Output keeps the input length; leave room with ``master.tail_seconds``.
    """
    x2, ir = as_2d(x), as_2d(ir)
    ir = ir / max(np.sqrt(np.sum(ir**2) / ir.shape[1]), 1e-12)
    ch = max(x2.shape[1], ir.shape[1])
    if x2.shape[1] < ch:
        x2 = np.repeat(x2, ch, axis=1)
    n = len(x2)
    wet = np.zeros_like(x2)
    for c in range(ch):
        w = signal.fftconvolve(x2[:, c], ir[:, min(c, ir.shape[1] - 1)])[:n]
        if predelay:
            w = np.concatenate([np.zeros(predelay), w])[:n]
        wet[:, c] = w
    return x2 * (1 - mix) + wet * mix


def gain_reduction(before: np.ndarray, after: np.ndarray, sr: int,
                   offset_db: float = 0.0, floor_db: float = -60.0) -> dict:
    """How much a dynamics stage turned the signal down, from 10 ms RMS blocks.

    Blocks quieter than ``floor_db`` at the input are ignored. ``offset_db``
    removes make-up gain so only reduction is counted.
    """
    b, a = as_2d(before), as_2d(after)
    n = min(len(b), len(a))
    blk = max(1, int(0.01 * sr))
    m = (n // blk) * blk
    if m == 0:
        return {"max_db": 0.0, "mean_db": 0.0, "percent_over_1db": 0.0}

    def rms_db(z):
        p = np.mean(z[:m].reshape(-1, blk, z.shape[1]) ** 2, axis=(1, 2))
        return 10 * np.log10(np.maximum(p, 1e-15))

    rb, ra = rms_db(b), rms_db(a)
    keep = rb > floor_db
    if not keep.any():
        return {"max_db": 0.0, "mean_db": 0.0, "percent_over_1db": 0.0}
    gr = np.maximum(rb[keep] - (ra[keep] - offset_db), 0)
    return {"max_db": round(float(gr.max()), 1), "mean_db": round(float(gr.mean()), 1),
            "percent_over_1db": round(float(np.mean(gr > 1) * 100), 1)}
