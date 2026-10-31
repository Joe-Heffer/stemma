---
name: stemma-master
description: Master a stemma track and run the final checks before calling it finished, covering the loudness target for the destination, master.fx, limiter gain reduction, PLR, loudness range, low-end correlation, per-section figures, optional comparison with a reference, and sheet music. Use when asked to master, finalise, export or deliver a track, change its loudness target or output formats, or when master warnings appear.
---

# Master and finish a track

Mastering in stemma is the `master` block of `track.yaml`. It gains the mix
to `master.lufs`, applies `master.fx`, and limits true peaks to
`master.true_peak`. Parameters are in `docs/mixing.md` under “Mastering”.

Fix problems in the mix first (the `stemma-mix-revision` skill). The master
should need little work: if the limiter is busy, the mix has a peak problem.

## 1. Set the target

| Destination | `master.lufs` | `true_peak` |
|-------------|---------------|-------------|
| Streaming (default) | −14 | −1 |
| Apple Music, podcasts | −16 | −1 |
| Broadcast, EBU R128 | −23 | −1 |
| Game audio, background loops | −16 to −20, agree with the user | −1 |
| Loud club master | −9 to −7 (expect heavy limiting) | −1 |

Formats: `formats: [wav, flac]` by default; add `mp3` or `ogg` when the
destination needs them. `bit_depth: 16` adds dither (for CD-style delivery).
`tail_seconds` must cover reverb and release tails; `fade_out_seconds` shapes
the very end.

## 2. Run and read

```sh
uv run stemma all <slug> | jq '{master_report: .master,
  master: .analysis.master | {lufs_integrated, true_peak_dbtp, crest_factor_db, plr_db,
    loudness_range_lu, short_term_lufs_max, low_end_correlation, correlation,
    stereo_width_above_300hz, bands_db, spectral_centroid_hz, tempo_bpm, key_tonal, limiter},
  sections: .analysis.sections, warnings: .analysis.warnings}'
```

Check each against CLAUDE.md’s table:

* `lufs_integrated` within 0.1–0.5 LU of the target. If not, read
  `master_report.gain_db` and the limiter figures: either `normalise` is
  false or the mix is too peaky to reach the target.
* `true_peak_dbtp` at or below the ceiling.
* `limiter.mean_db` under 1–2 dB and `max_db` under 6 dB; a `limiter:`
  warning means fix the peaks in the mix (find the stem with the highest
  `crest_factor_db`, usually kick or snare, and compress or lower it), or
  lower `master.lufs`.
* `plr_db` 8–13 at −14 LUFS; under 8 is over-limited.
* `crest_factor_db` 8–14 for a punchy master; under 6 sounds squashed.
* `loudness_range_lu` 3–8 for pop and electronic, more for acoustic or film.
  Under 2–3 on a long track means the arrangement is flat: go back to
  automation.
* `low_end_correlation` near 1 (warning under 0.8).
* `sections`: loudness and centroid should rise and fall with the
  arrangement described in the spec.
* `tempo_bpm` and `key_tonal` match the spec (half or double tempo and the
  relative key are accepted).

## 3. Whole-mix corrections only

Add `master.fx` only for problems that belong to the whole stereo file, one
at a time, re-running after each:

* stereo low end: `{type: stereo_width, mono_below_hz: 120}`;
* dull or harsh overall: a `highshelf` or `lowshelf` of 1–2 dB, not more;
* a touch of glue: `compressor` 1.5:1, high threshold, 30 ms attack.

If more than 2 dB of EQ seems needed, fix the parts.

## 4. Optional: compare with a reference

Only if `ELEVENLABS_API_KEY` is set and the user accepts the credit cost
(roughly 900 credits per minute), or with a file the user supplies:

```sh
uv run stemma reference <slug> --seconds 30
uv run stemma reference <slug> --file path/to/reference.flac   # no API call
```

Read `compare` (master minus reference per band, centroid, width above
300 Hz, crest factor, tempo) as a direction to move in, not a target. A
reference is cached by request; do not pass `--force` without reason. It is
never mixed into the track.

## 5. Score, if wanted

```sh
uv run stemma score <slug>
```

Act on `warnings`: `off_grid` notes mean `score.grid` is too coarse for that
part. PDF needs LilyPond; otherwise the `.ly` file is ready to compile.
`renders/score/` is build output: do not commit it.

## 6. Finish

* `stemma all <slug>` runs clean: no warnings, or each one explained in
  `notes.md`.
* Record the final figures with the `stemma-revision-log` skill.
* Tell the user where the files are (`tracks/<slug>/renders/master.wav`,
  `master.flac`, …) and that renders are not committed, so they rebuild with
  `make all TRACK=<slug>`.
