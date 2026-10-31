---
name: stemma-generated-parts
description: Add or revise a stemma part whose audio comes from the ElevenLabs Music API (source elevenlabs) - writing sound.prompt, controlling credit cost and caching, lining the audio up with bar 1, and checking tempo and key. Use when a track needs a texture, pad, comping or acoustic-sounding part that MIDI synthesis cannot give, or when a generated part drifts or clashes.
---

# Generated parts (ElevenLabs)

A part with `source: elevenlabs` has no generator. stemma asks the
ElevenLabs Music API for that one instrument on its own, over the whole
track, and slices it per section. The audio then goes through `mix`,
`master` and `analyse` like any stem. `midi` and `score` skip it.

## Before you start

* Ask the user before the first generation: it costs credits (roughly 900
  per minute of audio at the time of writing). Say how long the track is.
* `ELEVENLABS_API_KEY` must be set (`stemma doctor` reports it).
* Record in `tracks/<slug>/notes.md` the ElevenLabs plan and the date. The
  free tier does not allow commercial use. If the plan is unknown, ask.
* Suitable: textures, pads, comping, ambience, acoustic colour. Not
  suitable: drums and bass, or anything that must lock to the grid. Keep
  those as MIDI parts.

## 1. Add the part

```yaml
parts:
  - name: keys
    role: harmony
    source: elevenlabs
    optional: true            # the track still builds without the API key
    sound:
      prompt: "warm Rhodes electric piano comping on the chords, sparse in the intro"
      offset_seconds: 0.0
    mix: {gain_db: -8, pan: 0.2, fx: [{type: highpass, cutoff_hz: 150}]}
```

Always set `optional: true`.

## 2. Write the prompt

stemma adds the title, tempo, key, metre, the sections with their
descriptions, and the `## Brief` from `notes.md`. The prompt describes only
this instrument:

* the instrument and its tone (“nylon-string guitar, close-miked, soft”);
* what it plays (“arpeggiates the chords in eighths”, “long sustained
  chords”, “answers the lead with short phrases”);
* how it changes across sections, using the section names from the spec
  (“silent in the intro, enters at the groove, thins in the outro”).

Do not name other instruments it should play with, artists or real songs.
One instrument per part: for two textures, make two parts.

## 3. Generate and render

```sh
uv run stemma render <slug> --part keys
```

* The audio is cached in `tracks/<slug>/generated/` by request. Changing
  the prompt, tempo, key, form or brief makes a new request and costs
  credits again. Plan prompt edits carefully.
* `--section` renders cost nothing extra once the full track exists.
* `--force` re-slices stems from the cached audio (free).
  `--force-generate` calls the API again (costs credits). Use it only when
  the user agrees.
* `make clean` keeps `generated/`. Never commit `generated/`.

## 4. Check alignment, tempo and key

```sh
uv run stemma all <slug> | jq '{warnings: .analysis.warnings,
  keys: .analysis.stems.keys | {tempo_bpm, lufs_integrated, bands_db},
  key_tonal: .analysis.master.key_tonal}'
```

* A warning `keys: generated audio runs at about N bpm, not T` means it will
  drift against the MIDI parts. Reword the prompt (state the feel plainly,
  “steady, strictly in time”) and regenerate with the user’s agreement, or
  drop the part.
* Line up the first downbeat with bar 1 using `sound.offset_seconds`:
  positive trims that many seconds from the start, negative delays the
  audio. Find the offset with `stemma plot <slug> --kind spectrogram`, or by
  comparing the stem’s first onset with the kick’s. Re-render with
  `--force` (free).
* Compare `key_tonal` with the spec. A part in the wrong key cannot be
  fixed by mixing: change the prompt or remove the part.

## 5. Mix it

Treat it like any supporting part (the `stemma-mix-revision` skill):
highpass it, cut where it masks the lead, pan it, send it to the reverb bus.
Generated audio is often full-range and loud, so start the fader low.

## 6. Record

The revision log row records the prompt change and why. Keep the plan and
date line in `notes.md` current.
