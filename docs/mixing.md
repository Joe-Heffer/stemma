# Mixing and mastering reference

This is the reference for everything between rendered stems and the master:
effects, sidechain, automation, buses, the mastering chain and the figures
`analyse` reports. CLAUDE.md gives the order of work; this file gives the
parameters.

## Signal flow

```
stem ─► part fx ─► sidechain ─► fader (gain_db) ─► automation ─► pan/width ─┬─► bus ─► bus fx ─► bus pan ─► bus automation ─┐
                                                                            └─► sends (post-fader) ─► send buses ───────────┤
                                                                                                                            ▼
                                       master.wav ◄─ limiter ◄─ loudness gain ◄─ master.fx ◄─ mix.wav ◄─ mix fx ◄─ mix bus (sum)
```

* `renders/post-mix/<part>.wav` is each part after its fader, automation and
  pan: what it adds to the mix. `analyse` measures stems from here.
* `mix.json` and `master.json` record the engine, peaks, gain reduction of
  every dynamics stage, sidechain ducking and the limiter.

## Effects

Effects go in `fx` lists on parts (`parts[].mix.fx`), buses (`buses[].fx`),
the mix bus (`mix.fx`) and the master (`master.fx`). Each has `type` and may
set `bypass: true` to switch it off without deleting it. Frequencies are Hz,
levels dB, times ms unless stated.

With Pedalboard installed (`uv sync --extra fx`, `mix.engine: auto`), the
first group runs through Pedalboard; otherwise through stemma’s scipy
versions. The second group always runs through stemma’s own code.

### EQ and filters (both engines)

| Type | Parameters (default) | Use |
|------|----------------------|-----|
| `highpass` | `cutoff_hz`, `q` (0.707) | Clear low end from everything but kick and bass (100–250 Hz on leads and pads) |
| `lowpass` | `cutoff_hz`, `q` (0.707) | Darken; tame fizz on distorted parts |
| `peak` | `freq_hz`, `gain_db`, `q` (0.707) | Cut where another part lives; Q 1–2 for surgical cuts, 0.5–1 for tone |
| `lowshelf` | `freq_hz`, `gain_db`, `q` (0.707) | Thin or warm the bottom |
| `highshelf` | `freq_hz`, `gain_db`, `q` (0.707) | Air (+) or de-harsh (−) |
| `gain` | `gain_db` | Gain staging inside a chain |

### Dynamics (both engines unless noted)

| Type | Parameters (default) | Use |
|------|----------------------|-----|
| `compressor` | `threshold_db` (−18), `ratio` (4), `attack_ms` (10), `release_ms` (120), `makeup_db` (0) | Level control; slower attack lets transients through |
| `limiter` | `threshold_db` (−1), `release_ms` (60) | Catch peaks on a bus; the master has its own limiter |
| `gate` | `threshold_db` (−50), `ratio` (10), `attack_ms` (1), `release_ms` (80), `hold_ms` (0), `range_db` (40) | Remove bleed, noise or reverb tails below the threshold. stemma code on both engines |
| `transient` | `attack_db` (0), `sustain_db` (0), each −24 to 24 | Shape drums: + attack for punch, − sustain to tighten. stemma code on both engines |

Every `compressor`, `limiter` and `gate` reports `gain_reduction_db`
(`max_db`, `mean_db`, `percent_over_1db`) under `dynamics` in `mix.json`
(and `master.json` for `master.fx`). As a guide, a bus or mix-bus
compressor doing more than 3–4 dB mean is working hard; a part compressor at
0 dB is doing nothing and can go.

### Space and colour (both engines)

| Type | Parameters (default) | Use |
|------|----------------------|-----|
| `reverb` | `room_size` (0.5), `damping` (0.5), `wet` (0.33), `dry` (0.4), `width` (1.0) | On a send bus with `wet: 1, dry: 0` |
| `delay` | `beats` (0.75) or `seconds`, `feedback` (0.3), `mix` (0.25) | Tempo-synced echoes; dotted eighth is 0.75 beats |
| `chorus` | `rate_hz` (0.8), `depth` (0.25), `mix` (0.5) | Width and movement on leads and pads |
| `distortion` | `drive_db` (12) | Harmonics so a bass reads on small speakers |

### Stereo and convolution (stemma code on both engines)

| Type | Parameters (default) | Use |
|------|----------------------|-----|
| `stereo_width` | `width` (1.0, 0–2), `mono_below_hz` (none, 20–500) | Widen or narrow; `mono_below_hz: 120` folds the low end to mono with a Linkwitz–Riley crossover |
| `mid_side_eq` | `mid: [...]`, `side: [...]` (EQ effects only) | E.g. highpass the side at 200 Hz, lift side air with a high shelf |
| `convolution` | `ir` (required), `mix` (0.3), `predelay_ms` (0) | Real spaces from an impulse response. The IR is scaled to unit energy and resampled to the track rate |

`ir` is a WAV or FLAC path relative to the track folder or `sounds/`. An IR is
a recording of someone’s room or hardware: it must be freely licensed and
listed in `sounds/LICENCES.md` (and `sounds/manifest.yaml` if shared) in the
same commit. Convolution output keeps the input length, so the tail is limited
by `master.tail_seconds`.

## Sidechain ducking

```yaml
parts:
  - name: bass
    mix:
      sidechain: {source: drums, filter_hz: 120, threshold_db: -16, depth_db: 4,
                  attack_ms: 3, release_ms: 90}
```

The part is turned down while the source part’s *raw* stem is above
`threshold_db`, by `1 − 1/ratio` dB per dB over (`ratio` 4), never more than
`depth_db` (6). `filter_hz` lowpasses the trigger first, so a full drum stem
ducks only on the kick. It runs after the part’s fx and before its fader.

`mix.json` reports `max_duck_db` and `percent_ducked_over_1db`. If the part is
ducked most of the time, the threshold is too low or the release too long:
the aim is a dip on each hit, not a quieter part. Typical uses: bass under
kick (2–4 dB), pads under kick for pumping (6–10 dB, longer release), music
under a vocal.

## Automation

```yaml
automation:
  - {part: lead, section: outro, gain_db: -4, ramp_beats: 4}   # fade down over a bar
  - {part: pad, section: intro, mute: true}
  - {bus: verb, section: outro, gain_db: 3}                     # bigger space at the end
  - {part: lead, section: groove, gain_db: 0, ramp_beats: 2}    # explicit return, with a ramp
```

* One entry per part or bus per section. Sections without an entry are at
  0 dB (the fader level); the last section’s level holds through the tail.
* `ramp_beats` ramps from the previous section’s level, starting at the
  section start (in dB, or linearly in amplitude to or from a mute). Without
  an entry, a return to 0 dB is a step: add an entry with `gain_db: 0` and a
  ramp to smooth it.
* Part automation comes after the fader and before pan and sends, so sends
  follow it. Bus automation scales the bus output.
* Section renders use the same curve as the full render.

## Mastering

```yaml
master:
  lufs: -14            # integrated target
  true_peak: -1        # dBTP ceiling
  normalise: true      # false: keep the mix level, only limit
  fx:                  # before loudness gain and the limiter
    - {type: stereo_width, mono_below_hz: 120}
    - {type: mid_side_eq, side: [{type: highpass, cutoff_hz: 150}]}
    - {type: compressor, threshold_db: -12, ratio: 1.5, attack_ms: 30, release_ms: 200}
  limiter: {release_ms: 60, lookahead_ms: 4}
  formats: [wav, flac, mp3]    # wav, flac, mp3, ogg
  bit_depth: 24                # 16 adds TPDF dither
  tail_seconds: 2
  fade_out_seconds: 1
```

The master gains the mix towards `lufs` and limits true peaks to
`true_peak`, iterating until the integrated loudness is within 0.1 LU.
`master.json` (and `analyse`’s `master.limiter`) reports the limiter’s
`max_db`, `mean_db` and `percent_over_1db` of gain reduction. It warns above
6 dB max or 2 dB mean: the mix has peaks that are too loud for the target
(often an unruly kick or a transient-heavy part). Fix them in the mix, with a
part or bus compressor, or a lower `lufs`, rather than letting the limiter
flatten them.

Common loudness targets: −14 LUFS for streaming (the default), −16 for
podcasts and Apple Music’s normalisation, −23 for broadcast (EBU R128), −9
to −7 for loud club masters (expect a lot of limiting).

Keep the mix bus (`mix.fx`) for glue that belongs to the mix, and `master.fx`
for corrective work on the whole stereo file. Both are optional.

## Reading the analysis

Each `analyse` run measures stems (post-fader), the mix and the master.
Beyond the fields in CLAUDE.md’s table:

| Field | Meaning | Typical aims |
|-------|---------|--------------|
| `loudness_range_lu` | EBU R128 loudness range (spread of 3 s loudness) | 3–8 LU for pop and electronic; 8–15 for acoustic and film; under 3 sounds flat over a long track |
| `short_term_lufs_max` | loudest 3 s | 1–3 LU above the integrated level; much more means one section is far louder |
| `momentary_lufs_max` | loudest 0.4 s | |
| `plr_db` | true peak minus integrated loudness | 8–13 dB at −14 LUFS; under 8 is heavily limited |
| `low_end_correlation` | L/R correlation below 150 Hz | close to 1; warns below 0.8 on the mix and master |
| `master.limiter` | limiter gain reduction | `mean_db` under 1–2, `max_db` under 6 |
| `sections` | per section of the master: loudness, loudest 3 s, crest, centroid, width above 300 Hz | loudness and centroid should rise where the arrangement builds |
| `delta` | what changed since the last analysis with different figures | quote these in revision notes |

`delta.changed` lists every figure that moved by 0.1 or more, as
`{old, new, diff}`, for the mix, master, sections and each stem’s loudness,
crest, centroid, width and bands, plus `warnings_added` and
`warnings_removed`. `analysis.json` becomes `analysis.prev.json` only when
the figures change, so running `analyse` again without changing anything still
shows what the last change did.

## Plots

`stemma plot <slug> [--section S] [--kind spectrum spectrogram loudness]
[--stem P ...]` writes PNGs to `renders/plots/` (or the section’s folder).
Open them with the image reader.

* `spectrum.png`: third-octave spectra of the post-fader stems over the mix,
  with analyse’s band edges. Two stems with peaks at the same height in the
  same region are masking each other.
* `spectrogram.png`: the master (or mix) over time, with section markers.
  Look for frequency bands that stay lit everywhere (resonances, mud) and for
  sections that do not change.
* `loudness.png`: momentary and short-term loudness with the target and
  section markers. Builds and drops should be visible; a flat line means
  little contrast.

Plots need matplotlib (`uv sync --extra plot`; music21 usually installs it
already).
