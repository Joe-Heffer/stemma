---
name: stemma-add-sound
description: Add a sound source to stemma - a soundfont (SF2/SF3), SFZ instrument, sample, impulse response, Csound orchestra or Faust patch - with the licence check and the sounds/manifest.yaml and sounds/LICENCES.md entries the repository requires. Use when a part needs an instrument the builtin synth lacks, when using fluidsynth, sfizz, csound, faust or convolution reverb, or when asked to download or add samples.
---

# Add a sound

Every sample, soundfont, SFZ or impulse response must be freely licensed and
recorded in `sounds/LICENCES.md` (and `sounds/manifest.yaml` if shared) in the
same commit that adds or first references it.

## 1. Check the licence first

Acceptable: CC0 or public domain, MIT, BSD, CC BY, CC BY-SA (record the
attribution), GPL for patches that are code. Refuse and tell the user if
the terms are non-commercial (CC BY-NC), “free for personal use”, unclear,
missing, or the source cannot be identified. Do not use sounds ripped from
commercial products or recordings.

Record: name, kind, licence, author, source URL, whether it is committed.

## 2. Choose where it lives

| What | Where | Committed? |
|------|-------|------------|
| Large shared soundfont or sample set | `sounds/cache/` via a manifest `url`, or a system path | No; `stemma sounds fetch NAME` downloads it |
| Small shared patch (Faust, Csound, SFZ text) | `sounds/patches/` | Yes |
| Patch written for one track | `tracks/<slug>/patches/` | Yes, MIT unless its header says otherwise |
| Small freely licensed WAV sample | `sounds/samples/…` | Yes (`.gitignore` allows WAV only there) |

Do not commit WAV or FLAC anywhere else.

## 3. Manifest entry (shared sounds)

Follow the existing entries in `sounds/manifest.yaml`:

```yaml
  - name: SomeKit
    kind: sfz              # sf2, sf3, sfz, wav, ir, …
    file: SomeKit/kit.sfz  # under sounds/cache/ when fetched
    licence: CC0-1.0
    author: Name
    url: https://example.org/somekit.zip     # direct download, or omit and give system_paths
    sha256: …              # the first fetch prints it; add it
    notes: >-
      Anything a reader needs (how it was converted, what is excluded).
```

Then:

```sh
uv run stemma sounds list
uv run stemma sounds fetch SomeKit
```

If `fetch` prints “no checksum recorded”, add the printed `sha256` to the
entry. Add a row to the table in `sounds/LICENCES.md`, and update its
“Used by” column when a track starts using the sound.

## 4. Reference it from a part

Sounds resolve by manifest name, or by path relative to the track folder,
then `sounds/`.

```yaml
# FluidSynth (GM programs are 0-based: 0 piano, 33 fingered bass, 48 strings, 89 warm pad)
sound: {soundfont: FluidR3_GM, program: 48}
# drums on channel 10
sound: {soundfont: FluidR3_GM, drums: true}
# sfizz
sound: {path: patches/strings.sfz}
# Csound: stemma passes p4 frequency, p5 amplitude, p6 MIDI note, p7 velocity
sound: {path: patches/fm-bell.orc, instrument: 1, release: 1.0}
# Faust: the patch exposes freq, gain and gate
sound: {path: patches/pluck.dsp, release: 0.3}
```

Mark parts that need an external tool `optional: true` so the track still
builds where the tool is absent. Confirm with:

```sh
uv run stemma doctor
uv run stemma render <slug> --part <name> --section <section>
```

A `skipped` status with a reason means the tool or file was not found.

## 5. Impulse responses

Use with the `convolution` effect (`docs/mixing.md`):

```yaml
fx: [{type: convolution, ir: irs/hall.wav, mix: 0.3, predelay_ms: 10}]
```

`ir` is relative to the track folder or `sounds/`. An IR is a recording of
someone’s room or hardware, so the licence rules above apply in full.

## 6. Writing a patch

* Faust: start from `sounds/patches/pluck.dsp`. Keep `freq`, `gain` and
  `gate` controls; output stereo (`<: _, _`).
* Csound: start from `sounds/patches/fm-bell.orc`. stemma supplies `sr`,
  `ksmps`, `nchnls = 2` and `0dbfs = 1`; use a release envelope
  (`linsegr`) and set `sound.release` long enough for it.
* Put a one-line header with the licence in the patch file.

## 7. Commit

Sound files (or manifest entry), `LICENCES.md` row and the track change go in
one commit, recorded with the `stemma-revision-log` skill.
