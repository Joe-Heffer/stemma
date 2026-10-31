import numpy as np
import pytest

from stemma.analyse import analyse_audio, keys_compatible

SR = 48000


def sine(freq=1000.0, dbfs=-20.0, seconds=5.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t)


@pytest.fixture(scope="module")
def sine_report():
    return analyse_audio(sine(), SR)


def test_sine_levels(sine_report):
    m = sine_report
    assert m["sample_peak_dbfs"] == pytest.approx(-20, abs=0.05)
    assert m["true_peak_dbtp"] == pytest.approx(-20, abs=0.1)
    assert m["rms_dbfs"] == pytest.approx(-23.01, abs=0.05)  # sine RMS is peak - 3.01 dB
    assert m["crest_factor_db"] == pytest.approx(3.01, abs=0.05)
    assert m["clipped_samples"] == 0


def test_sine_loudness(sine_report):
    # A mono 1 kHz sine at -20 dBFS peak reads about -23 LUFS under BS.1770
    # (K-weighting adds ~0.7 dB at 1 kHz; one channel, no surround weighting).
    assert -24.5 < sine_report["lufs_integrated"] < -22.0


def test_sine_spectrum(sine_report):
    bands = sine_report["bands_db"]
    assert max(bands, key=bands.get) == "low_mid"
    assert bands["low_mid"] > -0.1
    assert all(v < -30 for k, v in bands.items() if k != "low_mid")
    assert sine_report["spectral_centroid_hz"] == pytest.approx(1000, rel=0.05)


def test_mono_has_no_width(sine_report):
    assert sine_report["stereo_width"] == 0.0
    s = sine()
    dual = analyse_audio(np.stack([s, s], axis=1), SR, full=False)
    assert dual["stereo_width"] == pytest.approx(0, abs=1e-6)
    assert dual["correlation"] == pytest.approx(1, abs=1e-6)


def test_out_of_phase_is_all_side():
    s = sine(seconds=1)
    m = analyse_audio(np.stack([s, -s], axis=1), SR, full=False)
    assert m["stereo_width"] == pytest.approx(1, abs=1e-6)
    assert m["correlation"] == pytest.approx(-1, abs=1e-6)


def test_clipping_is_counted():
    s = np.clip(sine(dbfs=6, seconds=1), -1, 1)
    m = analyse_audio(s, SR, full=False)
    assert m["clipped_samples"] > 1000
    assert m["sample_peak_dbfs"] == pytest.approx(0, abs=0.01)


def test_inter_sample_peak_exceeds_sample_peak():
    # A sine at fs/4 phased so samples land at +-0.707 of the true peak.
    t = np.arange(SR) / SR
    s = 0.9 * np.sin(2 * np.pi * SR / 4 * t + np.pi / 4)
    m = analyse_audio(s, SR, full=False)
    assert m["true_peak_dbtp"] - m["sample_peak_dbfs"] > 2.5


def test_silence():
    m = analyse_audio(np.zeros(SR), SR)
    assert m["silent"] and m["lufs_integrated"] is None


def test_key_of_a_minor_triad_arpeggio():
    notes = [57, 60, 64, 69, 64, 60] * 4  # A3 C4 E4 A4 ...
    y = np.concatenate([sine(440 * 2 ** ((n - 69) / 12), -12, 0.5) for n in notes])
    m = analyse_audio(y, SR)
    assert keys_compatible(m["key"], "A minor"), m["key"]


def test_tempo_of_click_track():
    y = np.zeros(SR * 8)
    for i in range(0, len(y), SR // 2):  # 120 bpm
        y[i:i + 200] = np.hanning(200)
    m = analyse_audio(y, SR)
    assert m["tempo_bpm"] == pytest.approx(120, rel=0.03)


def test_keys_compatible():
    assert keys_compatible("C major", "A minor")
    assert keys_compatible("A major", "A minor")
    assert not keys_compatible("G major", "A minor")
