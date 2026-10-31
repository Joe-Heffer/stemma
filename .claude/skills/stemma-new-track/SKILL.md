---
name: stemma-new-track
description: Start a new stemma track from a written brief and take it to a first full render. Use when asked to make, compose or produce a new piece of music, song, loop, jingle or sound in this repository, or to scaffold a track under tracks/.
---

# Start a new track

Goal: a track folder with a brief, a valid spec, one generator per part and a
first master that builds with `stemma all`, recorded as revision 1.

Work through the steps in order. Each step ends with a command whose JSON you
read before moving on.

## 1. Check the tools

```sh
uv run stemma doctor
```

Note which renderers exist (`fluidsynth`, `sfizz`, `csound`, `faust`,
soundfonts, Pedalboard, matplotlib, LilyPond, `ELEVENLABS_API_KEY`). Only the
builtin synthesiser is guaranteed. Any part that needs something else must be
`optional: true`.

## 2. Scaffold

Choose a short kebab-case slug (`night-drive`), then:

```sh
uv run stemma new <slug> --title "Night Drive"
```

This copies `src/stemma/templates/track/` (spec, `notes.md`, drum and bass
generators). It refuses to overwrite an existing track.

## 3. Write the brief

Fill `## Brief` in `tracks/<slug>/notes.md`. If the request leaves any of
these open, choose and say so in `## Decisions`:

* Purpose and where it will be heard (streaming, game loop, podcast sting,
  broadcast). This sets `master.lufs` later.
* Mood and energy, in plain words.
* Length in seconds, and whether it must loop.
* References described in words (genre, era, instrumentation, tempo feel).
  Never paste or sample real recordings.
* Hard constraints (exact length, key, no drums, mono-safe).

The brief is also sent to ElevenLabs by `stemma reference` and by generated
parts, so keep it concrete and short.

Optional: `uv run stemma reference <slug> --seconds 30` if
`ELEVENLABS_API_KEY` is set and the user accepts the credit cost. Record the
prompt, the reference’s `bands_db`, `spectral_centroid_hz` and
`crest_factor_db` in `notes.md`. Do not re-run with `--force` without reason.

## 4. Write the spec

Edit `tracks/<slug>/track.yaml`. The schema is
`src/stemma/schema/track.schema.json`; `tracks/example-sketch/track.yaml` is a
complete worked example.

* `tempo`, `key` (`"A minor"`, `"F# dorian"`; modes: major, minor, dorian,
  phrygian, lydian, mixolydian, locrian), `time_signature`, `seed`.
* `sections`: name, bars and a one-line `description` of what happens. Work
  out the length first: seconds = bars × beats per bar × 60 / tempo. At
  120 bpm in 4/4 one bar is 2 s; at 90 bpm it is 2.67 s.
* Typical forms: loop (intro 4, main 8, outro 4); song (intro, verse,
  chorus, verse, chorus, bridge, chorus, outro); build-and-drop (intro, build,
  drop, break, drop, outro). Sections in multiples of 4 bars read naturally.
* `parts`: one per instrument, each with `name`, `role` and `source`. For
  `source: builtin` set `sound.preset` (`kit`, `saw-bass`, `pulse-lead`,
  `soft-pad`, `pluck`, `sine`). Tune the kit with `params: {kick_hz: …}` to
  the tonic or fifth (A1 = 55 Hz, E1 = 41.2, G1 = 49, C2 = 65.4, D2 = 73.4).
* Start the mix plain: `gain_db` per part and a highpass on everything except
  kick and bass. Leave buses, sidechain and automation for the mix revisions.
* `master: {lufs: -14, true_peak: -1}` unless the destination needs another
  target (see the `stemma-master` skill).

```sh
uv run stemma validate <slug>
```

Check `valid`, `bars`, `seconds` against the brief, and every section’s
`start_bar`.

## 5. Write the parts

Use the `stemma-write-part` skill for each generator. Write the rhythm
section first (drums, then bass), then harmony, then the lead. After each one:

```sh
uv run stemma midi <slug> --part <name>
```

## 6. First full build

```sh
uv run stemma all <slug>
```

Read, in this order: `render` (any `skipped` part and why), `mix.peak_dbfs`
(lower part gains if above 0), `master.limiter`, then
`analysis.warnings`, `analysis.masking`, `analysis.master` and
`analysis.sections`. The output is long; to see the essentials:

```sh
uv run stemma all <slug> | jq '{render: [.render[] | {part, status, reason}],
  warnings: .analysis.warnings, masking: .analysis.masking,
  master: .analysis.master | {lufs_integrated, true_peak_dbtp, crest_factor_db,
    loudness_range_lu, plr_db, bands_db, spectral_centroid_hz,
    stereo_width_above_300hz, tempo_bpm, key_tonal, limiter},
  sections: .analysis.sections}'
```

`tracks/<slug>/renders/analysis.json` holds the same report after any run.

## 7. Record and commit

Use the `stemma-revision-log` skill: add revision 1 to the log with the
master’s headline figures and any warnings, then commit (“New track: …”).

## Then

Improve the track one change at a time with the `stemma-mix-revision` skill,
and finish with `stemma-master`.
