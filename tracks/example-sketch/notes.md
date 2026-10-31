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
