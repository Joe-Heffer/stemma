---
name: stemma-write-part
description: Write or revise a stemma part generator (tracks/<slug>/parts/*.py) that produces MIDI notes for drums, bass, chords, pads, arpeggios or a lead melody, and check its output with stemma midi and stemma score. Use when composing notes, changing a rhythm, melody, chord voicing or groove, or choosing a builtin synth preset.
---

# Write a part generator

A generator is a Python file in `tracks/<slug>/parts/` with one function,
`build(ctx)`, that adds notes to `ctx`. stemma writes them to
`midi/<part>.mid`. The part entry in `track.yaml` points at it with
`generator: parts/<name>.py`.

The full `ctx` and theory API, the GM drum map and every builtin preset
parameter are in [reference.md](reference.md). The example generators in
`tracks/example-sketch/parts/` show each role.

## Rules

* Deterministic: use `ctx.rng` for any randomness. Never import `random`,
  read the clock, or read files that change between runs.
* Times are in beats (quarter notes) from the start of the track. A bar starts
  at `bar`, the value from `ctx.bars()`; beat 3 of that bar is `bar + 2`.
* Notes may be MIDI numbers or names (`"A2"`, `"F#4"`, C4 = 60).
* Make the part section-aware: decide what happens from
  `ctx.section_at(bar).name` and `ctx.bar_in_section(bar)`, so changing the
  form in `track.yaml` keeps the part sensible.
* Keep a module docstring that says what the part plays (progression,
  pattern, range). It is the part’s design note.

## Steps

1. Decide the part’s job and register before writing code. Use the ranges in
   CLAUDE.md (bass E1–A2, chords and pads C3–C5, lead A3–E6) and check that
   no other part uses the same octave with the same rhythm.
2. Write the harmony as data at the top of the file (scale degrees or note
   names per bar), then loop over `ctx.bars()`.
3. Put the rhythm in tables of `(beat, pitch or interval, length, velocity)`
   rows, one per pattern variant (sparse, main, fill). This makes later
   revisions one-line edits.
4. Shape dynamics: accents on downbeats (100–120), off-beats softer
   (70–90), ghost notes 35–55. Lift velocity or density in later sections.
5. End with `ctx.humanise(timing=…, velocity=…)`: drums and bass 0.003–0.005
   beats and ±3–4; leads and pads up to 0.01 and ±6.
6. Generate and read the report:

   ```sh
   uv run stemma midi <slug> --part <name>
   ```

   Check `notes` (not zero; plausible for the density), `range` (inside the
   register you chose), `velocity` (a spread, not one value), `first_s` and
   `last_end_s` (the part enters and ends where the sections say).
7. Render only this part and one section, and check its stem:

   ```sh
   uv run stemma render <slug> --part <name> --section <section>
   uv run stemma analyse <slug> --section <section> --stem <name>
   ```

8. Check the notation reads sensibly:

   ```sh
   uv run stemma score <slug> --part <name>
   ```

   `off_grid` above 0 means notes fall between grid steps: either they are
   meant to (raise `score.grid` to 24 or 32 for triplets or fine figures) or
   the generator has a timing bug. Large `max_quantise_shift_beats` on a part
   with little humanisation points to the same. Use the part’s
   `score: {clef: bass_8}` or `octave_shift` if ledger lines pile up.

## Role recipes

**Drums** (`role: drums`, preset `kit`). Start from the genre’s core: kick on
every beat (house, synth-pop) or on 1 and the “and” of 3 (rock, hip hop);
snare or clap on 2 and 4; hats on eighths or sixteenths with an accent
pattern. Add an open hat on an off-beat every other bar, a fill across the
last one or two beats before a new section (snare sixteenths with a velocity
crescendo), and a crash on the new section’s downbeat. Thin the kit in intros
and outros. Tune `kick_hz` in the spec to the tonic or the fifth.

**Bass** (`saw-bass`). Root on the downbeat of each chord, locked to the
kick; fifths and octaves for movement; notes short enough (0.25–0.7 beats in
a busy groove) for the kick to speak. Choose each root in the octave nearest
the previous one and clamp to E1–A2 (see `nearest_root` in
`tracks/example-sketch/parts/bass.py`).

**Chords and pads** (`soft-pad`, or GM programs through FluidSynth). Three
or four voices between C3 and C5. Write explicit voicings per chord and
move each voice by the smallest step, holding common tones (Am A3 C4 E4 → F
A3 C4 F4 → C G3 C4 E4 → G G3 B3 D4). Avoid parallel fifths and octaves
between the outer voices. Use `ctx.chord(pitches, start, length, velocity,
strum=0.02)` for a slight strum on keys.

**Lead** (`pulse-lead`). Phrases of two or four bars as call and answer.
Chord tones on strong beats, stepwise approach, leaps followed by a step
back. Repeat the call and vary the answer; let the last answer climb to lift
into the next section. Leave rests: a lead that never stops masks
everything. Resolve leading tones (G♯ to A in A minor, the seventh up to the
tonic).

**Arpeggio** (`pluck`). Chord tones in a fixed rhythm (sixteenths or
eighths), one or two octaves above the pad, with the pattern turning at the
top. Keep velocity lower than the lead and accent the first note of each
group.

## Revising a part

Change one thing (the rhythm table, a voicing, the register), regenerate
with `stemma midi --part`, re-render that part and section, and compare. Say
in the revision log what changed musically and what the figures did (see the
`stemma-revision-log` skill).
