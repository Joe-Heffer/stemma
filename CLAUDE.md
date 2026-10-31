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
   Optionally, run `stemma reference <slug>` once (needs
   `ELEVENLABS_API_KEY`; it costs credits, so do not re-run it with
   `--force` without reason). Record the prompt and the reference’s
   `bands_db`, centroid and crest factor in `notes.md`.
2. **Spec.** Set tempo, key, metre and sections in `track.yaml`. Run
   `stemma validate <slug>` and check the section map and duration.
3. **Parts.** Write one generator per part. Run `stemma midi <slug> --part P`
   and check the note count, pitch range and velocity range it reports.
   A part with `source: elevenlabs` has no generator: its audio is generated
   from `sound.prompt` (one instrument per part) when you render it. Its
   revisions are prompt changes. See “Generated parts” below.
4. **Render only what changed:** `stemma render <slug> --part P --section S`.
   Unchanged parts are cached, so a full render is cheap once stems exist.
5. **Analyse:** `stemma analyse <slug> --section S` (or `--stem P`). Read the
   numbers and the `warnings` list before doing anything else. When the
   numbers point at a problem you cannot place, run `stemma plot <slug>` and
   look at the PNGs in `renders/plots/` (spectra of the stems, spectrogram,
   loudness over time).
6. **Revise.** Change one thing at a time. In your reply, say what you
   changed *because of* the analysis, quoting the figure, e.g. "bass `low`
   band was −3.1 dB and masked the kick; cut 3 dB at 120 Hz on the bass, now
   −5.4 dB". After the change, the report’s `delta` lists every figure that
   moved since the previous analysis, with old and new values: check that
   the change did what you meant and nothing else moved unexpectedly.
7. **Commit** after each working revision (validate passes, chain runs, no
   new warnings you have not explained). The message describes the musical
   change ("Lead: answer phrase climbs to G5 to lift into the outro"), not the
   file edits. Add a line to the revision log in `notes.md`.
8. When the section works, run `stemma all <slug>` for the whole track.
9. To check that parts read sensibly, or when sheet music is wanted, run
   `stemma score <slug>` (MusicXML, LilyPond and, with `lilypond`, PDF in
   `renders/score/`). Act on its `warnings`: `off_grid` notes mean the
   `score.grid` is too coarse for the part.

Work in small steps. Do not rewrite several parts and the mix at once: you
will not know which change helped.

## Rules

* Never commit `renders/`, WAV, FLAC or other rendered audio.
* Any sample, soundfont, SFZ or impulse response you add or reference must be
  freely licensed and recorded in `sounds/LICENCES.md` and, for shared
  sounds, `sounds/manifest.yaml`, in the same commit. Do not use material
  with non-commercial or unclear terms.
* Score output in `renders/score/` is build output too: do not commit it.
* Keep generators deterministic: use `ctx.rng` (seeded from `seed` in the
  spec), never `random` or the clock.
* Reference audio from `stemma reference` is only measured. It lives in
  `renders/reference/` and is never mixed into a track. To use generated
  audio, give a part `source: elevenlabs`.
* Generated part audio (`tracks/<slug>/generated/`) is never committed. Use
  it only on an ElevenLabs plan whose terms allow your intended use (the free
  tier does not allow commercial use), and record the plan and the date in
  the track’s `notes.md`.
* Ask before adding Python dependencies or system packages.
* Write docs and notes in British English.

## Mixing and mastering workflow

`docs/mixing.md` lists every effect and its parameters, sidechain,
automation, the mastering chain and how to read each figure. Work in this
order, and analyse after each stage:

1. **Gain staging.** Faders (`gain_db`) first, with no fx: the most important
   part (usually kick, bass or lead) loudest, the mix peaking around −6 dBFS.
2. **Subtractive EQ.** Highpass everything that is not kick or bass; cut
   where parts collide (`masking`, `octave_bands_db`, `plot --kind spectrum`).
3. **Dynamics.** Compress parts that jump around; check each stage’s
   `gain_reduction_db` in `mix.json` and remove any that do nothing. Gate or
   `transient`-shape drums if they are loose or boomy.
4. **Sidechain.** Duck the bass (or pads) under the kick with
   `mix.sidechain` when they share the low end. Check `percent_ducked_over_1db`
   stays low: a dip on each hit, not a quieter part.
5. **Space.** Reverb and delay on send buses, highpassed. Pan supporting
   parts; widen pads with `width` or `stereo_width`. Keep kick and bass centred.
6. **Automation.** Shape sections with `automation` (lift the lead in the
   chorus, drop the pad in the intro, ramp into the outro). Check that
   `sections` loudness and centroid follow the arrangement.
7. **Mix bus.** Gentle glue compression (1.5–2:1, 1–2 dB mean reduction) if
   the parts sound separate.
8. **Master.** Set `master.lufs` for the destination. Add `master.fx` only
   for whole-mix corrections (`stereo_width` with `mono_below_hz`, a broad EQ
   tilt). Then read `master.limiter`: if it reports a warning, fix the peaks
   in the mix rather than accept it.
9. **Check.** Read the master’s warnings, `loudness_range_lu`, `plr_db` and
   `low_end_correlation`, and look at `stemma plot` once more.

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
| `key_tonal` | key of the non-drum stems only | more reliable than `key` when drums are loud; used for the key warning |
| `clipped_samples` | samples at full scale | 0 |
| `octave_bands_db` | absolute power per octave (31.5 Hz–16 kHz), per stem | compare stems with each other, not with fixed numbers |
| `masking` | stem pairs both strong, and within 6 dB, in one octave | empty, or explained (kick and bass often share 63 Hz) |
| `loudness_range_lu` | EBU R128 loudness range | 3–8 LU for pop and electronic, more for acoustic music |
| `short_term_lufs_max` | loudest 3 s | 1–3 LU above integrated |
| `plr_db` | true peak minus integrated loudness | 8–13 dB at −14 LUFS; under 8 is over-limited |
| `low_end_correlation` | L/R correlation below 150 Hz | near 1; warning below 0.8 |
| `master.limiter` | master limiter gain reduction (`max_db`, `mean_db`) | mean under 1–2 dB, max under 6 dB |
| `sections` | loudness, crest, centroid and width per section of the master | should rise and fall with the arrangement |
| `delta` | figures that changed since the last different analysis | quote them in the revision log |

Stem figures are measured post-fader (after part fx, gain and pan, from
`renders/post-mix/`) once `mix` has run, so they show what each part
contributes. `measured` says which version was used.

`stemma reference` reports `compare`: master minus reference for each band,
the centroid, width above 300 Hz, crest factor and tempo. Read it as a
direction to move in, not a target to hit: a generated reference has its own
arrangement. Its `warnings` flag bands more than 3 dB apart, a centroid more
than 25% away, and a reference whose tempo or key does not match the spec
(the key estimate includes drums, so treat that one as a hint).

## Generated parts

A part with `source: elevenlabs` asks the ElevenLabs Music API for one
instrument on its own. The prompt adds the tempo, key, metre, form and brief to
the part’s `sound.prompt`, so describe only what the instrument plays and how
it sounds (“warm Rhodes comping on the chords, sparse in the intro”).

* The whole track is generated once and sliced per section, so `--section`
  renders cost nothing extra. The audio is cached by request in
  `tracks/<slug>/generated/` (not cleared by `make clean`). Changing the
  prompt, tempo, key or form makes a new request. `--force` re-renders stems
  without calling the API. `--force-generate` calls it again and costs credits.
* Mark generated parts `optional: true` so the track still builds without
  `ELEVENLABS_API_KEY`.
* The model does not follow the grid. `analyse` estimates each generated
  stem’s tempo and warns when it drifts from the spec. Use
  `sound.offset_seconds` to line the first downbeat up with bar 1. Check
  `key_tonal` too.
* Keep MIDI parts for anything that must lock tightly (drums, bass). Generated
  parts suit textures, pads and comping.

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
* **Kick and bass fight** (both strong at 63 Hz, low end blurs): tune the kick
  to the key, then add `sidechain` on the bass from the drums with
  `filter_hz: 120`, 2–4 dB.
* **Flat arrangement** (`sections` loudness within 1 LU everywhere,
  `loudness_range_lu` under 2 on a long track): automate levels per section,
  thin the intro, add parts for the peak.

## Common mastering problems

* **Limiter working too hard** (`master.limiter` warning, `plr_db` under 8):
  find the loud peaks (usually kick or snare; check stem `crest_factor_db`),
  compress or lower that part, or lower `master.lufs`.
* **Stereo low end** (`low_end_correlation` warning): find the stereo part
  below 150 Hz (a wide pad, a stereo reverb on the bass), highpass or narrow
  it; as a last resort add `{type: stereo_width, mono_below_hz: 120}` to
  `master.fx`.
* **Dull or harsh master** against a reference: a broad `highshelf` or
  `lowshelf` of 1–2 dB in `master.fx`, not a large EQ move. If more is needed,
  fix the parts.
* **Integrated loudness misses the target**: `normalise` is off, or the mix
  is so peaky the limiter cannot reach it in six passes. Read
  `master.json`’s `gain_db` and limiter figures.
