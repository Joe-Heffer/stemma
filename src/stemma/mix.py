"""Sum stems into a stereo mixdown: per-part fx, gain, pan, buses and sends."""

from __future__ import annotations

import json

import numpy as np
import soundfile as sf

from . import dsp
from .errors import StemmaError
from .fx import apply_chain, choose_engine
from .paths import post_mix_dir, render_root, stems_dir
from .spec import Spec


def load_stem(path, sr: int) -> np.ndarray:
    audio, file_sr = sf.read(str(path), dtype="float64", always_2d=True)
    if file_sr != sr:
        raise StemmaError(f"{path} is {file_sr} Hz but the spec says {sr} Hz; re-render it")
    return audio


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    return x[:n] if len(x) >= n else np.pad(x, ((0, n - len(x)), (0, 0)))


def _sidechain(spec: Spec, sc: dict | None, sdir, n: int) -> np.ndarray | None:
    """Gain curve keyed from another part's raw stem, or None."""
    if not sc:
        return None
    wav = sdir / f"{sc['source']}.wav"
    if not wav.is_file():
        if spec.part(sc["source"]).get("optional"):
            return None
        raise StemmaError(f"sidechain source stem {wav} missing; render it first")
    trigger = _fit(load_stem(wav, spec.sample_rate), n)
    return dsp.duck_gain(trigger, spec.sample_rate, sc.get("depth_db", 6),
                         sc.get("threshold_db", -30), sc.get("ratio", 4),
                         sc.get("attack_ms", 5), sc.get("release_ms", 150),
                         sc.get("filter_hz"))


def automation_curve(spec: Spec, kind: str, name: str, section: str | None,
                     n: int) -> np.ndarray | None:
    """Per-sample linear gain from ``automation`` for one part or bus, or None.

    Built on the whole-track timeline, then sliced, so a section render hears
    the same levels as the full render.
    """
    entries = {a["section"]: a for a in spec.automation if a.get(kind) == name}
    if not entries:
        return None
    sr = spec.sample_rate
    total = int((spec.duration + spec.master["tail_seconds"]) * sr)
    g = np.ones(max(total, 1))
    prev = 1.0
    for i, sec in enumerate(spec.sections):
        a = entries.get(sec.name, {})
        amp = 0.0 if a.get("mute") else dsp.db_to_amp(a.get("gain_db", 0))
        s0, s1 = spec.section_span(sec.name)
        i0 = int(s0 * sr)
        i1 = total if i == len(spec.sections) - 1 else int(s1 * sr)
        r = min(int(a.get("ramp_beats", 0) * spec.seconds_per_beat * sr), i1 - i0)
        if r > 0:
            if prev > 0 and amp > 0:  # linear in dB
                ramp = np.geomspace(prev, amp, r)
            else:
                ramp = np.linspace(prev, amp, r)
            g[i0:i0 + r] = ramp
        g[i0 + r:i1] = amp
        prev = amp
    start = int(spec.section_span(section)[0] * sr)
    g = g[start:start + n]
    return np.pad(g, (0, n - len(g)), mode="edge") if len(g) < n else g


def mix(spec: Spec, section: str | None = None) -> dict:
    sr, tempo = spec.sample_rate, spec.tempo
    engine = choose_engine(spec.mix.get("engine", "auto"))
    start, end = spec.section_span(section)
    n = int(((end - start) + spec.master["tail_seconds"]) * sr)
    sdir = stems_dir(spec.dir, section)
    soloed = [p["name"] for p in spec.parts if p.get("mix", {}).get("solo")]
    buses = {b["name"]: np.zeros((n, 2)) for b in spec.buses}
    main = np.zeros((n, 2))
    report = {"engine": engine, "parts": [], "buses": []}
    post = post_mix_dir(spec.dir, section)
    post.mkdir(parents=True, exist_ok=True)
    for old in post.glob("*.wav"):
        old.unlink()
    for part in spec.parts:
        m = part.get("mix", {})
        name = part["name"]
        if m.get("mute") or (soloed and name not in soloed):
            report["parts"].append({"part": name, "status": "muted"})
            continue
        wav = sdir / f"{name}.wav"
        if not wav.is_file():
            if part.get("optional"):
                report["parts"].append({"part": name, "status": "skipped (no stem)"})
                continue
            raise StemmaError(f"stem {wav} missing; run `stemma render {spec.slug}"
                              + (f" --section {section}" if section else "") + "`")
        x = _fit(load_stem(wav, sr), n)
        meter: list = []
        x = apply_chain(x, m.get("fx", []), sr, tempo, engine, spec.resolve, meter)
        duck = _sidechain(spec, m.get("sidechain"), sdir, n)
        if duck is not None:
            x = x * duck[:, None]
        x = x * dsp.db_to_amp(m.get("gain_db", 0))
        auto = automation_curve(spec, "part", name, section, n)
        if auto is not None:
            x = x * auto[:, None]
        x = _fit(dsp.pan_stereo(x, m.get("pan", 0), m.get("width", 1)), n)
        # Post-fader stem, as heard in the mix, for analysis.
        sf.write(str(post / f"{name}.wav"), x.astype(np.float32), sr, subtype="FLOAT")
        dest = m.get("bus", "master")
        (main if dest == "master" else buses[dest])[:] += x
        for bus, level in m.get("sends", {}).items():
            buses[bus] += x * dsp.db_to_amp(level)
        entry = {"part": name, "status": "mixed", "bus": dest,
                 "peak_dbfs": round(dsp.amp_to_db(np.abs(x).max()), 2)}
        if meter:
            entry["dynamics"] = meter
        if auto is not None:
            entry["automation"] = sorted({a["section"] for a in spec.automation
                                          if a.get("part") == name})
        if duck is not None:
            duck_db = -20 * np.log10(np.maximum(duck, 1e-9))
            entry["sidechain"] = {"source": m["sidechain"]["source"],
                                  "max_duck_db": round(float(duck_db.max()), 1),
                                  "percent_ducked_over_1db":
                                      round(float(np.mean(duck_db > 1) * 100), 1)}
        elif m.get("sidechain"):
            entry["sidechain"] = {"source": m["sidechain"]["source"],
                                  "status": "skipped (no trigger stem)"}
        report["parts"].append(entry)
    for b in spec.buses:
        meter = []
        x = apply_chain(buses[b["name"]], b.get("fx", []), sr, tempo, engine, spec.resolve,
                        meter)
        x = _fit(dsp.pan_stereo(x, b.get("pan", 0)) if b.get("pan") else x, n)
        auto = automation_curve(spec, "bus", b["name"], section, n)
        if auto is not None:
            x = x * auto[:, None]
        main += x * dsp.db_to_amp(b.get("gain_db", 0))
        entry = {"bus": b["name"], "peak_dbfs": round(dsp.amp_to_db(np.abs(x).max()), 2)}
        if meter:
            entry["dynamics"] = meter
        report["buses"].append(entry)
    meter = []
    main = apply_chain(main, spec.mix.get("fx", []), sr, tempo, engine, spec.resolve, meter)
    if meter:
        report["mix_bus_dynamics"] = meter
    main = _fit(main * dsp.db_to_amp(spec.mix.get("gain_db", 0)), n)
    if main.shape[1] == 1:
        main = np.repeat(main, 2, axis=1)
    peak = float(np.abs(main).max())
    if peak == 0:
        raise StemmaError("the mix is silent; check mutes, solos and stems")
    out = render_root(spec.dir, section) / "mix.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), main.astype(np.float32), sr, subtype="FLOAT")
    report["mix"] = str(out.relative_to(spec.dir))
    report["peak_dbfs"] = round(dsp.amp_to_db(peak), 2)
    if peak > 1:
        report["note"] = "mix peaks above 0 dBFS (stored as float, so not clipped); "\
                         "mastering will bring it down, but consider lowering part gains"
    (out.parent / "mix.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
