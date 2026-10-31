import json

from stemma.cli import main


def test_new_then_full_chain(scratch_root, capsys):
    assert main(["new", "demo"]) == 0
    assert (scratch_root / "tracks/demo/track.yaml").is_file()
    assert main(["new", "demo"]) == 1  # refuses to overwrite
    capsys.readouterr()

    assert main(["all", "demo"]) == 0
    report = json.loads(capsys.readouterr().out)
    master = report["analysis"]["master"]
    assert abs(master["lufs_integrated"] + 14) < 0.5
    assert master["true_peak_dbtp"] <= -0.95
    assert master["clipped_samples"] == 0
    assert master["key_tonal"]  # drums excluded from this estimate
    renders = scratch_root / "tracks/demo/renders"
    assert report["analysis"]["stems"]["bass"]["measured"] == "post-mix"
    for f in ("master.wav", "master.flac", "mix.wav", "analysis.json", "stems/drums.wav",
              "post-mix/bass.wav"):
        assert (renders / f).is_file(), f

    # A second render hits the cache.
    assert main(["render", "demo", "--part", "bass"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "cached"


def test_section_render_is_short(scratch_root, capsys):
    main(["new", "demo"])
    main(["midi", "demo"])
    capsys.readouterr()
    assert main(["render", "demo", "--part", "drums", "--section", "b"]) == 0
    out = json.loads(capsys.readouterr().out)[0]
    assert out["seconds"] == 4 * 4 * 0.6 + 2  # 4 bars at 100 bpm plus the tail


def test_unknown_track(scratch_root, capsys):
    assert main(["render", "nope"]) == 1
    assert "no track" in capsys.readouterr().err
