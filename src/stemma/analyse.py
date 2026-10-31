"""Numeric listening: loudness, peaks, spectrum, tempo, key and stereo image."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

from . import dsp
from .errors import StemmaError
from .loudness import loudness_stats
from .paths import post_mix_dir, render_root, stems_dir
from .spec import Spec, is_audio_part
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
LOW_END_HZ = 150  # low_end_correlation is measured below this
LOW_END_MIN_CORR = 0.8  # warn on mix and master below this


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
        return {"stereo_width": 0.0, "stereo_width_above_300hz": 0.0, "correlation": 1.0,
                "low_end_correlation": 1.0}
    left, right = x[:, 0], x[:, 1]
    hi = dsp.filt(dsp.filt(x[:, :2], "highpass", 300, sr), "highpass", 300, sr)
    lo = dsp.filt(dsp.filt(x[:, :2], "lowpass", LOW_END_HZ, sr), "lowpass", LOW_END_HZ, sr)
    return {"stereo_width": _r(_width(left, right), 3),
            "stereo_width_above_300hz": _r(_width(hi[:, 0], hi[:, 1]), 3),
            "correlation": _r(_corr(left, right), 3),
            "low_end_correlation": _r(_corr(lo[:, 0], lo[:, 1]), 3)}


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    denom = np.sqrt(np.sum(left**2) * np.sum(right**2))
    return float(np.sum(left * right) / denom) if denom > 1e-12 else 1.0


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
    out.update(loudness_stats(x, sr))
    out["plr_db"] = (None if out["lufs_integrated"] is None
                     else _r(out["true_peak_dbtp"] - out["lufs_integrated"]))
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
    if name in ("mix", "master") and (m.get("low_end_correlation") or 1) < LOW_END_MIN_CORR:
        warn.append(f"{name}: low-end correlation {m['low_end_correlation']} below "
                    f"{LOW_END_MIN_CORR} (stereo under {LOW_END_HZ} Hz); centre the bass "
                    "and kick, or add stereo_width with mono_below_hz")
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
        key = m.get("key_tonal") or m.get("key")
        if key and not keys_compatible(key, spec.key):
            warn.append(f"{name}: estimated key {key} vs spec {spec.key}")
        if m["correlation"] is not None and m["correlation"] < 0:
            warn.append(f"{name}: negative L/R correlation, mono collapse risk")
        t = spec.targets
        for key in ("stereo_width", "stereo_width_above_300hz", "crest_factor_db",
                    "loudness_range_lu", "plr_db"):
            if key in t and m.get(key) is not None and not t[key][0] <= m[key] <= t[key][1]:
                warn.append(f"{name}: {key} {m[key]} outside {t[key]}")
        for band, rng in t.get("bands", {}).items():
            v = m["bands_db"][band]
            if not rng[0] <= v <= rng[1]:
                warn.append(f"{name}: {band} band {v} dB outside {rng}")
    return warn


def tonal_key(spec: Spec, post: Path) -> dict | None:
    """Key of the pitched parts only (post-fader, drums excluded).

    Pitched kicks, snares and hats skew the chroma of a full mix, so this is
    the more reliable estimate when drum parts are present.
    """
    total = None
    for part in spec.parts:
        wav = post / f"{part['name']}.wav"
        if part.get("role") in ("drums", "percussion") or not wav.is_file():
            continue
        x, sr = sf.read(str(wav), dtype="float64", always_2d=True)
        total = x if total is None else total[: len(x)] + x[: len(total)]
    if total is None or np.abs(total).max() < 1e-6:
        return None
    k = estimate_key(total.mean(axis=1), sr)
    return {"key_tonal": k["key"], "key_tonal_confidence": k["key_confidence"]}


def tempo_matches(estimated: float, spec_tempo: float, tolerance: float = 0.04) -> bool:
    """True when an estimate is within ``tolerance`` of the tempo, half or double it."""
    ratio = estimated / spec_tempo
    return min(abs(ratio - r) for r in (0.5, 1, 2)) <= tolerance


def _generated_tempo(spec: Spec, name: str, wav: Path, m: dict) -> list[str]:
    """Generated audio does not follow the grid by construction, so check its tempo."""
    x, sr = sf.read(str(wav), dtype="float64", always_2d=True)
    m["tempo_bpm"] = estimate_tempo(x.mean(axis=1), sr)
    if m["tempo_bpm"] and not tempo_matches(m["tempo_bpm"], spec.tempo):
        return [f"{name}: generated audio runs at about {m['tempo_bpm']} bpm, not "
                f"{spec.tempo:g}; it will drift against the other parts "
                "(regenerate, or reword sound.prompt)"]
    return []


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
            if is_audio_part(spec.part(name)) and not m.get("silent"):
                warnings_ += _generated_tempo(spec, name, wav, m)
            report["stems"][name] = m
            warnings_ += check_targets(spec, name, m, False)
        elif stem:
            raise StemmaError(f"{wav} missing; render it first")
    tonal = None if stem else tonal_key(spec, post)
    for label in ("mix", "master"):
        if stem:
            break
        wav = root / f"{label}.wav"
        if wav.is_file():
            x, sr = sf.read(str(wav), dtype="float64", always_2d=True)
            m = analyse_audio(x, sr)
            if tonal:
                m.update(tonal)
            if label == "master":
                mj = root / "master.json"
                if mj.is_file():
                    mreport = json.loads(mj.read_text())
                    if "limiter" in mreport:
                        m["limiter"] = mreport["limiter"]
                    warnings_ += mreport.get("warnings", [])
            report[label] = m
            warnings_ += check_targets(spec, label, m, label == "master")
            if not section:
                report["sections"] = section_figures(spec, x, sr)
    report["masking"] = masking_pairs(report["stems"])
    for mk in report["masking"]:
        warnings_.append(f"possible masking: {mk['stems'][0]} and {mk['stems'][1]} are both "
                         f"strong in the {mk['octave_hz']} Hz octave "
                         f"({mk['level_diff_db']} dB apart)")
    report["warnings"] = warnings_
    if not stem:
        root.mkdir(parents=True, exist_ok=True)
        report["delta"] = _rotate_and_diff(root, report)
        (root / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


SECTION_FIELDS = ("lufs_integrated", "short_term_lufs_max", "crest_factor_db",
                  "spectral_centroid_hz", "stereo_width_above_300hz")


def section_figures(spec: Spec, x: np.ndarray, sr: int) -> dict:
    """A few figures per section of a full render, to check how energy builds."""
    out = {}
    for sec in spec.sections:
        s0, s1 = spec.section_span(sec.name)
        m = analyse_audio(x[int(s0 * sr):int(s1 * sr)], sr, full=False)
        out[sec.name] = {k: m.get(k) for k in SECTION_FIELDS}
    return out


# What `delta` compares: top-level numbers, plus these nested dicts.
DELTA_NESTED = ("bands_db", "limiter")
DELTA_STEM_FIELDS = ("lufs_integrated", "crest_factor_db", "spectral_centroid_hz",
                     "stereo_width_above_300hz", "bands_db")
DELTA_MIN = 0.1


def _numbers(m: dict, fields=None) -> dict:
    out = {}
    for k, v in m.items():
        if fields and k not in fields:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, dict) and k in DELTA_NESTED:
            out.update({f"{k}.{kk}": vv for kk, vv in v.items()
                        if isinstance(vv, (int, float)) and not isinstance(vv, bool)})
    return out


def _measurements(report: dict) -> dict:
    """Flat {path: number} of the figures worth comparing between revisions."""
    flat = {}
    for label in ("mix", "master"):
        for k, v in _numbers(report.get(label, {})).items():
            flat[f"{label}.{k}"] = v
    for sec, m in report.get("sections", {}).items():
        for k, v in _numbers(m).items():
            flat[f"sections.{sec}.{k}"] = v
    for name, m in report.get("stems", {}).items():
        for k, v in _numbers(m, DELTA_STEM_FIELDS).items():
            flat[f"stems.{name}.{k}"] = v
    return flat


def diff_reports(old: dict, new: dict) -> dict:
    """Changes between two analysis reports: figures that moved and warnings."""
    a, b = _measurements(old), _measurements(new)
    changed = {}
    for k in sorted(set(a) & set(b)):
        d = b[k] - a[k]
        if abs(d) >= DELTA_MIN:
            changed[k] = {"old": a[k], "new": b[k], "diff": round(d, 3)}
    ow, nw = set(old.get("warnings", [])), set(new.get("warnings", []))
    return {"changed": changed,
            "warnings_added": sorted(nw - ow), "warnings_removed": sorted(ow - nw)}


def _rotate_and_diff(root: Path, report: dict) -> dict | None:
    """Compare with the last analysis whose figures differed from this one.

    ``analysis.json`` moves to ``analysis.prev.json`` only when the figures
    changed, so re-running analyse without a change keeps showing what the
    last change did.
    """
    cur, prev = root / "analysis.json", root / "analysis.prev.json"
    old = json.loads(cur.read_text()) if cur.is_file() else None
    if old is not None and _measurements(old) != _measurements(report):
        prev.write_text(json.dumps({k: v for k, v in old.items() if k != "delta"},
                                   indent=2) + "\n")
        base = old
    elif prev.is_file():
        base = json.loads(prev.read_text())
    else:
        return None
    return diff_reports(base, report)
