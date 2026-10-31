"""Numeric listening: loudness, peaks, spectrum, tempo, key and stereo image."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

from . import dsp
from .errors import StemmaError
from .paths import post_mix_dir, render_root, stems_dir
from .spec import Spec
from .theory import NAMES_SHARP

BANDS = {  # Hz, upper edge exclusive
    "sub": (20, 60),
    "low": (60, 250),
    "low_mid": (250, 2000),
    "high_mid": (2000, 6000),
    "air": (6000, 20000),
}

# Krumhansl–Kessler key profiles.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

CLIP_LEVEL = 0.999  # |sample| at or above this counts as clipped


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


OCTAVES_HZ = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def band_energy(mono: np.ndarray, sr: int) -> dict:
    """Share of spectral energy per band in dB relative to the total (0 dB = all)."""
    n_fft = 8192
    if len(mono) < n_fft:
        mono = np.pad(mono, (0, n_fft - len(mono)))
    from scipy.signal import welch

    f, pxx = welch(mono, sr, nperseg=n_fft)
    total = pxx[(f >= 20) & (f < 20000)].sum()
    out = {}
    for name, (lo, hi) in BANDS.items():
        e = pxx[(f >= lo) & (f < min(hi, sr / 2))].sum()
        out[name] = _r(10 * np.log10(e / total)) if total > 0 and e > 0 else -120.0
    centroid = float((f * pxx).sum() / pxx.sum()) if pxx.sum() > 0 else 0.0
    # Absolute octave-band power (dB, arbitrary reference) for comparing stems.
    octaves = {}
    for fc in OCTAVES_HZ:
        sel = (f >= fc / np.sqrt(2)) & (f < min(fc * np.sqrt(2), sr / 2))
        e = pxx[sel].sum() * (f[1] - f[0])
        label = str(int(fc)) if fc >= 63 else str(fc)
        octaves[label] = _r(10 * np.log10(e), 1) if e > 0 else -150.0
    return {"bands_db": out, "spectral_centroid_hz": _r(centroid, 0), "octave_bands_db": octaves}


def masking_pairs(stems: dict, near_peak_db: float = 4.0, level_gap_db: float = 6.0) -> list:
    """Pairs of stems that are both strong, and at similar levels, in the same octave.

    For each stem, an octave counts as "strong" when it is within ``near_peak_db``
    of that stem's loudest octave. Two stems conflict in an octave when both are
    strong there and their levels are within ``level_gap_db``.
    """
    names = [n for n, m in stems.items() if not m.get("silent") and "octave_bands_db" in m]
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            oa, ob = stems[a]["octave_bands_db"], stems[b]["octave_bands_db"]
            pa, pb = max(oa.values()), max(ob.values())
            for band in oa:
                la, lb = oa[band], ob[band]
                if (la >= pa - near_peak_db and lb >= pb - near_peak_db
                        and abs(la - lb) <= level_gap_db):
                    out.append({"stems": [a, b], "octave_hz": band,
                                "level_diff_db": _r(abs(la - lb), 1)})
    return out


def estimate_key(mono: np.ndarray, sr: int) -> dict:
    import librosa

    # Harmonic part only, so drums do not smear the pitch-class profile.
    harmonic = librosa.effects.harmonic(mono.astype(np.float32), margin=2.0)
    # Start at C2: kick drums and sub-bass add tonal energy that misleads key finding.
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr, hop_length=4096,
                                        fmin=librosa.note_to_hz("C2"), n_octaves=6)
    profile = chroma.sum(axis=1)
    if profile.sum() == 0:
        return {"key": None, "key_confidence": None}
    scores = []
    for mode, ref in (("major", MAJOR), ("minor", MINOR)):
        for tonic in range(12):
            r = np.corrcoef(profile, np.roll(ref, tonic))[0, 1]
            scores.append((r, f"{NAMES_SHARP[tonic]} {mode}"))
    scores.sort(reverse=True)
    return {"key": scores[0][1], "key_confidence": _r(scores[0][0], 3),
            "key_runner_up": scores[1][1]}


def estimate_tempo(mono: np.ndarray, sr: int) -> float | None:
    import librosa

    if len(mono) < sr * 4:
        return None
    onset = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr)
    tempo = librosa.feature.tempo(onset_envelope=onset, sr=sr)
    return _r(np.atleast_1d(tempo)[0], 1)


def _width(left: np.ndarray, right: np.ndarray) -> float:
    mid, side = (left + right) / 2, (left - right) / 2
    e_mid, e_side = np.sum(mid**2), np.sum(side**2)
    return float(e_side / (e_mid + e_side)) if e_mid + e_side > 0 else 0.0


def stereo_image(x: np.ndarray, sr: int) -> dict:
    """Side-energy share broadband and above 300 Hz.

    Kick and bass are (rightly) mono and dominate broadband energy, so the
    above-300 Hz figure is the better guide to how wide a mix feels.
    """
    if x.shape[1] < 2:
        return {"stereo_width": 0.0, "stereo_width_above_300hz": 0.0, "correlation": 1.0}
    left, right = x[:, 0], x[:, 1]
    hi = dsp.filt(dsp.filt(x[:, :2], "highpass", 300, sr), "highpass", 300, sr)
    denom = np.sqrt(np.sum(left**2) * np.sum(right**2))
    corr = np.sum(left * right) / denom if denom > 0 else 1.0
    return {"stereo_width": _r(_width(left, right), 3),
            "stereo_width_above_300hz": _r(_width(hi[:, 0], hi[:, 1]), 3),
            "correlation": _r(corr, 3)}


def analyse_audio(x: np.ndarray, sr: int, full: bool = True) -> dict:
    """Measure one signal. ``x`` is (samples,) or (samples, channels)."""
    import pyloudnorm as pyln

    x = dsp.as_2d(np.asarray(x, dtype=np.float64))
    mono = x.mean(axis=1)
    peak = float(np.abs(x).max()) if x.size else 0.0
    rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lufs = pyln.Meter(sr).integrated_loudness(x) if len(x) > 0.4 * sr else None
    tp = float(dsp.true_peak_envelope(x).max()) if x.size else 0.0
    silent = peak < 1e-6
    out = {
        "seconds": _r(len(x) / sr, 3),
        "channels": x.shape[1],
        "lufs_integrated": None if silent else _r(lufs),
        "true_peak_dbtp": _r(dsp.amp_to_db(tp)),
        "sample_peak_dbfs": _r(dsp.amp_to_db(peak)),
        "rms_dbfs": _r(dsp.amp_to_db(rms)),
        "crest_factor_db": None if silent else _r(dsp.amp_to_db(peak) - dsp.amp_to_db(rms)),
        "clipped_samples": int(np.sum(np.abs(x) >= CLIP_LEVEL)),
        **stereo_image(x, sr),
    }
    if silent:
        out["silent"] = True
        return out
    out.update(band_energy(mono, sr))
    if full:
        out["tempo_bpm"] = estimate_tempo(mono, sr)
        out.update(estimate_key(mono, sr))
    return out


def analyse_file(path: Path, full: bool = True) -> dict:
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return analyse_audio(x, sr, full)


def keys_compatible(estimated: str, spec_key: str) -> bool:
    """True when two keys share a tonic or are relatives (same pitch-class set)."""
    from .theory import MODES, parse_key

    def pcs(k):
        tonic, mode = parse_key(k)
        return tonic, frozenset((tonic + s) % 12 for s in MODES[mode])

    (t1, s1), (t2, s2) = pcs(estimated), pcs(spec_key)
    return t1 == t2 or s1 == s2


def check_targets(spec: Spec, name: str, m: dict, is_master: bool) -> list[str]:
    warn = []
    if m.get("silent"):
        return [f"{name}: silent"]
    if m["clipped_samples"]:
        warn.append(f"{name}: {m['clipped_samples']} clipped samples")
    if is_master:
        tgt = spec.master
        if m["lufs_integrated"] is not None and abs(m["lufs_integrated"] - tgt["lufs"]) > 1:
            warn.append(f"{name}: {m['lufs_integrated']} LUFS, target {tgt['lufs']}")
        if m["true_peak_dbtp"] > tgt["true_peak"] + 0.1:
            warn.append(f"{name}: true peak {m['true_peak_dbtp']} dBTP above "
                        f"{tgt['true_peak']}")
        if m.get("tempo_bpm") and spec.tempo:
            ratio = m["tempo_bpm"] / spec.tempo
            if min(abs(ratio - r) for r in (0.5, 1, 2)) > 0.04:
                warn.append(f"{name}: estimated tempo {m['tempo_bpm']} vs spec {spec.tempo}")
        if m.get("key") and not keys_compatible(m["key"], spec.key):
            warn.append(f"{name}: estimated key {m['key']} vs spec {spec.key}")
        if m["correlation"] is not None and m["correlation"] < 0:
            warn.append(f"{name}: negative L/R correlation, mono collapse risk")
        t = spec.targets
        for key in ("stereo_width", "stereo_width_above_300hz", "crest_factor_db"):
            if key in t and m.get(key) is not None and not t[key][0] <= m[key] <= t[key][1]:
                warn.append(f"{name}: {key} {m[key]} outside {t[key]}")
        for band, rng in t.get("bands", {}).items():
            v = m["bands_db"][band]
            if not rng[0] <= v <= rng[1]:
                warn.append(f"{name}: {band} band {v} dB outside {rng}")
    return warn


def analyse(spec: Spec, section: str | None = None, stem: str | None = None) -> dict:
    root = render_root(spec.dir, section)
    sdir = stems_dir(spec.dir, section)
    report: dict = {"track": spec.slug, "section": section,
                    "spec": {"tempo": spec.tempo, "key": spec.key}, "stems": {}}
    names = [stem] if stem else [p["name"] for p in spec.parts]
    warnings_: list[str] = []
    post = post_mix_dir(spec.dir, section)
    for name in names:
        wav = sdir / f"{name}.wav"
        if wav.is_file():
            # Prefer the post-fader version, unless the raw stem is newer than the mix.
            pm = post / f"{name}.wav"
            fresh = pm.is_file() and pm.stat().st_mtime >= wav.stat().st_mtime
            m = analyse_file(pm if fresh else wav, full=False)
            m["measured"] = "post-mix" if fresh else "raw stem (run mix for post-fader figures)"
            report["stems"][name] = m
            warnings_ += check_targets(spec, name, m, False)
        elif stem:
            raise StemmaError(f"{wav} missing; render it first")
    for label in ("mix", "master"):
        if stem:
            break
        wav = root / f"{label}.wav"
        if wav.is_file():
            m = analyse_file(wav)
            report[label] = m
            warnings_ += check_targets(spec, label, m, label == "master")
    report["masking"] = masking_pairs(report["stems"])
    for mk in report["masking"]:
        warnings_.append(f"possible masking: {mk['stems'][0]} and {mk['stems'][1]} are both "
                         f"strong in the {mk['octave_hz']} Hz octave "
                         f"({mk['level_diff_db']} dB apart)")
    report["warnings"] = warnings_
    if not stem:
        root.mkdir(parents=True, exist_ok=True)
        (root / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
