"""Renderers that call external, separately installed tools.

Each tool is run as a subprocess and never linked, which keeps copyleft
licences (FluidSynth and Csound are LGPL, the Faust compiler is GPL) out of
stemma itself.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pretty_midi
import soundfile as sf

from .. import sounds
from ..errors import BackendUnavailable, StemmaError
from ..midi import END_MARKER_CC, NoteEvent
from ..spec import Spec
from .builtin import midi_to_hz

TOOLS = {
    "fluidsynth": "fluidsynth",
    "sfizz": "sfizz_render",
    "csound": "csound",
    "faust": "faust",
}


def require(tool: str) -> str:
    exe = shutil.which(tool)
    if not exe:
        raise BackendUnavailable(f"`{tool}` is not installed or not on PATH")
    return exe


def run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-15:]
        raise StemmaError(f"{what} failed ({proc.returncode}):\n  " + "\n  ".join(tail))


def write_midi(notes: list[NoteEvent], spec: Spec, part: dict, length: float, path: Path):
    """Write a render-ready MIDI file for the given (possibly trimmed) notes."""
    sound = part.get("sound", {})
    pm = pretty_midi.PrettyMIDI(initial_tempo=spec.tempo, resolution=960)
    is_drum = bool(sound.get("drums", part.get("role") in ("drums", "percussion")))
    inst = pretty_midi.Instrument(sound.get("program", 0), is_drum=is_drum, name=part["name"])
    if sound.get("bank") is not None:
        inst.control_changes += [pretty_midi.ControlChange(0, sound["bank"] >> 7, 0.0),
                                 pretty_midi.ControlChange(32, sound["bank"] & 127, 0.0)]
    inst.notes = [pretty_midi.Note(n.velocity, n.pitch, n.start, n.end) for n in notes]
    inst.control_changes.append(pretty_midi.ControlChange(END_MARKER_CC, 0, length))
    pm.instruments.append(inst)
    pm.write(str(path))


def read_wav(path: Path, sr: int, length: float) -> np.ndarray:
    audio, file_sr = sf.read(str(path), dtype="float64", always_2d=True)
    if file_sr != sr:
        from scipy.signal import resample_poly

        g = np.gcd(sr, file_sr)
        audio = resample_poly(audio, sr // g, file_sr // g, axis=0)
    n = int(length * sr)
    if len(audio) < n:
        audio = np.pad(audio, ((0, n - len(audio)), (0, 0)))
    return audio[:n]


# FluidSynth (SF2/SF3) -----------------------------------------------------

def fluidsynth_cmd(exe: str, soundfont: Path, midi: Path, out: Path, sr: int,
                   gain: float = 0.6) -> list[str]:
    return [
        exe, "-ni", "-q", "-g", str(gain), "-r", str(sr),
        "-o", "synth.reverb.active=0", "-o", "synth.chorus.active=0",
        "-o", "audio.file.type=wav", "-o", "audio.file.format=float",
        "-F", str(out), str(soundfont), str(midi),
    ]


def render_fluidsynth(notes, spec: Spec, part: dict, length: float, tmp: Path) -> np.ndarray:
    exe = require("fluidsynth")
    sound = part.get("sound", {})
    sf2 = sounds.resolve(sound.get("soundfont", "FluidR3_GM"), spec.dir)
    midi, out = tmp / "in.mid", tmp / "out.wav"
    write_midi(notes, spec, part, length, midi)
    gain = 0.6 * 10 ** (sound.get("gain_db", 0) / 20)
    run(fluidsynth_cmd(exe, sf2, midi, out, spec.sample_rate, gain), "fluidsynth")
    return read_wav(out, spec.sample_rate, length)


# sfizz (SFZ) --------------------------------------------------------------

def sfizz_cmd(exe: str, sfz: Path, midi: Path, out: Path, sr: int) -> list[str]:
    return [exe, "--sfz", str(sfz), "--midi", str(midi), "--wav", str(out),
            "--samplerate", str(sr)]


def render_sfizz(notes, spec: Spec, part: dict, length: float, tmp: Path) -> np.ndarray:
    exe = require("sfizz_render")
    sfz = spec.resolve(part["sound"]["path"])
    if not sfz.is_file():
        raise BackendUnavailable(f"SFZ {sfz} not found")
    midi, out = tmp / "in.mid", tmp / "out.wav"
    write_midi(notes, spec, part, length, midi)
    run(sfizz_cmd(exe, sfz, midi, out, spec.sample_rate), "sfizz_render")
    audio = read_wav(out, spec.sample_rate, length)
    return audio * 10 ** (part["sound"].get("gain_db", 0) / 20)


# Csound -------------------------------------------------------------------

def csound_score(notes: list[NoteEvent], instrument, length: float) -> str:
    """One i-statement per note: p4 Hz, p5 amplitude 0..1, p6 MIDI note, p7 velocity."""
    ins = f'"{instrument}"' if isinstance(instrument, str) else str(instrument)
    lines = [
        f"i {ins} {n.start:.6f} {n.end - n.start:.6f} {midi_to_hz(n.pitch):.4f} "
        f"{n.velocity / 127:.4f} {n.pitch} {n.velocity}"
        for n in notes
    ]
    return "\n".join(lines + [f"e {length:.6f}"])


def csound_document(orc: str, score: str, sr: int) -> str:
    return (
        "<CsoundSynthesizer>\n<CsInstruments>\n"
        f"sr = {sr}\nksmps = 16\nnchnls = 2\n0dbfs = 1\n\n{orc}\n"
        "</CsInstruments>\n<CsScore>\n" + score + "\n</CsScore>\n</CsoundSynthesizer>\n"
    )


def render_csound(notes, spec: Spec, part: dict, length: float, tmp: Path) -> np.ndarray:
    exe = require("csound")
    sound = part["sound"]
    orc_path = spec.resolve(sound["path"])
    if not orc_path.is_file():
        raise BackendUnavailable(f"Csound orchestra {orc_path} not found")
    csd = tmp / "render.csd"
    score = csound_score(notes, sound.get("instrument", 1), length)
    csd.write_text(csound_document(orc_path.read_text(), score, spec.sample_rate))
    out = tmp / "out.wav"
    run([exe, "-d", "-m0", "--nodisplays", "-W", "-f", "-o", str(out), str(csd)], "csound")
    audio = read_wav(out, spec.sample_rate, length)
    return audio * 10 ** (sound.get("gain_db", 0) / 20)


# Faust --------------------------------------------------------------------

ARCH = Path(__file__).with_name("faust_arch.cpp")


def faust_binary(dsp_path: Path, build_dir: Path) -> Path:
    """Compile a Faust synth with stemma's offline note-player architecture."""
    faust = require("faust")
    cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        raise BackendUnavailable("a C++ compiler (c++, g++ or clang++) is needed for Faust")
    key = hashlib.sha256(dsp_path.read_bytes() + ARCH.read_bytes()).hexdigest()[:16]
    binary = build_dir / f"{dsp_path.stem}-{key}"
    if binary.is_file():
        return binary
    build_dir.mkdir(parents=True, exist_ok=True)
    cpp = build_dir / f"{dsp_path.stem}-{key}.cpp"
    run([faust, "-a", str(ARCH), "-I", str(dsp_path.parent), str(dsp_path), "-o", str(cpp)],
        "faust")
    inc = subprocess.run([faust, "--includedir"], capture_output=True, text=True).stdout.strip()
    run([cxx, "-O2", "-std=c++17", *([f"-I{inc}"] if inc else []), str(cpp), "-o", str(binary)],
        "c++ (Faust)")
    return binary


def render_faust(notes, spec: Spec, part: dict, length: float, tmp: Path) -> np.ndarray:
    sound = part["sound"]
    dsp_path = spec.resolve(sound["path"])
    if not dsp_path.is_file():
        raise BackendUnavailable(f"Faust source {dsp_path} not found")
    binary = faust_binary(dsp_path, spec.dir / "renders" / ".build" / "faust")
    sr = spec.sample_rate
    release = sound.get("release", 0.5)
    total = int(length * sr)
    lines = [
        f"{int(n.start * sr)} {max(1, int((n.end - n.start) * sr))} {int(release * sr)} "
        f"{midi_to_hz(n.pitch):.4f} {n.velocity / 127:.4f}"
        for n in notes
    ]
    note_file, out = tmp / "notes.txt", tmp / "out.f32"
    note_file.write_text("\n".join(lines) + "\n")
    run([str(binary), str(sr), str(total), str(note_file), str(out)], "faust render")
    raw = np.fromfile(out, dtype="<f4")
    chans = max(1, len(raw) // total) if total else 1
    audio = raw[: total * chans].reshape(total, chans).astype(np.float64)
    return audio * 10 ** (sound.get("gain_db", 0) / 20)


RENDERERS = {
    "fluidsynth": render_fluidsynth,
    "sfizz": render_sfizz,
    "csound": render_csound,
    "faust": render_faust,
}
