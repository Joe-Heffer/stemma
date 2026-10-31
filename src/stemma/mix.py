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
        x = apply_chain(x, m.get("fx", []), sr, tempo, engine)
        x = x * dsp.db_to_amp(m.get("gain_db", 0))
        x = _fit(dsp.pan_stereo(x, m.get("pan", 0), m.get("width", 1)), n)
        # Post-fader stem, as heard in the mix, for analysis.
        sf.write(str(post / f"{name}.wav"), x.astype(np.float32), sr, subtype="FLOAT")
        dest = m.get("bus", "master")
        (main if dest == "master" else buses[dest])[:] += x
        for bus, level in m.get("sends", {}).items():
            buses[bus] += x * dsp.db_to_amp(level)
        report["parts"].append({"part": name, "status": "mixed", "bus": dest,
                                "peak_dbfs": round(dsp.amp_to_db(np.abs(x).max()), 2)})
    for b in spec.buses:
        x = apply_chain(buses[b["name"]], b.get("fx", []), sr, tempo, engine)
        x = _fit(dsp.pan_stereo(x, b.get("pan", 0)) if b.get("pan") else x, n)
        main += x * dsp.db_to_amp(b.get("gain_db", 0))
        report["buses"].append({"bus": b["name"],
                                "peak_dbfs": round(dsp.amp_to_db(np.abs(x).max()), 2)})
    main = apply_chain(main, spec.mix.get("fx", []), sr, tempo, engine)
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
