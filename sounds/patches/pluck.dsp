// Karplus-Strong pluck for stemma's Faust backend (MIT licence).
// stemma sets the standard freq, gain and gate controls for each note.
import("stdfaust.lib");

freq = hslider("freq", 220, 20, 4000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");

excite = no.noise * en.ar(0.001, 0.008, gate);
string = pm.ks(pm.f2l(freq), 0.15, excite);
process = string * gain * en.asr(0.001, 1, 0.25, gate) * 0.5 <: _, _;
