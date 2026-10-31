"""Mix effects: gate, transient shaper, stereo tools, convolution and metering."""

import numpy as np
import pytest
import soundfile as sf

from stemma import dsp
from stemma.fx import apply_chain
from stemma.spec import validate

SR = 48000


def tone(freq, seconds=1.0, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def side_share(x):
    mid, side = dsp.ms_encode(x)
    return np.sum(side**2) / (np.sum(mid**2) + np.sum(side**2))


def test_gate_silences_below_threshold():
    loud, quiet = tone(220, 0.5, 0.5), tone(220, 0.5, 0.001)
    y = dsp.gate(np.concatenate([loud, quiet]), SR, threshold_db=-40, range_db=40)
    tail = y[int(0.9 * SR):]
    assert 20 * np.log10(np.abs(tail).max() / 0.001) == pytest.approx(-40, abs=1)
    assert np.abs(y[: int(0.4 * SR)]).max() == pytest.approx(0.5, abs=0.01)


def test_transient_shaper_lifts_onsets():
    t = np.arange(SR) / SR
    hit = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 8)
    y = dsp.transient_shaper(hit, SR, attack_db=6)
    early = slice(int(0.002 * SR), int(0.01 * SR))
    assert np.abs(y[early]).max() > 1.3 * np.abs(hit[early]).max()
    z = dsp.transient_shaper(hit, SR, sustain_db=-6)
    late = slice(int(0.3 * SR), int(0.6 * SR))
    assert np.abs(z[late]).max() < 0.8 * np.abs(hit[late]).max()


def test_mono_below_removes_low_side():
    low, high = tone(50, 2), tone(2000, 2)
    x = np.stack([low + high, -low + high], axis=1)  # anti-phase lows, mono highs
    y = dsp.stereo_width(x, SR, width=1.0, mono_below_hz=150)
    lo, _ = dsp.crossover(y, 150, SR)
    _, side = dsp.ms_encode(lo[SR // 2:])
    assert np.sqrt(np.mean(side**2)) < 0.01


def test_width_zero_is_mono():
    x = np.stack([tone(300), tone(500)], axis=1)
    assert side_share(dsp.stereo_width(x, SR, width=0)) < 1e-12
    assert side_share(dsp.stereo_width(x, SR, width=2)) > side_share(x)


def test_mid_side_eq_on_mono_leaves_side_empty():
    x = tone(1000)[:, None]
    chain = [{"type": "mid_side_eq", "mid": [{"type": "peak", "freq_hz": 1000, "gain_db": 6}],
              "side": [{"type": "highshelf", "freq_hz": 5000, "gain_db": 3}]}]
    y = apply_chain(x, chain, SR, 120, "scipy")
    assert y.shape[1] == 2
    assert side_share(y) < 1e-12
    gain = np.abs(y[SR // 2:, 0]).max() / 0.5
    assert 20 * np.log10(gain) == pytest.approx(6, abs=0.3)


def test_convolution_with_unit_impulse_is_identity(tmp_path):
    ir = np.zeros(64)
    ir[0] = 1
    sf.write(str(tmp_path / "unit.wav"), ir, SR)
    x = np.stack([tone(440), tone(660)], axis=1)
    y = apply_chain(x, [{"type": "convolution", "ir": "unit.wav", "mix": 1.0}], SR, 120,
                    "scipy", resolve=lambda p: tmp_path / p)
    assert np.allclose(y, x)


def test_convolution_resamples_and_reports_missing(tmp_path):
    ir = np.exp(-np.arange(4410) / 400.0)
    sf.write(str(tmp_path / "ir.wav"), ir, 44100)
    x = tone(440)[:, None]
    y = apply_chain(x, [{"type": "convolution", "ir": "ir.wav", "mix": 0.5}], SR, 120,
                    "scipy", resolve=lambda p: tmp_path / p)
    assert y.shape == (len(x), 2)
    with pytest.raises(Exception, match="not found"):
        apply_chain(x, [{"type": "convolution", "ir": "nope.wav"}], SR, 120, "scipy",
                    resolve=lambda p: tmp_path / p)


def test_meter_reports_compressor_reduction():
    x = tone(220, 2, 0.9)[:, None]
    meter = []
    apply_chain(x, [{"type": "compressor", "threshold_db": -20, "ratio": 4}], SR, 120,
                "scipy", meter=meter)
    gr = meter[0]["gain_reduction_db"]
    assert meter[0]["type"] == "compressor"
    # Peak −0.9 dBFS is ~19 dB over: 4:1 takes off about 14 dB.
    assert gr["max_db"] == pytest.approx(14.3, abs=1.5)
    quiet = []
    apply_chain(x * 0.01, [{"type": "compressor", "threshold_db": -20}], SR, 120, "scipy",
                meter=quiet)
    assert quiet[0]["gain_reduction_db"]["max_db"] == 0


def test_limiter_returns_gain():
    x = tone(220, 1, 1.0)
    y, gain = dsp.limiter(x, SR, ceiling_db=-6, return_gain=True)
    assert gain.min() < 0.55 and len(gain) == len(x)


def test_schema_accepts_new_effects(example_spec_data):
    data = example_spec_data
    data["mix"]["fx"] = [
        {"type": "gate", "threshold_db": -50, "hold_ms": 20},
        {"type": "transient", "attack_db": 3},
        {"type": "stereo_width", "width": 1.2, "mono_below_hz": 120},
        {"type": "mid_side_eq", "side": [{"type": "highpass", "cutoff_hz": 200}]},
        {"type": "convolution", "ir": "irs/room.wav", "mix": 0.2},
    ]
    assert validate(data) == []
    data["mix"]["fx"] = [{"type": "mid_side_eq", "mid": [{"type": "reverb"}]}]
    assert validate(data)
    data["mix"]["fx"] = [{"type": "convolution"}]
    assert validate(data)
