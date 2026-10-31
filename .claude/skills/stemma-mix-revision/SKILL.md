---
name: stemma-mix-revision
description: Make one analysis-driven change to a stemma track's mix (gain, EQ, compression, sidechain, panning, reverb sends, automation) and confirm it with stemma analyse and its delta. Use when a track sounds muddy, harsh, narrow, flat, masked or unbalanced, when analyse reports warnings or masking, or when asked to improve, balance or fix the mix.
---

# One mix revision

A revision is one change, measured before and after. Never change several
parts and the mix bus at once: the `delta` will not tell you which change did
what.

Effect parameters, sidechain, automation and buses are in `docs/mixing.md`.
The stage order (gain, subtractive EQ, dynamics, sidechain, space,
automation, mix bus, master) is in CLAUDE.md. Work on the earliest stage that
has a problem.

## 1. Get a baseline

If the track has not been analysed since its last change:

```sh
uv run stemma all <slug> --section <section>     # or the whole track
```

Work on the section where the problem is loudest, for speed. A section
render goes to `renders/sections/<name>/`, with its own analysis and delta.

Read the compact view:

```sh
uv run stemma analyse <slug> --section <section> | jq '{warnings, masking,
  mix: .mix | {peak: .sample_peak_dbfs, lufs_integrated, crest_factor_db, bands_db,
    spectral_centroid_hz, stereo_width_above_300hz, low_end_correlation},
  stems: .stems | map_values({lufs_integrated, crest_factor_db, bands_db,
    spectral_centroid_hz, stereo_width}),
  delta}'
```

Then read `renders/mix.json` (`renders/sections/<name>/mix.json` for a
section): each part’s `peak_dbfs`,
every `dynamics[].gain_reduction_db` and `sidechain` figures, and the buses’
dynamics.

## 2. Diagnose

Read `warnings` first. Then compare stems with each other, not with fixed
numbers: `octave_bands_db` shows who owns each octave; `masking` lists
octaves where two stems are both near their peak and within 6 dB.

| Symptom in the report | Likely cause | First fix |
|-----------------------|--------------|-----------|
| `possible masking: A and B … N Hz octave` | two parts in one register | move one part’s register (generator), else `peak` cut on the less important part at that octave, else pan apart. Kick and bass sharing 63 Hz is normal: tune the kick and sidechain the bass |
| mix `sub` or `low` high, crest falling | low-end build-up | highpass non-bass parts (100–250 Hz on leads and pads); lower the bass preset `sub`; `lowshelf` cut on the bass |
| `low_mid` heavy, centroid low | mud at 250–500 Hz | `peak` −2 to −4 dB around 300 Hz on bass or pads, Q ≈ 1 |
| `high_mid` high, centroid climbing | harshness | lower the lead’s `cutoff`, `peak` cut 2–5 kHz on the offender, lower hat velocities |
| `stereo_width_above_300hz` under 0.05 | too narrow | pan supporting parts ±0.1–0.4, `width` 1.5–1.8 on pads, send to a reverb bus |
| `low-end correlation … below 0.8` | something stereo under 150 Hz | narrow or highpass the wide part; keep kick and bass at `pan: 0`; last resort `stereo_width` with `mono_below_hz: 120` |
| `negative L/R correlation` | phase-inverted or very wide part | reduce `width` or chorus `mix`, check stereo spread |
| `N clipped samples`, or `mix.peak_dbfs` above 0 | faders too high | lower `gain_db` on the loudest parts |
| part compressor `mean_db` 0 | compressor doing nothing | raise ratio, lower threshold, or remove it |
| bus compressor `mean_db` above 3–4 | over-compression | raise the threshold |
| stem crest factor much higher than others, limiter working | transient-heavy part | compressor with slower attack, or `transient` with `attack_db` negative |
| sidechain `percent_ducked_over_1db` high (over ~30) | ducking the whole part | raise `threshold_db`, shorten `release_ms`, set `filter_hz: 120` |
| `sections` loudness within 1 LU everywhere | flat arrangement | `automation` per section; thin the intro; add density in the peak (generator change) |
| `estimated tempo … vs spec` | weak transients, or a generated part drifting | check `stems.*.tempo_bpm`; for an ElevenLabs part see `stemma-generated-parts` |
| `estimated key … vs spec` | wrong notes, or a detuned kick | check `key_tonal`; relative major/minor is accepted; listen for a kick not tuned to the key |
| `… outside […]` (a `targets` range) | measured figure out of the spec’s range | fix the cause above, or widen the target if the brief justifies it, and say so |

When the numbers point at a problem you cannot place:

```sh
uv run stemma plot <slug> [--section S] [--kind spectrum spectrogram loudness]
```

Open the PNGs in `renders/plots/` with the Read tool. Spectrum: two stems
peaking at the same height in one region mask each other. Spectrogram: a
band lit everywhere is a resonance or mud; sections that look the same
sound the same. Loudness: a flat line means no contrast.

## 3. Change one thing

Write down, before editing, what you expect to move and by roughly how much
(“bass `low_mid` −13 dB → about −15; mix centroid up slightly”).

Edit `track.yaml` (fx, gains, sends, sidechain, automation) or one
generator. Then re-run only what the change affects:

* mix-only change (fx, gain, pan, sends, sidechain, automation, buses):
  `uv run stemma mix <slug> --section S`, then `master` and `analyse` with the
  same `--section`. `stemma all <slug> --section S` does all of it and the
  stems come from the cache.
* sound or notes change: `uv run stemma render <slug> --part P --section S`
  first, or just `stemma all <slug> --section S`.

## 4. Check the delta

```sh
uv run stemma analyse <slug> --section <section> | jq .delta
```

`delta.changed` lists every figure that moved by 0.1 or more as
`{old, new, diff}`, keyed like `stems.bass.bands_db.low_mid` or
`sections.groove.lufs_integrated`. Check:

* the figure you aimed at moved in the right direction, by about the amount
  you expected;
* nothing else moved unexpectedly (a cut on the bass should not raise the
  lead’s loudness);
* `warnings_added` is empty, or each new warning is explained.

If the change did not help, revert it before trying another. If it helped,
run `stemma all <slug>` for the whole track once the section works.

## 5. Record

Use the `stemma-revision-log` skill. In the reply to the user, quote the
figures, for example: “bass `low_mid` was −13.1 dB and masked the pad in the
250 Hz octave; cut 3 dB at 300 Hz on the bass, now −15.4 dB and the masking
pair has gone.”
