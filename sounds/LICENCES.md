# Sound licences

Every sample, soundfont, SFZ instrument or impulse response used by stemma must
be listed here before it is committed or referenced from a track. Prefer
public-domain (CC0), MIT, CC BY or similarly permissive licences. Do not add
sounds with "non-commercial" or unclear terms.

| Name | Kind | Licence | Author / source | Committed? | Used by |
|------|------|---------|-----------------|------------|---------|
| FluidR3_GM | SF2 | MIT | Frank Wen and contributors; `fluid-soundfont-gm` package | No (system path) | `tracks/example-sketch` (optional pad) |
| FluidR3Mono_GM | SF3 | MIT | Frank Wen; MuseScore conversion | No (fetched to `sounds/cache/`) | none yet |
| builtin presets | Synthesis code | MIT (this repo) | `src/stemma/render/builtin.py` | Yes | all example parts |

Reference audio from `stemma reference` (generated with ElevenLabs or
supplied with `--file`) is not a sound in this sense. It stays in the
gitignored `renders/reference/`, is only measured, and must never be used by a
track, so it is not listed here.

Patches written for a track (Faust `.dsp`, Csound `.orc`, SFZ text) live in
`tracks/<slug>/patches/` and are covered by the repository's MIT licence unless
their header says otherwise.
