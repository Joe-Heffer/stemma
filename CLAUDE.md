# Working in stemma

You are producing music from text. A track is `tracks/<slug>/`: `track.yaml`
(the spec), `parts/*.py` (generators that write notes), `midi/` (their output,
or hand-written MIDI), `patches/` (Faust, Csound or SFZ sources) and
`notes.md` (brief, decisions, revision log). Audio in `renders/` is build
output: never commit it.

Run everything through `uv run stemma …` (or `make … TRACK=<slug>`). Every
command prints JSON. Run `uv run stemma doctor` once per session to see which
renderers exist.

## The loop

1. **Brief.** Write or read the brief in `notes.md`: purpose, mood, length,
   references described in words, and any hard constraints.
2. **Spec.** Set tempo, key, metre and sections in `track.yaml`. Run
   `stemma validate <slug>` and check the section map and duration.
3. **Parts.** Write one generator per part. Run `stemma midi <slug> --part P`
   and check the note count, pitch range and velocity range it reports.
4. **Render only what changed:** `stemma render <slug> --part P --section S`.
   Unchanged parts are cached, so a full render is cheap once stems exist.
5. **Analyse:** `stemma analyse <slug> --section S` (or `--stem P`). Read the
   numbers and the `warnings` list before doing anything else.
6. **Revise.** Change one thing at a time. In your reply, say what you
   changed *because of* the analysis, quoting the figure, e.g. "bass `low`
   band was −3.1 dB and masked the kick; cut 3 dB at 120 Hz on the bass, now
   −5.4 dB".
7. **Commit** after each working revision (validate passes, chain runs, no
   new warnings you have not explained). The message describes the musical
   change ("Lead: answer phrase climbs to G5 to lift into the outro"), not the
   file edits. Add a line to the revision log in `notes.md`.
8. When the section works, run `stemma all <slug>` for the whole track.

Work in small steps. Do not rewrite several parts and the mix at once: you
will not know which change helped.

## Rules

* Never commit `renders/`, WAV, FLAC or other rendered audio.
* Any sample, soundfont, SFZ or impulse response you add or reference must be
  freely licensed and recorded in `sounds/LICENCES.md` and, for shared
  sounds, `sounds/manifest.yaml`, in the same commit. Do not use material
  with non-commercial or unclear terms.
* Keep generators deterministic: use `ctx.rng` (seeded from `seed` in the
  spec), never `random` or the clock.
* Ask before adding Python dependencies or system packages.
* Write docs and notes in British English.

## Reading the analysis

| Field | Meaning | Typical aims |
|-------|---------|--------------|
| `lufs_integrated` | BS.1770 loudness | master at the target (−14 by default); stems are relative |
| `true_peak_dbtp` | 4× oversampled peak | master ≤ −1 dBTP |
| `crest_factor_db` | peak minus RMS | 8–14 dB for a punchy master; under 6 sounds squashed |
| `bands_db` | share of energy per band (sub < 60, low 60–250, low_mid 250–2k, high_mid 2–6k, air > 6k), 0 dB = all | see mixing notes |
| `spectral_centroid_hz` | brightness | rising when you meant to warm something up is a red flag |
| `stereo_width` | side energy share, 0 mono, 0.5 very wide | low on bass-heavy mixes, since kick and bass are mono |
| `stereo_width_above_300hz` | the same above 300 Hz | 0.05–0.3 for a full mix |
| `correlation` | L/R correlation | keep above 0; negative collapses in mono |
| `tempo_bpm`, `key` | estimates from audio | should match the spec (half/double tempo and relative keys are accepted) |
| `clipped_samples` | samples at full scale | 0 |
| `octave_bands_db` | absolute power per octave (31.5 Hz–16 kHz), per stem | compare stems with each other, not with fixed numbers |
| `masking` | stem pairs both strong, and within 6 dB, in one octave | empty, or explained (kick and bass often share 63 Hz) |

Stem figures are measured post-fader (after part fx, gain and pan, from
`renders/post-mix/`) once `mix` has run, so they show what each part
contributes. `measured` says which version was used.

The analysis is a proxy for listening, not a replacement. Use it to catch
problems and to confirm that a change did what you intended.

## Writing good parts

* **Register.** Give each part its own octave range. Bass roughly E1–A2, pads
  and chords C3–C5, lead melodies around A3–E6. Two parts in the same octave
  with the same rhythm will mask each other.
* **Voice leading.** Move chord voices by the smallest interval, hold common
  tones, avoid parallel fifths and octaves between outer voices, and resolve
  leading tones (B to A in A minor, the 7th up to the tonic).
* **Melody.** Put chord tones on strong beats and approach them by step; use
  leaps sparingly and follow a leap with a step back. Write in phrases
  (call and answer over two or four bars) and repeat with variation rather
  than repeating exactly.
* **Rhythm and dynamics.** Vary velocity: accents on downbeats, softer
  off-beats and ghost notes. Build intensity across sections with density and
  velocity, not just loudness. Leave space: rests let the lead breathe.
* **Bass.** Lock to the kick. Play roots on downbeats, use fifths and octaves
  for movement, and keep notes short enough that the kick is heard.
* **Drums.** Start from a genre's core pattern (four-on-the-floor kick;
  backbeat snare on 2 and 4; hats on eighths or sixteenths with accents).
  Vary hats with open hats on off-beats, add a fill in the last bar before a
  new section and a crash on its downbeat. Humanise lightly (timing
  0.003–0.01 beats, velocity ±4).
* **Tuning the kit.** The builtin kick is pitched (`kick_hz`, 55 = A1). Tune
  it to the key or to the fifth, or it will fight the bass.

## Common mixing problems

* **Masking** (parts blur together): check `masking` and the stems'
  `octave_bands_db`. Separate
  by register first, then by EQ (cut one part where the other lives), then by
  panning. Cutting is better than boosting.
* **Low-end build-up** (`sub` or `low` too high on the mix, crest factor
  falling): highpass everything that is not kick or bass (100–250 Hz for
  leads and pads), choose whether kick or bass owns the sub, and reduce the
  bass synth's `sub` level or add a low shelf cut.
* **Mud** (`low_mid` 250–500 Hz heavy, centroid low): a gentle peak cut
  around 300 Hz on bass and pads.
* **Harshness** (`high_mid` high, centroid climbing): lower the lead's filter
  `cutoff`, cut 2–5 kHz on the offending part, or tame hats' velocity.
* **Too narrow** (`stereo_width` under 0.05): pan supporting parts, raise
  pad `width`, send to a stereo reverb bus. Keep kick and bass centred.
* **Over-compression** (crest factor below ~6 dB): raise thresholds or
  ratios less aggressively; let the master limiter do less work by fixing
  levels in the mix.
* **Clipping or near-0 dBFS mix peaks**: stems and the mix are float, so
  nothing clips until mastering, but lower part gains if `mix` reports peaks
  above 0 dBFS so effects behave predictably.
