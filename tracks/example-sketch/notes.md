# Example Sketch

## Brief

A 30-second synth-pop loop to prove the toolchain end to end: drums, bass and a
lead, with an optional warm pad. Bright but not harsh, driving at 120 bpm, in A
minor. Short intro, a groove that repeats once with more energy, a fill, and an
outro that thins out and lands on A.

## Decisions

* Form: intro 4 bars, groove 8, outro 4 (32 s plus a 2 s tail).
* Harmony: i–VI–III–VII (Am F C G), one chord per bar, through every section.
* Bass: syncopated root and fifth with an octave pop, E1–A2, roots chosen by
  nearest octave so the line moves smoothly.
* Lead: two-bar call over Am–F, answered over C–G; the second answer climbs to
  G5 to lift into the outro. Range G4–G5.
* Pad (optional, FluidSynth GM program 89): three-voice chords with common
  tones held, highpassed at 220 Hz so it stays out of the bass.
* Drums on a compressed bus; lead and pad send to a shared reverb bus.

## Revision log

| Rev | Change | Why (analysis) |
|-----|--------|----------------|
| 1 | First full arrangement and mix | Master −14.06 LUFS, −1.04 dBTP, 0 clips, tempo 119.7. Warnings: `sub` −2.9 dB (target ≤ −3), width 0.013 (target ≥ 0.02), lead and pad both dominant in `low_mid`. Key read as C major (relative major, accepted). |
| 2 | Kick tuned to A1 (55 Hz, shorter decay); bass sub oscillator 0.6 → 0.15 and highpass 32 → 40 Hz; pad raised 4 dB, panned left, width 1.8, cut 4 dB at 650 Hz; lead panned right with light chorus and a bigger reverb send | Rev 1 `sub` band was −2.9 dB (target ≤ −3) and the 48 Hz kick read as a G against A minor. The bass's octave-down sub put energy at 27.5 Hz. Now `sub` −4.2 dB, width above 300 Hz 0.12 (target 0.05–0.4), no masking pairs, master −14.1 LUFS, −1.04 dBTP, crest 14.2 dB, 0 clips, tempo 119.7, key C major (relative of A minor). Rev 1's lead/pad masking warning came from the old coarse heuristic; at octave resolution the pad sits at 250 Hz and the lead at 500 Hz. |
| 3 | Bass written on a `bass_8` clef in the score; audio unchanged | `stemma score` put the bass (F1–C3) on a plain bass clef with up to four ledger lines; the octave clef reads like bass guitar notation. Score: 16 bars per part, 0 notes off the 1/16 grid, largest quantise shift 0.016 beats. |

## Ideas for next revisions

* Sidechain-style ducking of the bass under the kick (needs a new `duck` effect).
* A short breakdown before the second groove pass, so the energy lift is earned.
