"""Write a track as sheet music: MusicXML, LilyPond source and (with lilypond) PDF.

Notes come from each part's MIDI file, so hand-written MIDI is scored too. They
are quantised to ``score.grid`` from the spec, laid out in bars by music21
(rests, ties over barlines, chords for overlapping notes, spelling in the key)
and written out. Drums go on a percussion stave using the GM drum map.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .errors import StemmaError
from .midi import is_drum, read_notes
from .paths import render_root
from .spec import Spec, is_audio_part
from .theory import note_name

# GM drum number -> (display step, display octave, notehead, LilyPond drum name).
# Positions follow the common five-line kit layout.
DRUM_MAP: dict[int, tuple[str, int, str, str]] = {
    35: ("F", 4, "normal", "bda"),
    36: ("F", 4, "normal", "bd"),
    37: ("C", 5, "x", "ss"),
    38: ("C", 5, "normal", "sn"),
    39: ("D", 5, "x", "hc"),
    40: ("C", 5, "normal", "sne"),
    41: ("A", 4, "normal", "tomfl"),
    42: ("G", 5, "x", "hh"),
    43: ("A", 4, "normal", "tomfh"),
    44: ("D", 4, "x", "hhp"),
    45: ("B", 4, "normal", "toml"),
    46: ("G", 5, "circle-x", "hho"),
    47: ("D", 5, "normal", "tomml"),
    48: ("E", 5, "normal", "tommh"),
    49: ("A", 5, "x", "cymc"),
    50: ("E", 5, "normal", "tomh"),
    51: ("F", 5, "x", "cymr"),
    52: ("A", 5, "x", "cymch"),
    53: ("F", 5, "diamond", "rb"),
    54: ("E", 5, "x", "tamb"),
    55: ("A", 5, "x", "cyms"),
    56: ("E", 5, "triangle", "cb"),
    57: ("B", 5, "x", "cymcb"),
    59: ("F", 5, "x", "cymrb"),
}
DRUM_FALLBACK = ("B", 4, "x", "ss")

CLEFS = {
    "treble": "TrebleClef",
    "treble_8": "Treble8vbClef",
    "bass": "BassClef",
    "bass_8": "Bass8vbClef",
    "alto": "AltoClef",
    "percussion": "PercussionClef",
}
CLEF_NAMES = {v: k for k, v in CLEFS.items()}

# Mean velocity upper bounds for each dynamic marking.
DYNAMICS = [(40, "pp"), (56, "p"), (72, "mp"), (88, "mf"), (104, "f"), (128, "ff")]


@dataclass
class QNote:
    pitch: int
    start: Fraction  # quarter notes from the start of the excerpt
    length: Fraction
    velocity: int


def _music21():
    try:
        import music21
    except ImportError as e:  # pragma: no cover - music21 is a core dependency
        raise StemmaError("music21 is not installed; run `uv sync`") from e
    return music21


# Quantising -----------------------------------------------------------------
def quantise(spec: Spec, part: dict, span: tuple[float, float]) -> tuple[list[QNote], dict]:
    """Read a part's MIDI, keep notes inside ``span`` (beats) and snap them to the grid."""
    step = Fraction(4, spec.score["grid"])
    lo, hi = span
    out: dict[tuple[Fraction, int], QNote] = {}
    shifts, merged = [], 0
    for n in read_notes(spec.midi_path(part)):
        b0 = n.start / spec.seconds_per_beat
        b1 = n.end / spec.seconds_per_beat
        q0 = round(Fraction(b0) / step) * step
        if not lo <= q0 < hi:
            continue
        q1 = max(round(Fraction(b1) / step) * step, q0 + step)
        q1 = min(q1, Fraction(hi))
        shifts.append(abs(float(q0) - float(b0)))
        key = (q0 - Fraction(lo), n.pitch)
        if key in out:
            merged += 1
            if q1 - q0 > out[key].length:
                out[key].length = q1 - q0
            continue
        out[key] = QNote(int(n.pitch), q0 - Fraction(lo), q1 - q0, int(n.velocity))
    notes = sorted(out.values(), key=lambda n: (n.start, n.pitch))
    # A repeated pitch cuts off the previous one rather than overlapping it.
    last: dict[int, QNote] = {}
    for n in notes:
        prev = last.get(n.pitch)
        if prev and prev.start + prev.length > n.start:
            prev.length = n.start - prev.start
        last[n.pitch] = n
    stats = {
        "max_quantise_shift_beats": round(max(shifts), 4) if shifts else 0.0,
        "off_grid": int(sum(s > float(step) / 4 for s in shifts)),
        "merged": merged,
    }
    return notes, stats


# Building the music21 score ---------------------------------------------------
def _spell(m21, midi: int, sharps: int):
    """Spell a MIDI note for the key: sharps in sharp keys, flats in flat keys."""
    p = m21.pitch.Pitch(midi=midi)
    if p.accidental is not None and p.accidental.alter != 0:
        if (sharps > 0 and p.accidental.alter < 0) or (sharps < 0 and p.accidental.alter > 0):
            p = p.getEnharmonic()
    return p


def _dynamic(velocity: float) -> str:
    for bound, mark in DYNAMICS:
        if velocity < bound:
            return mark
    return "ff"


def _clef(m21, name: str, part_stream, role: str | None):
    if name == "auto":
        if role == "bass":
            return m21.clef.BassClef()
        return m21.clef.bestClef(part_stream, recurse=True)
    return getattr(m21.clef, CLEFS[name])()


def _pitched_part(m21, notes: list[QNote], total: Fraction, sharps: int, shift: int):
    flat = m21.stream.Part()
    for n in notes:
        if n.length <= 0:
            continue
        el = m21.note.Note(_spell(m21, n.pitch + 12 * shift, sharps))
        el.quarterLength = n.length
        el.volume.velocity = n.velocity
        flat.insert(n.start, el)
    sliced = flat.chordify() if notes else m21.stream.Part()
    part = m21.stream.Part()
    for el in sliced.notesAndRests:
        offset = el.offset
        if isinstance(el, m21.chord.Chord) and len(el.pitches) == 1:
            single = m21.note.Note(el.pitches[0])
            single.duration = el.duration
            single.tie = el.notes[0].tie
            single.volume.velocity = el.notes[0].volume.velocity
            el = single
        part.insert(offset, el)
    return part


def _drum_part(m21, notes: list[QNote], total: Fraction, bar: Fraction, step: Fraction):
    """Hits grouped by onset; each lasts until the next hit, the barline or one beat."""
    part = m21.stream.Part()
    unmapped: set[int] = set()
    onsets = sorted({n.start for n in notes})
    for i, t in enumerate(onsets):
        nxt = onsets[i + 1] if i + 1 < len(onsets) else total
        bar_end = (t // bar + 1) * bar
        length = max(min(nxt - t, bar_end - t, Fraction(1)), step)
        hits = []
        for n in (n for n in notes if n.start == t):
            if n.pitch not in DRUM_MAP:
                unmapped.add(n.pitch)
            step_, octave, head, lily = DRUM_MAP.get(n.pitch, DRUM_FALLBACK)
            u = m21.note.Unpitched(displayName=f"{step_}{octave}")
            u.notehead = head
            u.volume.velocity = n.velocity
            u.editorial.lily = lily
            hits.append(u)
        el = hits[0] if len(hits) == 1 else m21.percussion.PercussionChord(hits)
        el.quarterLength = length
        part.insert(t, el)
    return part, sorted(unmapped)


def build_score(spec: Spec, section: str | None = None, only: str | None = None):
    """Return ``(music21 Score, report)`` for the track or one section."""
    m21 = _music21()
    bar = Fraction(spec.beats_per_bar).limit_denominator(64)
    step = Fraction(4, spec.score["grid"])
    sections = [spec.section(section)] if section else spec.sections
    first_bar = sections[0].start_bar
    lo = float(first_bar * bar)
    total = sum(s.bars for s in sections) * bar
    tonic_name, mode = spec.key.split()
    key_sig = m21.key.Key(tonic_name.replace("b", "-"), mode)

    score = m21.stream.Score()
    score.metadata = m21.metadata.Metadata()
    score.metadata.title = spec.title + (f" ({section})" if section else "")
    if spec.data.get("artist"):
        score.metadata.composer = spec.data["artist"]

    audio_only = [p["name"] for p in spec.parts if is_audio_part(p)
                  and (not only or p["name"] == only)]
    chosen = [p for p in spec.parts if (not only or p["name"] == only)
              and p.get("score", {}).get("include", True) and not is_audio_part(p)]
    if only and not chosen:
        part = spec.part(only)  # raises for an unknown part
        if is_audio_part(part):
            raise StemmaError(f"part {only!r} is generated audio and has no notes to score")
        raise StemmaError(f"part {only!r} has score.include set to false")
    if not chosen:
        raise StemmaError("no parts to score")

    parts_report, warnings = [], []
    for idx, p in enumerate(chosen):
        opts = p.get("score", {})
        notes, stats = quantise(spec, p, (lo, lo + float(total)))
        drum = is_drum(p)
        unmapped: list[int] = []
        if drum:
            part, unmapped = _drum_part(m21, notes, total, bar, step)
            clef = m21.clef.PercussionClef()
            inst = m21.instrument.UnpitchedPercussion()
        else:
            part = _pitched_part(m21, notes, total, key_sig.sharps, opts.get("octave_shift", 0))
            clef = _clef(m21, opts.get("clef", "auto"), part, p.get("role"))
            program = p.get("sound", {}).get("program")
            inst = (m21.instrument.instrumentFromMidiProgram(program) if program is not None
                    else m21.instrument.Instrument())
        label = opts.get("name", p["name"])
        inst.partName = label
        inst.partAbbreviation = None
        part.id = f"P{idx + 1}"
        part.partName = label
        part.insert(0, inst)
        part.insert(0, clef)
        part.insert(0, m21.key.Key(key_sig.tonic, mode) if not drum else m21.key.KeySignature(0))
        part.insert(0, m21.meter.TimeSignature(f"{spec.numerator}/{spec.denominator}"))
        if idx == 0:
            part.insert(0, m21.tempo.MetronomeMark(number=spec.tempo, referent=1.0))
            for s in sections:
                off = (s.start_bar - first_bar) * bar
                part.insert(off, m21.expressions.RehearsalMark(s.name))
        # One dynamic per section, where the level changes.
        current = None
        for s in sections:
            s0 = (s.start_bar - first_bar) * bar
            s1 = s0 + s.bars * bar
            vels = [n.velocity for n in notes if s0 <= n.start < s1]
            if not vels:
                continue
            mark = _dynamic(sum(vels) / len(vels))
            if mark != current:
                first = min(n.start for n in notes if s0 <= n.start < s1)
                part.insert(first, m21.dynamics.Dynamic(mark))
                current = mark
        part.makeRests(refStreamOrTimeRange=[0, float(total)], fillGaps=True, inPlace=True)
        part.makeNotation(inPlace=True)
        part.splitAtDurations(recurse=True)
        score.insert(0, part)

        elements = list(part.recurse().notesAndRests)
        entry = {
            "part": p["name"],
            "staff": "percussion" if drum else CLEF_NAMES.get(type(clef).__name__, clef.sign),
            "measures": len(part.getElementsByClass("Measure")),
            "notes": len(notes),
            "chords": sum(1 for e in elements if len(getattr(e, "notes", ())) > 1),
            "rests": sum(1 for e in elements if e.isRest),
            **stats,
        }
        if notes and not drum:
            shift = 12 * opts.get("octave_shift", 0)
            entry["written_range"] = [note_name(min(n.pitch for n in notes) + shift),
                                      note_name(max(n.pitch for n in notes) + shift)]
        if unmapped:
            entry["unmapped_drums"] = unmapped
            warnings.append(f"{p['name']}: GM drum notes {unmapped} have no notation mapping; "
                            f"written on B4 as side stick")
        if stats["off_grid"]:
            warnings.append(
                f"{p['name']}: {stats['off_grid']} of {len(notes)} notes were more than a "
                f"quarter of a grid step off the 1/{spec.score['grid']} grid; "
                "try a finer score.grid (12 or 24 for triplets)")
        if not notes:
            warnings.append(f"{p['name']}: no notes in range; written as rests")
        parts_report.append(entry)
    report = {"parts": parts_report, "warnings": warnings}
    if audio_only:
        report["not_scored"] = {n: "generated audio, no notes" for n in audio_only}
    return score, report


# LilyPond ---------------------------------------------------------------------
LY_TYPES = {"breve": "\\breve", "whole": "1", "half": "2", "quarter": "4", "eighth": "8",
            "16th": "16", "32nd": "32", "64th": "64", "128th": "128"}
LY_CLEFS = {"G": "treble", "F": "bass", "C": "alto"}
LY_ACC = {-2: "eses", -1: "es", 0: "", 1: "is", 2: "isis"}


def ly_pitch(p) -> str:
    """LilyPond absolute pitch: c is C3, c' is C4."""
    alter = int(p.accidental.alter) if p.accidental is not None else 0
    marks = p.octave - 3
    return p.step.lower() + LY_ACC[alter] + ("'" * marks if marks > 0 else "," * -marks)


def ly_duration(d) -> str:
    if d.type not in LY_TYPES:
        raise StemmaError(f"cannot write duration {d.quarterLength} ({d.type}) in LilyPond")
    out = LY_TYPES[d.type] + "." * d.dots
    for t in d.tuplets:
        out += f"*{t.numberNotesNormal}/{t.numberNotesActual}"
    return out


def _ly_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tied(n) -> bool:
    return n.tie is not None and n.tie.type in ("start", "continue")


def _ly_event(m21, el, drum: bool) -> str:
    dur = ly_duration(el.duration)
    if el.isRest:
        return "r" + dur
    if drum:
        hits = el.notes if isinstance(el, m21.percussion.PercussionChord) else [el]
        names = [getattr(h.editorial, "lily", DRUM_FALLBACK[3]) for h in hits]
        return (names[0] if len(names) == 1 else "<" + " ".join(names) + ">") + dur
    if el.isChord:
        inner = " ".join(ly_pitch(n.pitch) + ("~" if _tied(n) else "") for n in el.notes)
        return f"<{inner}>{dur}"
    return ly_pitch(el.pitch) + dur + ("~" if _tied(el) else "")


def to_lilypond(m21, score, spec: Spec, report: dict) -> str:
    tonic, mode = spec.key.split()
    ly_tonic = tonic[0].lower() + {"#": "is", "b": "es"}.get(tonic[1:], "")
    lines = ['\\version "2.24.0"', "", "\\header {",
             f"  title = {_ly_string(score.metadata.title)}"]
    if score.metadata.composer:
        lines.append(f"  composer = {_ly_string(score.metadata.composer)}")
    lines += ["  tagline = ##f", "}", "", "\\score {", "  <<"]
    for part, entry in zip(score.parts, report["parts"], strict=True):
        drum = entry["staff"] == "percussion"
        name = _ly_string(part.partName or entry["part"])
        if drum:
            lines.append(f"    \\new DrumStaff \\with {{ instrumentName = {name} }} \\drummode {{")
        else:
            lines.append(f"    \\new Staff \\with {{ instrumentName = {name} }} {{")
            clef = part.recurse().getElementsByClass("Clef").first()
            ly_clef = LY_CLEFS.get(clef.sign, "treble") + ("_8" if clef.octaveChange == -1 else "")
            lines.append(f"      \\clef {_ly_string(ly_clef)}")
            lines.append(f"      \\key {ly_tonic} \\{mode}")
        lines.append(f"      \\time {spec.numerator}/{spec.denominator}")
        if part is score.parts[0]:
            lines.append(f"      \\tempo 4 = {spec.tempo:g}")
        for m in part.getElementsByClass("Measure"):
            marks: dict[float, list[str]] = {}
            for rm in m.getElementsByClass("RehearsalMark"):
                marks.setdefault(rm.offset, []).append(
                    f"\\mark \\markup \\box {_ly_string(rm.content)}")
            dyns = {d.offset: d.value for d in m.getElementsByClass("Dynamic")}
            events = []
            for el in m.notesAndRests:
                pre = " ".join(marks.pop(el.offset, []))
                ev = _ly_event(m21, el, drum)
                if el.offset in dyns and not el.isRest:
                    ev += "\\" + dyns.pop(el.offset)
                events.append((pre + " " + ev).strip())
            lines.append("      " + " ".join(events) + f" |  % {m.number}")
        lines.append('      \\bar "|."')
        lines.append("    }")
    lines += ["  >>", "  \\layout { }", "}", ""]
    return "\n".join(lines)


# Entry point --------------------------------------------------------------------
def score(spec: Spec, section: str | None = None, only: str | None = None,
          formats: list[str] | None = None) -> dict:
    """Write the score files and return a report."""
    m21 = _music21()
    formats = formats or spec.score["formats"]
    unknown = sorted(set(formats) - {"musicxml", "ly", "pdf"})
    if unknown:
        raise StemmaError(f"unknown score formats {unknown}; use musicxml, ly or pdf")
    sc, report = build_score(spec, section, only)
    out_dir = render_root(spec.dir, section) / "score"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = only or spec.slug
    files = []
    if "musicxml" in formats:
        path = out_dir / f"{stem}.musicxml"
        sc.write("musicxml", fp=str(path))
        files.append(path)
    ly_text = to_lilypond(m21, sc, spec, report) if {"ly", "pdf"} & set(formats) else None
    ly_path = out_dir / f"{stem}.ly"
    if ly_text is not None:
        ly_path.write_text(ly_text)
        if "ly" in formats:
            files.append(ly_path)
    status = "not requested"
    if "pdf" in formats:
        status, pdf, msg = _compile_pdf(ly_path)
        if pdf:
            files.append(pdf)
        if msg:
            report["warnings"].append(msg)
        if "ly" not in formats:
            ly_path.unlink(missing_ok=True)
    return {"track": spec.slug, "section": section, "grid": spec.score["grid"],
            "bars": sum(s.bars for s in ([spec.section(section)] if section else spec.sections)),
            "files": [str(f.relative_to(spec.dir)) for f in files], "lilypond": status,
            **report}


def _compile_pdf(ly_path: Path) -> tuple[str, Path | None, str | None]:
    exe = shutil.which("lilypond")
    if not exe:
        return "absent", None, ("pdf skipped: lilypond is not installed "
                                "(sudo apt install lilypond); the .ly file is ready to compile")
    try:
        proc = subprocess.run([exe, "--pdf", "-o", str(ly_path.with_suffix("")), str(ly_path)],
                              capture_output=True, text=True, timeout=600, cwd=ly_path.parent)
    except subprocess.TimeoutExpired:
        return "failed", None, "lilypond timed out after 600 s"
    pdf = ly_path.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.is_file():
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        return "failed", None, f"lilypond failed: {tail}"
    return "compiled", pdf, None
