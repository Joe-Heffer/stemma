# stemma

Command-line tooling that lets an AI agent such as Claude Code produce music
tracks and sounds from a written brief, with no DAW and no GUI.

* Everything runs headlessly and reproducibly: `make all TRACK=<slug>`.
* Text is the source of truth. A track is a YAML spec, Python part generators,
  MIDI and patch sources. Rendered audio is a gitignored build artefact.
* Open formats throughout: YAML validated by JSON Schema, Standard MIDI Files,
  SF2/SF3, SFZ, Csound and Faust source, WAV and FLAC, and sheet music as
  MusicXML and LilyPond.
* `stemma analyse` turns audio into JSON (loudness, loudness range, true
  peak, spectral balance, tempo, key, stereo width, clipping, limiter gain
  reduction, per-section figures and what changed since the last run) so an
  agent can “hear” its work and iterate. `stemma plot` draws spectra, a
  spectrogram and loudness over time as PNGs it can look at.

## Prerequisites

Required:

* [uv](https://docs.astral.sh/uv/) (it installs Python 3.12+ and every Python dependency)
* GNU Make

Optional external renderers, each detected at run time (`stemma doctor`):

| Tool | Used for | Debian/Ubuntu |
|------|----------|---------------|
| FluidSynth + a GM soundfont | `source: fluidsynth` (SF2/SF3) | `sudo apt install fluidsynth fluid-soundfont-gm` |
| sfizz (`sfizz_render`) | `source: sfizz` (SFZ) | build from [sfizz](https://sfz.tools/sfizz/) or use its OBS packages |
| Csound | `source: csound` | `sudo apt install csound` |
| Faust + a C++ compiler | `source: faust` | `sudo apt install faust g++` |
| Pedalboard | higher-quality mix effects | `uv sync --extra fx` |
| matplotlib | PNG plots from `stemma plot` (music21 usually installs it) | `uv sync --extra plot` |
| LilyPond | PDF sheet music from `stemma score` | `sudo apt install lilypond` |

SoX and ffmpeg are handy for inspecting renders but not required.

The example track uses the built-in synthesiser for drums, bass and lead, so
`make all TRACK=example-sketch` works from a clean clone with only uv and make.
Its pad part uses FluidSynth and is marked `optional`, so it is skipped with a
warning when FluidSynth is missing.

## Quick start

```sh
git clone https://github.com/joe-heffer/stemma && cd stemma
make all TRACK=example-sketch          # midi → render → mix → master → analyse
ls tracks/example-sketch/renders       # stems/, post-mix/, mix.wav, master.wav, master.flac, analysis.json
make test
```

Start a new track:

```sh
uv run stemma new night-drive --title "Night Drive"
$EDITOR tracks/night-drive/track.yaml tracks/night-drive/parts/*.py
uv run stemma all night-drive
```

## Commands

All commands take a track slug (a folder under `tracks/`) and print JSON on stdout.

| Command | What it does |
|---------|--------------|
| `stemma new <slug> [--title T]` | Scaffold a track from the template |
| `stemma validate <slug>` | Validate `track.yaml` and print the bar/section map |
| `stemma midi <slug> [--part P]` | Run part generators, write `midi/<part>.mid`, report note ranges |
| `stemma render <slug> [--part P] [--section S] [--force] [--force-generate]` | Render stems; unchanged parts come from the cache |
| `stemma mix <slug> [--section S]` | Per-part fx, sidechain, gain, automation, pan, buses and sends into `renders/mix.wav` |
| `stemma master <slug> [--section S]` | Mastering chain, loudness normalisation and true-peak limiting to WAV, FLAC, MP3 or Ogg |
| `stemma analyse <slug> [--section S] [--stem P]` | Measurements per stem, mix, master and section, the change since the last run, and warnings |
| `stemma plot <slug> [--section S] [--kind K …] [--stem P …]` | Stem spectra, spectrogram and loudness over time as PNG in `renders/plots/` |
| `stemma analyse --file X.wav` | Analyse any audio file |
| `stemma score <slug> [--part P] [--section S] [--format …]` | Sheet music in `renders/score/`: MusicXML, LilyPond and PDF |
| `stemma reference <slug> [--prompt T] [--seconds N] [--file X]` | Generate a reference track from the brief (ElevenLabs) or load one, and compare the master with it |
| `stemma all <slug> [--section S]` | The whole chain |
| `stemma doctor` | Which external tools, soundfonts and engines are available |
| `stemma sounds list` / `fetch [NAME]` | Shared sounds from `sounds/manifest.yaml` |

`--section` renders, mixes and masters just one section into
`renders/sections/<name>/`, which keeps iteration fast.

The Makefile wraps these: `make render TRACK=example-sketch ARGS="--part lead"`.

## Reference tracks (optional)

A brief describes its references in words, which cannot be measured.
`stemma reference <slug>` sends a prompt built from `track.yaml` (title, tempo,
key, metre, section names and descriptions) and the `## Brief` section of
`notes.md` to the [ElevenLabs Music API](https://elevenlabs.io/docs/api-reference/music/compose),
analyses the instrumental it returns, and, once `renders/master.wav` exists,
compares the master with it: per-band balance, spectral centroid, width above
300 Hz, crest factor and tempo. Loudness is left out because both are
normalised.

```sh
export ELEVENLABS_API_KEY=...                 # from your ElevenLabs account
uv run stemma reference night-drive           # generate (or reuse) and compare
uv run stemma reference night-drive --prompt "Slow, warm synthwave, analogue pads, 90 bpm"
uv run stemma reference night-drive --file ~/refs/some-track.flac   # no API call
```

* The reference is a measuring stick, not material. It is written to
  `renders/reference/` (gitignored) and is never mixed, sampled or rendered
  into a part, so tracks still build offline and deterministically without it.
* Generation costs ElevenLabs credits (roughly 900 per minute of audio at the
  time of writing), so keep references short with `--seconds`. Requests are
  cached by their content: running the same request again reuses the file
  unless you pass `--force`.
* The generated audio is governed by ElevenLabs’ terms for your plan, not by
  this repository’s licence.
* The request is `POST /v1/music` with `prompt`, `music_length_ms`, `model_id`
  and `force_instrumental`. If ElevenLabs changes its API, adjust the
  constants at the top of `src/stemma/elevenlabs.py`.

## Generated parts (optional)

A part can be audio generated by the [ElevenLabs Music API](https://elevenlabs.io/docs/api-reference/music/compose)
instead of MIDI, one instrument per part:

```yaml
parts:
  - name: keys
    role: harmony
    source: elevenlabs
    optional: true            # skipped, with a warning, when ELEVENLABS_API_KEY is unset
    sound:
      prompt: "warm Rhodes electric piano comping on the chords, sparse in the intro"
      offset_seconds: 0.0     # trim the start so the first downbeat lands on bar 1
    mix: {gain_db: -6, pan: 0.2}
```

`stemma render` builds the prompt from the spec (title, tempo, key, metre,
sections and the `## Brief` in `notes.md`) plus `sound.prompt`, and asks for
that one instrument only. It requests the whole track once and slices it per
section. From there the stem goes through `mix`, `master` and `analyse` like
any other part. `midi` and `score` skip it.

* Audio is cached by request in `tracks/<slug>/generated/` (gitignored, kept
  by `make clean`). `--force` re-renders stems from the cached audio.
  `--force-generate` calls the API again.
* Generation costs credits (roughly 900 per minute of audio at the time of
  writing).
* The model may not hold the tempo or key exactly. `analyse` warns when a
  generated stem’s estimated tempo is more than 4% off the spec.
* The audio is governed by ElevenLabs’ terms for your plan. Check that they
  allow your use (the free tier is non-commercial) and record the plan in the
  track’s `notes.md`.

## Agent skills

`.claude/skills/` holds skills that Claude Code loads on demand: starting a
track from a brief, writing part generators, one analysis-driven mix
revision, mastering, recording a revision, generated (ElevenLabs) parts and
adding licensed sounds. Each is a step-by-step procedure with the exact
commands and the figures to read. CLAUDE.md lists them; `tests/test_skills.py`
keeps their commands in step with the CLI.

## Repository layout

```
CLAUDE.md                 instructions for agents working in this repo
.claude/skills/           agent skills: new track, write a part, mix revision, master, …
docs/mixing.md            mixing and mastering reference
src/stemma/               the package and CLI
  schema/track.schema.json  JSON Schema for track.yaml
  render/                 builtin synth, FluidSynth, sfizz, Csound and Faust backends
  templates/track/        what `stemma new` copies
sounds/                   shared patches and the soundfont manifest, with licences
tracks/<slug>/
  track.yaml              the spec
  parts/*.py              part generators (build(ctx) → notes)
  midi/                   one MIDI file per part (generated or hand-written)
  patches/                Faust, Csound or SFZ sources made for this track
  notes.md                brief, decisions, revision log
  renders/                build output, gitignored
tests/
```

## The spec

`track.yaml` holds title, tempo, key, time signature, ordered sections with bar
counts, parts (role, source, generator or MIDI file, sound reference, mix
settings), buses, the stereo mix bus, mastering targets (default −14 LUFS
integrated, −1 dBTP) and optional analysis target ranges. See
`tracks/example-sketch/track.yaml` and the schema for every field.

### Sources

* `builtin`: numpy synth presets `sine`, `saw-bass`, `pulse-lead`, `soft-pad`,
  `pluck`, and a synthesised GM drum `kit`. Override any parameter with
  `sound.params`.
* `fluidsynth`: `sound.soundfont` (manifest name or path), `program`, `bank`.
  Rendered dry (FluidSynth reverb and chorus off) so the mix stage owns effects.
* `sfizz`: `sound.path` to an `.sfz` file.
* `csound`: `sound.path` to an orchestra (`.orc`) with no header. stemma adds
  `sr`, `ksmps`, `nchnls = 2`, `0dbfs = 1`, and writes one score event per
  note with p4 = Hz, p5 = amplitude 0–1, p6 = MIDI note, p7 = velocity.
* `faust`: `sound.path` to a `.dsp` with `freq`, `gain` and `gate` controls.
  stemma compiles it with an offline note-player architecture and caches the binary.

### Mixing and mastering

[`docs/mixing.md`](docs/mixing.md) is the full reference: signal flow, every
effect and its parameters, sidechain, automation, the mastering chain, plots
and how to read the analysis.

* Effects: `gain`, `highpass`, `lowpass`, `peak`, `lowshelf`, `highshelf`,
  `compressor`, `limiter`, `gate`, `transient`, `reverb`, `delay` (in `beats`
  or `seconds`), `distortion`, `chorus`, `stereo_width` (with
  `mono_below_hz`), `mid_side_eq` and `convolution` (impulse responses), on
  parts, buses, the mix bus or the master. With Pedalboard installed
  (`mix.engine: auto`) the classic effects run through Pedalboard; otherwise,
  and for the stereo, gate, transient and convolution effects, through
  stemma’s numpy/scipy code. The engine used is recorded in
  `renders/mix.json`; pin it with `mix.engine` when you need renders to match
  across machines. Every compressor, limiter and gate reports its gain
  reduction there.
* `parts[].mix.sidechain` ducks a part under another part’s stem (bass under
  the kick).
* `automation` sets a part’s or bus’s level, or mutes it, per section, with
  optional ramps.
* `master.fx` is a mastering chain before loudness normalisation;
  `master.limiter` sets the limiter’s release and look-ahead, and
  `master.json` reports how hard it worked.

## Sheet music

`stemma score` reads each part's MIDI file (generated or hand-written),
quantises it to `score.grid` and writes notation with
[music21](https://web.mit.edu/music21/): bars, rests, ties over barlines,
chords where notes overlap, pitches spelt for the key, a rehearsal mark per
section and a dynamic per section from the mean velocity. Drums go on a
percussion stave using the GM drum map.

* `renders/score/<slug>.musicxml` opens in MuseScore, Dorico, Sibelius,
  Finale and Verovio.
* `renders/score/<slug>.ly` is LilyPond source. With `lilypond` installed it
  is compiled to `<slug>.pdf`; without it the PDF is skipped with a warning.

```yaml
score:
  grid: 16                         # 4, 8, 16, 32; 12 or 24 allow triplets
  formats: [musicxml, ly, pdf]
parts:
  - name: bass
    score: {clef: bass_8}          # auto, treble, treble_8, bass, bass_8, alto, percussion
  - name: fx
    score: {include: false}        # leave a part off the score
```

Each part also takes `octave_shift` (transpose the written part) and `name`
(the staff label). The report lists, per part, the stave, bar count, notes,
chords, rests, written range and how far quantising moved notes. `off_grid`
counts notes more than a quarter of a grid step away from the grid, which
usually means the part needs a finer or triplet grid.

The score is a reading of the MIDI, not an engraving: humanised timing is
snapped to the grid and note lengths are rounded. In flat keys every
accidental is spelt as a flat and in sharp keys as a sharp.

## Licences

stemma is MIT licensed. Copyleft tools are only ever run as separate
commands, never linked: FluidSynth and Csound (LGPL), the Faust compiler (GPL;
its generated code is not), SoX and ffmpeg. Pedalboard (GPL-3.0) is an
optional extra. music21 (BSD-3) is a core dependency; LilyPond (GPL) is
only run as a command. Sounds and their licences are listed in `sounds/LICENCES.md`.
