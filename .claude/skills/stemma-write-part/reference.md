# Generator reference

Source: `src/stemma/compose.py`, `src/stemma/theory.py` and
`src/stemma/render/builtin.py`. If this file and the code disagree, the code
is right; update this file.

## `ctx` (compose.Context)

| Member | Meaning |
|--------|---------|
| `ctx.name` | part name |
| `ctx.part` | the part’s dict from `track.yaml` |
| `ctx.spec` | the whole spec |
| `ctx.tempo` | bpm |
| `ctx.beats_per_bar` | beats per bar from the time signature |
| `ctx.total_bars` | bars in the track |
| `ctx.sections` | list of sections, each with `name`, `start_bar`, `bars`, `description` |
| `ctx.scale` | `Scale` for the spec’s key |
| `ctx.rng` | seeded `numpy.random.Generator` (seed from spec `seed` and the part name) |
| `ctx.notes` | notes added so far (`pitch`, `start`, `length`, `velocity`) |
| `ctx.section(name)` | one section by name |
| `ctx.bars(*sections)` | start beat of every bar, optionally only in the named sections |
| `ctx.section_at(beat)` | section containing that beat |
| `ctx.bar_in_section(beat)` | 0-based bar index within its section |
| `ctx.add(pitch, start, length, velocity=90)` | add one note; velocity is clipped to 1–127; returns the note |
| `ctx.chord(pitches, start, length, velocity=80, strum=0)` | add several notes, each later by `strum` beats |
| `ctx.humanise(timing=0.01, velocity=6)` | jitter start (beats, normal σ) and velocity of every note so far |

`humanise` affects only the notes already added, so call it last, or call it
after each layer with different amounts.

Useful idioms:

```python
for bar in ctx.bars():
    section = ctx.section_at(bar).name
    i = ctx.bar_in_section(bar)
    last_bar = i == ctx.section(section).bars - 1   # place a fill here
    chord_index = int(bar // ctx.beats_per_bar) % len(PROGRESSION)

if ctx.rng.random() < 0.3:             # occasional variation, reproducible
    ...
```

## Theory helpers (`from stemma.theory import …`)

| Function | Example | Result |
|----------|---------|--------|
| `note(name)` | `note("A2")` | 45 |
| `note_name(midi)` | `note_name(61)` | `"C#4"` (sharps only) |
| `Scale(key)` | `Scale("A minor")` | `.tonic` 9, `.mode` `"minor"` |
| `scale.degree(d, octave=4)` | `degree(0, 1)` in A minor | 33 (A1); degrees are 0-based and may be negative or above 6 |
| `scale.chord(d, octave=3, size=3)` | `chord(5)` in A minor | F4 A4 C5 (the octave counts from the tonic: `degree(0, 3)` is A3) |
| `scale.contains(midi)` | | whether the note is in the key |
| `scale.nearest(midi)` | | snap to the nearest scale tone, ties go down |

Modes: major, minor (natural), dorian, phrygian, lydian, mixolydian, locrian.
The minor scale is natural minor: add the raised seventh yourself for a
harmonic-minor V chord (E G♯ B in A minor).

`scale.chord` stacks thirds in root position. Write voicings by hand when
voice leading matters.

## GM drum map (builtin `kit`)

| Note | Sound |
|------|-------|
| 35, 36 | kick (pitched by `kick_hz`, length by `kick_decay`) |
| 37 | rim |
| 38, 40 | snare (`snare_hz`) |
| 39 | clap |
| 42, 44 | closed hat |
| 46 | open hat |
| 49, 52, 55, 57 | crash |
| 51, 53, 59 | ride |
| 41, 43, 45, 47, 48, 50 | toms, 80–200 Hz, scaled by `tom_tune` |

Other notes are silent on the builtin kit.

Kick tuning: `kick_hz` 55 = A1, 41.2 = E1, 43.7 = F1, 49 = G1, 51.9 = G♯1,
58.3 = B♭1, 61.7 = B1, 65.4 = C2. Pick the tonic or the fifth of the key.

## Builtin presets

Set in the part: `sound: {preset: saw-bass, params: {sub: 0.15, cutoff: 400}}`.
`params` override the preset, which overrides these defaults:

| Param | Default | Meaning |
|-------|---------|---------|
| `wave` | saw | sine, triangle, saw, square, pulse |
| `pulse_width` | 0.5 | for `pulse` |
| `voices` | 1 | unison voices |
| `detune_cents` | 0 | spread between voices |
| `spread` | 0 | stereo spread of voices, 0–1; 0 gives a mono stem |
| `sub` | 0 | sine one octave down (raises the `sub` band) |
| `noise` | 0 | white noise in the oscillator mix |
| `attack`, `decay`, `sustain`, `release` | 0.005, 0.2, 0.7, 0.15 | amplitude envelope, seconds |
| `cutoff` | 3000 | lowpass Hz; 0 disables the filter |
| `resonance` | 0.8 | filter Q |
| `filter_env` | 0 | filter envelope depth in octaves |
| `filter_decay` | 0.2 | seconds |
| `keytrack` | 0.5 | cutoff follows pitch (1 = fully) |
| `velocity_cutoff` | 1.0 | octaves of cutoff change across the velocity range |
| `vibrato_rate`, `vibrato_cents`, `vibrato_delay` | 5.0, 0, 0.2 | |
| `drive` | 0 | tanh saturation, 0–10 |
| `level` | 0.3 | output level |

| Preset | Character | Main settings |
|--------|-----------|---------------|
| `sine` | pure tone, sub bass or test | no filter, full sustain |
| `saw-bass` | plucky filtered saw with sub and drive | `sub` 0.6, `cutoff` 260, `filter_env` 2.6, `drive` 1.5 |
| `pulse-lead` | two-voice detuned pulse with delayed vibrato | `cutoff` 1800, `vibrato_cents` 14, `spread` 0.4 |
| `soft-pad` | five-voice wide saw, slow attack and release | `attack` 0.6, `release` 1.2, `cutoff` 1100, `spread` 0.9 |
| `pluck` | short filtered saw, no sustain | `sustain` 0, `filter_env` 3.5, `cutoff` 500 |
| `kit` | synthesised drums on the GM map | `kick_hz` 50, `kick_decay` 0.22, `snare_hz` 185, `tom_tune` 1.0 |

Common adjustments: lower `saw-bass` `sub` (0.1–0.3) when the `sub` band is
too high; lower `cutoff` on the lead when `high_mid` is harsh; raise
`spread` or `voices` on pads for width; shorten `release` on a bass that
blurs the kick.

## Other sources

* `fluidsynth`: `sound: {soundfont: FluidR3_GM, program: 89}` (0-based GM
  program), optional `bank`; `drums: true` writes channel 10.
* `sfizz`: `sound: {path: patches/x.sfz}`.
* `csound`: `sound: {path: …orc, instrument: 1, release: 0.5}`; see
  `sounds/patches/fm-bell.orc` for the p-fields stemma passes.
* `faust`: `sound: {path: …dsp, release: 0.3}`; the patch must expose
  `freq`, `gain` and `gate`; see `sounds/patches/pluck.dsp`.

Adding any of these is covered by the `stemma-add-sound` skill.
