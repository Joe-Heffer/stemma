import copy
from pathlib import Path

import pytest

from stemma.errors import StemmaError
from stemma.spec import Spec, load, validate


def test_example_is_valid(example_spec_data):
    assert validate(example_spec_data) == []


def test_template_is_valid():
    from importlib import resources

    import yaml

    text = resources.files("stemma").joinpath("templates/track/track.yaml").read_text()
    assert validate(yaml.safe_load(text.replace("{{title}}", "T"))) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d.pop("tempo"), "'tempo' is a required property"),
        (lambda d: d["parts"][0].setdefault("mix", {}).update(pan=2), "$.parts[0].mix.pan"),
        (lambda d: d["parts"][0].update(source="logic-pro"), "$.parts[0].source"),
        (lambda d: d.update(key="H minor"), "$.key"),
        (lambda d: d["sections"][0].update(bars=0), "$.sections[0].bars"),
        (lambda d: d.update(time_signature=[4, 3]), "$.time_signature[1]"),
        (lambda d: d["parts"].append(copy.deepcopy(d["parts"][0])), "duplicate names"),
        (lambda d: d["parts"][0]["mix"].update(bus="nowhere"), "unknown bus 'nowhere'"),
        (lambda d: d["parts"][1]["mix"]["fx"].append({"type": "highpass"}), "cutoff_hz"),
        (lambda d: d.update(colour="blue"), "Additional properties"),
        (lambda d: d["parts"].append({"name": "x", "source": "csound"}), "sound.path"),
    ],
)
def test_invalid_specs_report_a_path(example_spec_data, mutate, expected):
    mutate(example_spec_data)
    errors = validate(example_spec_data)
    assert errors, "expected validation to fail"
    assert any(expected in e for e in errors), errors


def test_timing(example_spec_data, tmp_path):
    spec = Spec(example_spec_data, tmp_path / "example-sketch")
    assert spec.total_bars == 16
    assert spec.duration == pytest.approx(32.0)
    assert spec.section_span("groove") == pytest.approx((8.0, 24.0))
    assert spec.master["lufs"] == -14 and spec.master["true_peak"] == -1


def test_six_eight_bar_is_three_beats(example_spec_data, tmp_path):
    example_spec_data["time_signature"] = [6, 8]
    assert Spec(example_spec_data, tmp_path).beats_per_bar == 3


def test_load_reports_validation_errors(tmp_path):
    (tmp_path / "track.yaml").write_text("title: x\n")
    with pytest.raises(StemmaError, match="failed validation"):
        load(tmp_path)


def test_every_effect_is_documented():
    from stemma.spec import schema

    doc = (Path(__file__).parent.parent / "docs/mixing.md").read_text()
    types = schema()["$defs"]["fx"]["properties"]["type"]["enum"]
    missing = [t for t in types if f"| `{t}` |" not in doc]
    assert not missing, f"add {missing} to docs/mixing.md"
