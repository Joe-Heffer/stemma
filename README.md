# stemma

Command-line tooling that lets an AI agent such as Claude Code produce music
tracks and sounds from a written brief, with no DAW and no GUI.

* Everything runs headlessly and reproducibly: `make all TRACK=<slug>`.
* Text is the source of truth. A track is a YAML spec, Python part generators,
  MIDI and patch sources. Rendered audio is a gitignored build artefact.
* Open formats throughout: YAML validated by JSON Schema, Standard MIDI Files,
  SF2/SF3, SFZ, Csound and Faust source, WAV and FLAC.
* `stemma analyse` turns audio into JSON (loudness, true peak, spectral
  balance, tempo, key, stereo width, clipping) so an agent can "hear" its work
  and iterate.

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
| `stemma render <slug> [--part P] [--section S] [--force]` | Render stems; unchanged parts come from the cache |
| `stemma mix <slug> [--section S]` | Per-part fx, gain, pan, buses and sends into `renders/mix.wav` |
| `stemma master <slug> [--section S]` | Loudness-normalise and true-peak limit to WAV and FLAC |
| `stemma analyse <slug> [--section S] [--stem P]` | Measurements per stem, mix and master, plus warnings |
| `stemma analyse --file X.wav` | Analyse any audio file |
| `stemma all <slug> [--section S]` | The whole chain |
| `stemma doctor` | Which external tools, soundfonts and engines are available |
| `stemma sounds list` / `fetch [NAME]` | Shared sounds from `sounds/manifest.yaml` |

`--section` renders, mixes and masters just one section into
`renders/sections/<name>/`, which keeps iteration fast.

The Makefile wraps these: `make render TRACK=example-sketch ARGS="--part lead"`.

## Repository layout

```
CLAUDE.md                 instructions for agents working in this repo
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

### Effects

`gain`, `highpass`, `lowpass`, `peak`, `lowshelf`, `highshelf`, `compressor`,
`limiter`, `reverb`, `delay` (in `beats` or `seconds`), `distortion` and
`chorus`, on parts, buses or the mix bus. With Pedalboard installed
(`mix.engine: auto`) they run through Pedalboard; otherwise through stemma's
scipy implementations. The engine used is recorded in `renders/mix.json`;
pin it with `mix.engine` when you need renders to match across machines.

## Licences

stemma is MIT licensed. Copyleft tools are only ever run as separate
commands, never linked: FluidSynth and Csound (LGPL), the Faust compiler (GPL;
its generated code is not), SoX and ffmpeg. Pedalboard (GPL-3.0) is an
optional extra. Sounds and their licences are listed in `sounds/LICENCES.md`.
