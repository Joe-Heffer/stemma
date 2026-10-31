; FM bell for stemma's Csound backend (MIT licence).
; stemma supplies sr, ksmps, nchnls = 2 and 0dbfs = 1.
; p4 = frequency (Hz), p5 = amplitude 0..1, p6 = MIDI note, p7 = velocity.

instr 1
  iamp  = p5 * 0.3
  kenv  linsegr 0, 0.005, 1, 1.5, 0.3, 0.6, 0
  kidx  linsegr 4, 0.8, 1, 0.6, 0.5
  asig  foscili iamp * kenv, p4, 1, 1.4, kidx
  outs  asig, asig
endin
