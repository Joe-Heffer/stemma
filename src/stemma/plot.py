"""PNG plots an agent can look at: stem spectra, a spectrogram and loudness over time."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .errors import StemmaError
from .loudness import block_loudness
from .paths import post_mix_dir, render_root, stems_dir
from .spec import Spec

KINDS = ("spectrum", "spectrogram", "loudness")


def _pyplot():
    try:
        import matplotlib
    except ImportError as e:
        raise StemmaError("plots need matplotlib; run `uv sync --extra plot`") from e
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _read(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return x, sr


def third_octave_spectrum(mono: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """(centre Hz, dB) of power in 1/3-octave bands from 25 Hz to 16 kHz."""
    from scipy.signal import welch

    f, pxx = welch(mono, sr, nperseg=min(8192, len(mono)))
    centres = 1000 * 2 ** (np.arange(-16, 13) / 3)
    out = []
    for fc in centres:
        sel = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        e = pxx[sel].sum() * (f[1] - f[0])
        out.append(10 * np.log10(e) if e > 0 else -150.0)
    return centres, np.array(out)


def _section_lines(ax, spec: Spec, section: str | None):
    if section:
        return
    for sec in spec.sections:
        t = spec.section_span(sec.name)[0]
        ax.axvline(t, color="0.5", lw=0.8, ls=":")
        ax.text(t, 1.0, f" {sec.name}", transform=ax.get_xaxis_transform(), va="top",
                fontsize=8, color="0.3")


def plot_spectrum(spec: Spec, section, stems, out: Path) -> Path:
    plt = _pyplot()
    post, raw = post_mix_dir(spec.dir, section), stems_dir(spec.dir, section)
    names = stems or [p["name"] for p in spec.parts]
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=110)
    drawn = 0
    for name in names:
        wav = post / f"{name}.wav"
        wav = wav if wav.is_file() else raw / f"{name}.wav"
        if not wav.is_file():
            continue
        x, sr = _read(wav)
        if np.abs(x).max() < 1e-6:
            continue
        fc, db = third_octave_spectrum(x.mean(axis=1), sr)
        ax.semilogx(fc, db, label=name, lw=1.6)
        drawn += 1
    master = render_root(spec.dir, section) / "mix.wav"
    if master.is_file() and not stems:
        x, sr = _read(master)
        fc, db = third_octave_spectrum(x.mean(axis=1), sr)
        ax.semilogx(fc, db, label="mix", color="k", lw=1.2, ls="--")
    if not drawn:
        plt.close(fig)
        raise StemmaError("no stems to plot; run render and mix first")
    for edge in (60, 250, 2000, 6000):  # analyse's band edges
        ax.axvline(edge, color="0.85", lw=0.8)
    ax.set(xlabel="Hz (1/3-octave bands)", ylabel="dB (relative)", xlim=(20, 20000),
           title=f"{spec.title}: stem spectra, post-fader" + (f" ({section})" if section else ""))
    top = ax.get_ylim()[1]
    ax.set_ylim(top - 70, top + 3)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def _master_or_mix(spec: Spec, section) -> Path:
    root = render_root(spec.dir, section)
    for name in ("master.wav", "mix.wav"):
        if (root / name).is_file():
            return root / name
    raise StemmaError(f"no master.wav or mix.wav in {root}; run mix and master first")


def plot_spectrogram(spec: Spec, section, out: Path) -> Path:
    from scipy.signal import spectrogram

    plt = _pyplot()
    src = _master_or_mix(spec, section)
    x, sr = _read(src)
    f, t, sxx = spectrogram(x.mean(axis=1), sr, nperseg=4096, noverlap=3072)
    db = 10 * np.log10(np.maximum(sxx, 1e-14))
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=110)
    sel = f >= 20
    mesh = ax.pcolormesh(t, f[sel], db[sel], shading="auto", cmap="magma",
                         vmin=db.max() - 90, vmax=db.max())
    ax.set_yscale("log")
    ax.set(ylim=(20, sr / 2), xlabel="seconds", ylabel="Hz",
           title=f"{spec.title}: {src.stem} spectrogram" + (f" ({section})" if section else ""))
    _section_lines(ax, spec, section)
    fig.colorbar(mesh, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_loudness(spec: Spec, section, out: Path) -> Path:
    plt = _pyplot()
    src = _master_or_mix(spec, section)
    x, sr = _read(src)
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
    for window, label, lw in ((0.4, "momentary (0.4 s)", 0.8), (3.0, "short-term (3 s)", 1.8)):
        t, lufs = block_loudness(x, sr, window)
        if len(t):
            ax.plot(t + window / 2, lufs, label=label, lw=lw)
    if src.stem == "master":
        ax.axhline(spec.master["lufs"], color="k", ls="--", lw=1,
                   label=f"target {spec.master['lufs']} LUFS (integrated)")
    _section_lines(ax, spec, section)
    lo = spec.master["lufs"] - 25
    ax.set(xlabel="seconds", ylabel="LUFS", ylim=(lo, max(ax.get_ylim()[1], lo + 30)),
           title=f"{spec.title}: {src.stem} loudness" + (f" ({section})" if section else ""))
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot(spec: Spec, section: str | None = None, kinds=None, stems=None) -> dict:
    out_dir = render_root(spec.dir, section) / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for kind in kinds or KINDS:
        out = out_dir / f"{kind}.png"
        if kind == "spectrum":
            plot_spectrum(spec, section, stems, out)
        elif kind == "spectrogram":
            plot_spectrogram(spec, section, out)
        elif kind == "loudness":
            plot_loudness(spec, section, out)
        else:
            raise StemmaError(f"unknown plot {kind!r}; choose from {KINDS}")
        files[kind] = str(out.relative_to(spec.dir))
    return {"track": spec.slug, "section": section, "plots": files}
