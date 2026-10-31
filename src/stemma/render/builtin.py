"""Built-in numpy synthesiser and drum kit.

No external tools are needed, so any track using ``source: builtin`` renders
from a clean clone. Every random choice is seeded from the part and note, so
renders are bit-for-bit reproducible.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .. import dsp
from ..errors import StemmaError
from ..midi import NoteEvent

SYNTH_DEFAULTS = {
    "wave": "saw",          # sine, triangle, saw, square, pulse
    "pulse_width": 0.5,
    "voices": 1,            # unison voices
    "detune_cents": 0.0,    # spread between unison voices
    "spread": 0.0,          # stereo spread of unison voices, 0..1 (0 gives a mono stem)
    "sub": 0.0,             # level of a sine one octave down
    "noise": 0.0,           # level of white noise in the oscillator mix
    "attack": 0.005, "decay": 0.2, "sustain": 0.7, "release": 0.15,
    "cutoff": 3000.0,       # lowpass cutoff in Hz; 0 disables the filter
    "resonance": 0.8,       # filter Q
    "filter_env": 0.0,      # filter envelope depth in octaves
    "filter_decay": 0.2,    # filter envelope decay in seconds
    "keytrack": 0.5,        # cutoff follows pitch: 1 = fully
    "velocity_cutoff": 1.0, # octaves of cutoff change across the velocity range
    "vibrato_rate": 5.0, "vibrato_cents": 0.0, "vibrato_delay": 0.2,
    "drive": 0.0,           # tanh saturation amount, 0..10
    "level": 0.3,
}

PRESETS: dict[str, dict] = {
    "sine": {"wave": "sine", "cutoff": 0, "attack": 0.01, "sustain": 1.0, "release": 0.1},
    "saw-bass": {"wave": "saw", "sub": 0.6, "attack": 0.003, "decay": 0.3, "sustain": 0.55,
                 "release": 0.07, "cutoff": 260, "resonance": 1.1, "filter_env": 2.6,
                 "filter_decay": 0.14, "keytrack": 0.3, "drive": 1.5, "level": 0.35},
    "pulse-lead": {"wave": "pulse", "pulse_width": 0.32, "voices": 2, "detune_cents": 9,
                   "spread": 0.4, "attack": 0.012, "decay": 0.35, "sustain": 0.65,
                   "release": 0.22, "cutoff": 1800, "resonance": 0.9, "filter_env": 1.4,
                   "filter_decay": 0.25, "vibrato_cents": 14, "vibrato_rate": 5.4,
                   "vibrato_delay": 0.25, "level": 0.18},
    "soft-pad": {"wave": "saw", "voices": 5, "detune_cents": 16, "spread": 0.9,
                 "attack": 0.6, "decay": 1.0, "sustain": 0.8, "release": 1.2,
                 "cutoff": 1100, "resonance": 0.6, "filter_env": 0.6, "filter_decay": 1.2,
                 "level": 0.1},
    "pluck": {"wave": "saw", "voices": 2, "detune_cents": 6, "spread": 0.5,
              "attack": 0.002, "decay": 0.35, "sustain": 0.0, "release": 0.2,
              "cutoff": 500, "resonance": 1.0, "filter_env": 3.5, "filter_decay": 0.12,
              "level": 0.22},
    # Drum kit. Tune kick_hz to the key (55 = A1) so the kick does not clash with the bass.
    "kit": {"drums": True, "level": 0.5, "kick_hz": 50.0, "kick_decay": 0.22,
            "snare_hz": 185.0, "tom_tune": 1.0},
}


def preset_params(sound: dict) -> dict:
    name = sound.get("preset", "sine")
    if name not in PRESETS:
        raise StemmaError(f"unknown builtin preset {name!r}; choose from {sorted(PRESETS)}")
    return {**SYNTH_DEFAULTS, **PRESETS[name], **sound.get("params", {})}


def midi_to_hz(p: float) -> float:
    return 440.0 * 2 ** ((p - 69) / 12)


def _velocity_amp(v: int) -> float:
    return (v / 127) ** 1.6


# Synth voices -------------------------------------------------------------

def synth_note(n: NoteEvent, p: dict, sr: int, rng: np.random.Generator) -> np.ndarray:
    gate = max(1, int((n.end - n.start) * sr))
    total = gate + int(p["release"] * sr)
    t = np.arange(total) / sr
    f0 = midi_to_hz(n.pitch)
    vib = 0.0
    if p["vibrato_cents"]:
        ramp = np.clip((t - p["vibrato_delay"]) / 0.3, 0, 1)
        vib = ramp * p["vibrato_cents"] * np.sin(2 * np.pi * p["vibrato_rate"] * t)
    voices = int(p["voices"])
    chans = 2 if p["spread"] > 0 else 1
    out = np.zeros((total, chans))
    for v in range(voices):
        off = 0.0 if voices == 1 else (v / (voices - 1) - 0.5) * p["detune_cents"]
        freq = f0 * 2 ** ((off + vib) / 1200) * np.ones(total)
        osc = dsp.oscillator(p["wave"], freq, sr, rng.random(), p["pulse_width"])
        if chans == 2:
            pos = 0.0 if voices == 1 else (v / (voices - 1) * 2 - 1) * p["spread"]
            out += dsp.pan_stereo(osc, pos) * np.sqrt(2)
        else:
            out[:, 0] += osc
    out /= np.sqrt(voices)
    if p["sub"]:
        out += (p["sub"] * np.sin(2 * np.pi * f0 / 2 * t + rng.random() * 6.283))[:, None]
    if p["noise"]:
        out += p["noise"] * rng.standard_normal((total, 1))
    if p["cutoff"]:
        fenv = np.exp(-t / max(p["filter_decay"], 1e-3))
        octaves = (p["filter_env"] * fenv + p["keytrack"] * (n.pitch - 60) / 12
                   + p["velocity_cutoff"] * (n.velocity / 127 - 0.5))
        cutoff = np.clip(p["cutoff"] * 2 ** octaves, 20, 0.45 * sr)
        for c in range(chans):
            out[:, c] = dsp.varying_lowpass(out[:, c], cutoff, sr, p["resonance"])
    if p["drive"]:
        k = 1 + p["drive"]
        out = np.tanh(out * k) / np.tanh(k)
    env = dsp.adsr(gate, total, sr, p["attack"], p["decay"], p["sustain"], p["release"])
    return out * (env * _velocity_amp(n.velocity) * p["level"])[:, None]


# Drum kit -----------------------------------------------------------------

def _exp(t, tau):
    return np.exp(-t / tau)


def _noise(rng, n):
    return rng.uniform(-1, 1, n)


def _metal(t, rng):
    """Six inharmonic square waves, the classic analogue hi-hat source."""
    freqs = [205.3, 304.4, 369.6, 522.7, 540.0, 800.0]
    return sum(signal.square(2 * np.pi * f * 1.6 * t + rng.random() * 6.283) for f in freqs) / 6


def kick(sr, rng, hz=50.0, decay=0.22, length=0.45):
    t = np.arange(int(length * sr)) / sr
    f = hz + 110 * _exp(t, 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / sr) * _exp(t, decay)
    click = dsp.filt(_noise(rng, len(t)), "highpass", 2500, sr) * _exp(t, 0.004) * 0.4
    return np.tanh(1.8 * (body + click)) * 0.9


def snare(sr, rng, hz=185.0, length=0.35):
    t = np.arange(int(length * sr)) / sr
    tone = (np.sin(2 * np.pi * hz * t) + 0.5 * np.sin(2 * np.pi * hz * 1.78 * t)) * _exp(t, 0.045)
    noise = dsp.filt(_noise(rng, len(t)), "bandpass", 3500, sr, q=0.6) * _exp(t, 0.11)
    return 0.45 * tone + 1.1 * noise


def clap(sr, rng, length=0.4):
    t = np.arange(int(length * sr)) / sr
    env = np.zeros_like(t)
    for d in (0, 0.011, 0.022):
        env += (t >= d) * _exp(np.maximum(t - d, 0), 0.008)
    env += (t >= 0.03) * 0.6 * _exp(np.maximum(t - 0.03, 0), 0.09)
    return dsp.filt(_noise(rng, len(t)), "bandpass", 1400, sr, q=1.2) * env * 1.6


def hat(sr, rng, open_=False):
    length, tau = (0.6, 0.18) if open_ else (0.12, 0.022)
    t = np.arange(int(length * sr)) / sr
    src = 0.7 * _metal(t, rng) + 0.5 * _noise(rng, len(t))
    src = dsp.filt(dsp.filt(src, "highpass", 7000, sr), "highpass", 7000, sr)
    return src * _exp(t, tau) * 0.6


def cymbal(sr, rng, ride=False):
    length, tau = (1.6, 0.5) if ride else (2.2, 0.7)
    t = np.arange(int(length * sr)) / sr
    src = 0.5 * _metal(t * (1.3 if ride else 1.0), rng) + 0.6 * _noise(rng, len(t))
    src = dsp.filt(src, "highpass", 4500 if ride else 3000, sr)
    return src * _exp(t, tau) * (0.25 if ride else 0.35)


def tom(sr, rng, pitch_hz, length=0.5):
    t = np.arange(int(length * sr)) / sr
    f = pitch_hz * (1 + 0.6 * _exp(t, 0.05))
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * _exp(t, 0.18) * 0.8


def rim(sr, rng):
    t = np.arange(int(0.06 * sr)) / sr
    src = np.sin(2 * np.pi * 1700 * t) + 0.5 * _noise(rng, len(t))
    return dsp.filt(src, "bandpass", 1700, sr, q=2) * _exp(t, 0.008)


TOMS = {41: 80, 43: 100, 45: 120, 47: 145, 48: 170, 50: 200}
CLOSED_HATS = {42, 44}
OPEN_HATS = {46}


def drum_hit(pitch: int, sr: int, rng, p: dict) -> np.ndarray | None:
    """General MIDI percussion map (channel 10 note numbers)."""
    if pitch in (35, 36):
        return kick(sr, rng, p.get("kick_hz", 50.0), p.get("kick_decay", 0.22))
    if pitch in (38, 40):
        return snare(sr, rng, p.get("snare_hz", 185.0))
    if pitch == 39:
        return clap(sr, rng)
    if pitch == 37:
        return rim(sr, rng)
    if pitch in CLOSED_HATS:
        return hat(sr, rng)
    if pitch in OPEN_HATS:
        return hat(sr, rng, open_=True)
    if pitch in (49, 52, 55, 57):
        return cymbal(sr, rng)
    if pitch in (51, 53, 59):
        return cymbal(sr, rng, ride=True)
    if pitch in TOMS:
        return tom(sr, rng, TOMS[pitch] * p.get("tom_tune", 1.0))
    return None


# Rendering ----------------------------------------------------------------

def render(notes: list[NoteEvent], sound: dict, sr: int, length: float, seed: int) -> np.ndarray:
    p = preset_params(sound)
    n_total = int(length * sr)
    is_kit = bool(p.get("drums"))
    chans = 1 if is_kit or p["spread"] <= 0 else 2
    out = np.zeros((n_total, chans))
    unknown = set()
    closed_times = sorted(n.start for n in notes if n.pitch in CLOSED_HATS)
    for i, n in enumerate(notes):
        rng = np.random.default_rng([seed, i, n.pitch])
        start = int(n.start * sr)
        if start >= n_total:
            continue
        if is_kit:
            hit = drum_hit(n.pitch, sr, rng, p)
            if hit is None:
                unknown.add(n.pitch)
                continue
            if n.pitch in OPEN_HATS:  # a closed hat chokes a ringing open hat
                nxt = next((c for c in closed_times if c > n.start), None)
                if nxt is not None:
                    cut = int((nxt - n.start) * sr)
                    if cut < len(hit):
                        fade = min(len(hit) - cut, int(0.004 * sr))
                        hit[cut:cut + fade] *= np.linspace(1, 0, fade)
                        hit[cut + fade:] = 0
            buf = (hit * _velocity_amp(n.velocity) * p["level"])[:, None]
        else:
            buf = synth_note(n, p, sr, rng)
        end = min(n_total, start + len(buf))
        out[start:end] += buf[: end - start]
    if unknown:
        import sys

        print(f"  warning: no builtin drum sound for notes {sorted(unknown)}", file=sys.stderr)
    return out
