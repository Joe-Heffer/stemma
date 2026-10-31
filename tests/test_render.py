import shutil

import numpy as np
import pytest

from stemma.dsp import limiter, true_peak_envelope
from stemma.master import integrated_lufs, master_audio
from stemma.midi import NoteEvent
from stemma.render import builtin, select_notes
from stemma.render.external import csound_score, fluidsynth_cmd

SR = 48000


@pytest.mark.parametrize("preset", sorted(p for p in builtin.PRESETS if p != "kit"))
def test_synth_preset_renders_a_note(preset):
    audio = builtin.render([NoteEvent(57, 0.1, 0.6, 100)], {"preset": preset}, SR, 1.5, 0)
    assert audio.shape[0] == int(1.5 * SR)
    assert np.all(np.isfinite(audio))
    assert np.abs(audio).max() > 0.01
    assert np.abs(audio[: int(0.09 * SR)]).max() == 0  # silent before the note
    assert abs(audio.mean()) < 0.02 * np.abs(audio).max()  # no DC offset


def test_render_is_deterministic():
    notes = [NoteEvent(p, i * 0.25, i * 0.25 + 0.1, 100) for i, p in enumerate([36, 38, 42, 46])]
    a = builtin.render(notes, {"preset": "kit"}, SR, 2, 3)
    b = builtin.render(notes, {"preset": "kit"}, SR, 2, 3)
    assert np.array_equal(a, b) and np.abs(a).max() > 0.05


def test_select_notes_clips_to_section():
    notes = [NoteEvent(60, 0, 1, 90), NoteEvent(62, 1.5, 3, 90), NoteEvent(64, 5, 6, 90)]
    out = select_notes(notes, 2, 4)
    assert [(n.pitch, n.start, n.end) for n in out] == [(62, 0, 1)]


def test_limiter_respects_true_peak():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((SR * 2, 2)) * 0.5
    y = limiter(x, SR, ceiling_db=-1.0)
    assert 20 * np.log10(true_peak_envelope(y).max()) <= -1.0 + 0.05


def test_master_hits_targets():
    rng = np.random.default_rng(1)
    t = np.arange(SR * 10) / SR
    x = 0.05 * np.sin(2 * np.pi * 110 * t)[:, None] + 0.02 * rng.standard_normal((len(t), 2))
    y, report = master_audio(x, SR, lufs=-14, true_peak=-1)
    assert integrated_lufs(y, SR) == pytest.approx(-14, abs=0.5)
    assert report["true_peak_dbtp"] <= -0.95


def test_csound_score_format():
    score = csound_score([NoteEvent(69, 0.5, 1.0, 127)], 1, 3.0)
    assert score.splitlines()[0] == "i 1 0.500000 0.500000 440.0000 1.0000 69 127"
    assert score.splitlines()[-1] == "e 3.000000"


def test_fluidsynth_command_is_dry(tmp_path):
    cmd = fluidsynth_cmd("fluidsynth", tmp_path / "a.sf2", tmp_path / "a.mid",
                         tmp_path / "o.wav", 48000)
    assert "synth.reverb.active=0" in cmd and cmd[-2:] == [str(tmp_path / "a.sf2"),
                                                           str(tmp_path / "a.mid")]


@pytest.mark.skipif(not shutil.which("fluidsynth"), reason="fluidsynth not installed")
def test_fluidsynth_renders_when_available(scratch_root):
    from stemma import sounds

    try:
        sounds.resolve("FluidR3_GM")
    except Exception:
        pytest.skip("FluidR3_GM soundfont not installed")
    from stemma.cli import main

    assert main(["new", "fs"]) == 0
    track = scratch_root / "tracks" / "fs" / "track.yaml"
    track.write_text(track.read_text().replace("source: builtin\n    generator: parts/bass.py",
                                               "source: fluidsynth\n    generator: parts/bass.py"))
    assert main(["midi", "fs"]) == 0
    assert main(["render", "fs", "--part", "bass", "--section", "a"]) == 0
    assert (scratch_root / "tracks/fs/renders/sections/a/stems/bass.wav").is_file()
