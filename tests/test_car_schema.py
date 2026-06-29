"""Tests for the per-car setup schema (``tools/ai_sidecar/car_schema.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ai_sidecar.car_schema import CarSetupSchema, SpinnerDesc

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "assets/setups/_schema/ks_porsche_911_gt3_r_2016/5c2e8707648a.json"


def _spinner(**kw) -> SpinnerDesc:
    return SpinnerDesc.from_dump({"name": "X", **kw})


def test_decode_numeric_uses_display_multiplier() -> None:
    sp = _spinner(displayMultiplier=0.1, min=-40, max=-10, step=1)
    assert sp.decode(-18) == pytest.approx(-1.8)
    assert sp.decode(None) is None


def test_decode_enum_by_items_and_item_values() -> None:
    sp = _spinner(items=["Soft", "Medium", "Hard"], itemValues=[0, 1, 2], min=0, max=2, step=1)
    assert sp.decode(0) == "Soft"
    assert sp.decode(1) == "Medium"
    assert sp.decode(2) == "Hard"
    assert sp.decode(5) is None  # out of range


def test_clamp_snaps_to_range_and_step() -> None:
    sp = _spinner(min=0, max=20, step=1)
    assert sp.clamp(25) == 20.0
    assert sp.clamp(-3) == 0.0
    sp2 = _spinner(min=0, max=10, step=2)
    assert sp2.clamp(5.4) == 6.0  # round(2.7)=3 -> 6
    assert sp2.clamp(4.9) == 4.0  # round(2.45)=2 -> 4


def test_is_valid_rejects_out_of_range_offstep_and_readonly() -> None:
    sp = _spinner(min=0, max=20, step=1)
    assert sp.is_valid(16) is True
    assert sp.is_valid(21) is False  # over max
    assert sp.is_valid(-1) is False  # under min
    off = _spinner(min=0, max=10, step=2)
    assert off.is_valid(5) is False  # off the step grid
    ro = _spinner(min=0, max=10, step=1, readOnly=True)
    assert ro.is_valid(5) is False  # read-only


def test_schema_hash_is_deterministic_and_structure_only() -> None:
    dump = [{"name": "A", "min": 0, "max": 10, "step": 1, "value": 5}]
    s1 = CarSetupSchema.from_spinners_dump("car", dump)
    # same structure, different current value -> same hash
    dump2 = [{"name": "A", "min": 0, "max": 10, "step": 1, "value": 7}]
    s2 = CarSetupSchema.from_spinners_dump("car", dump2)
    assert s1.schema_hash == s2.schema_hash and len(s1.schema_hash) == 12
    # different range -> different hash
    dump3 = [{"name": "A", "min": 0, "max": 12, "step": 1, "value": 5}]
    assert CarSetupSchema.from_spinners_dump("car", dump3).schema_hash != s1.schema_hash


def test_schema_level_validate_clamp_decode_and_unknown_passthrough() -> None:
    s = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "WING_2", "min": 0, "max": 20, "step": 1, "value": 16}]
    )
    assert s.validate("WING_2", 25) is False
    assert s.clamp("WING_2", 25) == 20.0
    # unknown spinner: permissive passthrough (schema may be partial)
    assert s.validate("UNKNOWN", 999) is True
    assert s.clamp("UNKNOWN", 999) == 999.0
    assert s.decode("UNKNOWN", 5) == 5


def test_constrain_params_clamps_section_value_keys() -> None:
    s = CarSetupSchema.from_spinners_dump(
        "car",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1},
            {"name": "ARB_FRONT", "min": 1, "max": 8, "step": 1},
        ],
    )
    out = s.constrain_params({"WING_2.VALUE": 30, "ARB_FRONT.VALUE": 0, "UNTRACKED.VALUE": 99})
    assert out["WING_2.VALUE"] == 20.0
    assert out["ARB_FRONT.VALUE"] == 1.0
    assert out["UNTRACKED.VALUE"] == 99  # unknown -> untouched


def test_json_roundtrip_and_save_load(tmp_path: Path) -> None:
    s = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 11, "step": 1, "value": 7, "units": ""}]
    )
    again = CarSetupSchema.from_json(s.to_json())
    assert again.car_id == "car" and again.schema_hash == s.schema_hash
    assert again.spinners["ABS"].max == 11
    dest = s.save(tmp_path)
    assert dest.exists()
    loaded = CarSetupSchema.load(dest)
    assert loaded.schema_hash == s.schema_hash


def test_from_car_setup_reads_spinner_schema() -> None:
    class _FakeSetup:
        car_id = "car"
        spinner_schema = {"WING_2": {"min": 0, "max": 20, "step": 1, "value": 16}}

    s = CarSetupSchema.from_car_setup(_FakeSetup())
    assert s is not None and "WING_2" in s.spinners
    assert CarSetupSchema.from_car_setup(object()) is None  # no spinner_schema -> None


def test_example_asset_decodes_known_values() -> None:
    assert EXAMPLE.exists(), f"example schema asset missing: {EXAMPLE}"
    s = CarSetupSchema.load(EXAMPLE)
    assert s.car_id == "ks_porsche_911_gt3_r_2016"
    assert len(s.spinners) == 12
    assert s.decode("CAMBER_LF", -18) == pytest.approx(-1.8)  # displayMultiplier 0.1
    assert s.decode("TYRES", 1) == "Medium"  # enum
    assert s.validate("WING_2", 25) is False and s.clamp("WING_2", 25) == 20.0
    assert s.validate("FINAL_RATIO", 7) is False  # read-only in the example


def test_from_spinners_captures_ranges() -> None:
    from tools.ai_sidecar.setup_model import from_spinners

    cs = from_spinners(
        [
            {
                "name": "WING_2",
                "value": 16,
                "min": 0,
                "max": 20,
                "step": 1,
                "displayMultiplier": 1.0,
            },
            {"name": "ABS", "value": 7, "min": 0, "max": 11, "step": 1},
        ]
    )
    assert cs.value("WING_2") == 16.0  # existing value path unchanged
    assert cs.spinner_schema is not None
    assert cs.spinner_schema["WING_2"]["max"] == 20  # ranges are NO LONGER discarded
    sch = CarSetupSchema.from_car_setup(cs)
    assert sch is not None and sch.validate("WING_2", 25) is False


def test_optimizer_respects_schema_constraint() -> None:
    from tools.ai_sidecar.setup_optimizer import suggest_next_setup

    def rec(wing: float, lap_ms: int) -> dict:
        return {
            "car": {"id": "c"},
            "track": {"id": "t"},
            "lap": {"lap_ms": lap_ms, "is_valid": True},
            "setup": {"hash": f"h{wing}", "params": {"WING_2.VALUE": wing, "ARB_FRONT.VALUE": 6.0}},
        }

    records = [rec(20, 78000), rec(19, 78500), rec(18, 79000)]
    schema = CarSetupSchema.from_spinners_dump(
        "c",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1},
            {"name": "ARB_FRONT", "min": 1, "max": 8, "step": 1},
        ],
    )
    out = suggest_next_setup(records, car_id="c", track_id="t", schema=schema)
    if out.get("ok"):
        for key, move in out.get("changes", {}).items():
            assert schema.validate(key, move["to"]) is True  # no out-of-range proposal
    # backward-compat: no schema still returns a dict
    assert isinstance(suggest_next_setup(records, car_id="c", track_id="t"), dict)
