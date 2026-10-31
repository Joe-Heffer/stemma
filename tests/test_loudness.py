import numpy as np
import pytest

from stemma.analyse import analyse_audio, diff_reports
from stemma.loudness import block_loudness, loudness_stats
from stemma.master import integrated_lufs

SR = 48000


def tone(seconds, amp, freq=1000):
    t = np.arange(int(SR * seconds)) / SR
    x = amp * np.sin(2 * np.pi * freq * t)
    return np.stack([x, x], axis=1)


def test_short_term_matches_integrated_for_steady_tone():
    x = tone(10, 0.1)
    _, st = block_loudness(x, SR, 3.0)
    assert np.median(st) == pytest.approx(integrated_lufs(x, SR), abs=0.2)


def test_loudness_range():
    assert loudness_stats(tone(12, 0.1), SR)["loudness_range_lu"] == pytest.approx(0, abs=0.2)
    stepped = np.concatenate([tone(15, 0.1), tone(15, 0.1 * 10 ** (-10 / 20))])
    stats = loudness_stats(stepped, SR)
    assert stats["loudness_range_lu"] == pytest.approx(10, abs=0.5)
    assert stats["momentary_lufs_max"] >= stats["short_term_lufs_max"] - 0.1
    assert loudness_stats(tone(1, 0.1), SR)["loudness_range_lu"] is None


def test_plr_and_low_end_correlation():
    m = analyse_audio(tone(5, 0.5, 60), SR, full=False)
    assert m["plr_db"] == pytest.approx(m["true_peak_dbtp"] - m["lufs_integrated"], abs=0.01)
    assert m["low_end_correlation"] == pytest.approx(1.0, abs=1e-3)
    x = tone(5, 0.5, 60)
    x[:, 1] *= -1
    assert analyse_audio(x, SR, full=False)["low_end_correlation"] < -0.99


def test_diff_reports():
    old = {"master": {"lufs_integrated": -14.0, "bands_db": {"sub": -4.0}},
           "stems": {"bass": {"lufs_integrated": -20, "octave_bands_db": {"63": -3}}},
           "warnings": ["a", "b"]}
    new = {"master": {"lufs_integrated": -14.02, "bands_db": {"sub": -5.5}},
           "stems": {"bass": {"lufs_integrated": -22, "octave_bands_db": {"63": -9}}},
           "warnings": ["b", "c"]}
    d = diff_reports(old, new)
    assert d["changed"] == {"master.bands_db.sub": {"old": -4.0, "new": -5.5, "diff": -1.5},
                            "stems.bass.lufs_integrated": {"old": -20, "new": -22, "diff": -2}}
    assert d["warnings_added"] == ["c"] and d["warnings_removed"] == ["a"]
