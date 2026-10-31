import json
import shutil
from fractions import Fraction

import pytest
import yaml
from music21 import converter, duration, pitch

from stemma.cli import main
from stemma.score import ly_duration, ly_pitch

# A part that exercises ties, chords, humanised timing and flat spelling in C minor.
LEAD = '''
def build(ctx):
    ctx.add("G4", 3, 2)               # crosses the barline into bar 2
    ctx.chord(["C4", "Eb4", "G4"], 4 + 2, 2)
    ctx.add("Bb4", 8.012, 1)          # humanised: lands on beat 0 of bar 3
    ctx.add("F#4", 9, 1)
'''


def _demo(scratch_root, capsys, extra_part=True):
    assert main(["new", "demo"]) == 0
    track = scratch_root / "tracks/demo"
    if extra_part:
        (track / "parts/lead.py").write_text(LEAD)
        data = yaml.safe_load((track / "track.yaml").read_text())
        data["parts"].append({"name": "lead", "role": "lead", "source": "builtin",
                              "generator": "parts/lead.py", "sound": {"preset": "pulse-lead"},
                              "score": {"name": "Lead"}})
        (track / "track.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    assert main(["midi", "demo"]) == 0
    capsys.readouterr()
    return track


def _score(capsys, *args):
    assert main(["score", "demo", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_full_score(scratch_root, capsys):
    track = _demo(scratch_root, capsys)
    report = _score(capsys, "--format", "musicxml", "ly")
    assert report["files"] == ["renders/score/demo.musicxml", "renders/score/demo.ly"]
    assert [p["part"] for p in report["parts"]] == ["drums", "bass", "lead"]

    sc = converter.parse(track / "renders/score/demo.musicxml")
    assert len(sc.parts) == 3
    for part in sc.parts:
        measures = part.getElementsByClass("Measure")
        assert len(measures) == 8
        for m in measures:
            assert m.duration.quarterLength == 4, (part.partName, m.number)
    drums, bass, lead = sc.parts
    assert drums.recurse().getElementsByClass("Clef").first().sign == "percussion"
    assert bass.recurse().getElementsByClass("Clef").first().sign == "F"
    key = lead.recurse().getElementsByClass("KeySignature").first()
    assert key.sharps == -3
    assert lead.partName == "Lead"

    notes = list(lead.recurse().notes)
    g1, g2 = notes[0], notes[1]
    assert (g1.measureNumber, g1.offset, g1.tie.type) == (1, 3.0, "start")
    assert (g2.measureNumber, g2.offset, g2.tie.type) == (2, 0.0, "stop")
    assert [p.name for p in notes[2].pitches] == ["C", "E-", "G"]
    bflat = notes[3]
    assert (bflat.measureNumber, bflat.offset, bflat.name) == (3, 0.0, "B-")
    assert notes[4].name == "G-"  # F# respelt as a flat in C minor

    ly = (track / "renders/score/demo.ly").read_text()
    for needle in ("\\key c \\minor", "\\time 4/4", "\\drummode", "\\tempo 4 = 100",
                   "\\mark \\markup \\box \"b\"", "g'4~", "<c' ees' g'>2"):
        assert needle in ly, needle


def test_section_and_part(scratch_root, capsys):
    track = _demo(scratch_root, capsys)
    report = _score(capsys, "--section", "b", "--part", "bass", "--format", "musicxml")
    assert report["bars"] == 4
    assert report["files"] == ["renders/sections/b/score/bass.musicxml"]
    sc = converter.parse(track / "renders/sections/b/score/bass.musicxml")
    assert len(sc.parts) == 1
    assert len(sc.parts[0].getElementsByClass("Measure")) == 4


def test_excluded_part_and_unknown(scratch_root, capsys):
    _demo(scratch_root, capsys, extra_part=False)
    assert main(["score", "demo", "--part", "nope"]) == 1


def test_pdf_skipped_without_lilypond(scratch_root, capsys, monkeypatch):
    _demo(scratch_root, capsys, extra_part=False)
    monkeypatch.setattr(shutil, "which", lambda exe: None)
    report = _score(capsys, "--format", "pdf")
    assert report["lilypond"] == "absent"
    assert report["files"] == []
    assert any("lilypond is not installed" in w for w in report["warnings"])


@pytest.mark.skipif(shutil.which("lilypond") is None, reason="lilypond not installed")
def test_pdf(scratch_root, capsys):
    track = _demo(scratch_root, capsys)
    report = _score(capsys)
    assert report["lilypond"] == "compiled", report["warnings"]
    assert (track / "renders/score/demo.pdf").is_file()


def test_ly_helpers():
    assert ly_pitch(pitch.Pitch("C4")) == "c'"
    assert ly_pitch(pitch.Pitch("B-2")) == "bes,"
    assert ly_pitch(pitch.Pitch("F#5")) == "fis''"
    assert ly_duration(duration.Duration(1.5)) == "4."
    assert ly_duration(duration.Duration(Fraction(1, 3))) == "8*2/3"
    assert ly_duration(duration.Duration(4)) == "1"
