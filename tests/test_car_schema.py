"""Tests for the per-car setup schema (``tools/ai_sidecar/car_schema.py``)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.ai_sidecar.car_schema import CarSetupSchema, SpinnerDesc, load_latest_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "assets/setups/_schema/ks_porsche_911_gt3_r_2016/4fcbe0406992.json"


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


def test_decode_enum_with_item_values_does_not_fall_back_to_index() -> None:
    sp = _spinner(items=["Short", "Medium", "Long"], itemValues=[10, 20, 30], min=0, max=2, step=1)
    assert sp.decode(20) == "Medium"
    assert sp.decode(1) is None
    assert sp.is_valid(20) is True
    assert sp.is_valid(1) is False


def test_clamp_snaps_to_range_and_step() -> None:
    sp = _spinner(min=0, max=20, step=1)
    assert sp.clamp(25) == 20.0
    assert sp.clamp(-3) == 0.0
    sp2 = _spinner(min=0, max=10, step=2)
    assert sp2.clamp(5.4) == 6.0  # round(2.7)=3 -> 6
    assert sp2.clamp(4.9) == 4.0  # round(2.45)=2 -> 4
    sp3 = _spinner(min=1, max=8, step=2)
    assert sp3.clamp(8) == 7.0
    assert sp3.is_valid(sp3.clamp(8)) is True


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
    dump = [{"name": "A", "min": 0, "max": 10, "step": 1, "value": 5, "units": "click"}]
    s1 = CarSetupSchema.from_spinners_dump("car", dump)
    # same structure, different current value -> same hash
    dump2 = [{"name": "A", "min": 0, "max": 10, "step": 1, "value": 7, "units": "click"}]
    s2 = CarSetupSchema.from_spinners_dump("car", dump2)
    assert s1.schema_hash == s2.schema_hash and len(s1.schema_hash) == 12
    # different range -> different hash
    dump3 = [{"name": "A", "min": 0, "max": 12, "step": 1, "value": 5, "units": "click"}]
    assert CarSetupSchema.from_spinners_dump("car", dump3).schema_hash != s1.schema_hash


def test_schema_hash_changes_when_decode_metadata_changes() -> None:
    base = CarSetupSchema.from_spinners_dump(
        "car",
        [
            {
                "name": "CAMBER_LF",
                "min": -40,
                "max": 0,
                "step": 1,
                "displayMultiplier": 0.1,
                "units": "deg",
            },
            {"name": "TYRES", "items": ["Soft", "Medium"], "itemValues": [0, 1]},
        ],
    )
    changed_multiplier = CarSetupSchema.from_spinners_dump(
        "car",
        [
            {
                "name": "CAMBER_LF",
                "min": -40,
                "max": 0,
                "step": 1,
                "displayMultiplier": 0.01,
                "units": "deg",
            },
            {"name": "TYRES", "items": ["Soft", "Medium"], "itemValues": [0, 1]},
        ],
    )
    changed_units = CarSetupSchema.from_spinners_dump(
        "car",
        [
            {
                "name": "CAMBER_LF",
                "min": -40,
                "max": 0,
                "step": 1,
                "displayMultiplier": 0.1,
                "units": "rad",
            },
            {"name": "TYRES", "items": ["Soft", "Medium"], "itemValues": [0, 1]},
        ],
    )
    changed_items = CarSetupSchema.from_spinners_dump(
        "car",
        [
            {
                "name": "CAMBER_LF",
                "min": -40,
                "max": 0,
                "step": 1,
                "displayMultiplier": 0.1,
                "units": "deg",
            },
            {"name": "TYRES", "items": ["Soft", "Medium"], "itemValues": [10, 20]},
        ],
    )
    assert changed_multiplier.schema_hash != base.schema_hash
    assert changed_units.schema_hash != base.schema_hash
    assert changed_items.schema_hash != base.schema_hash


def test_from_dump_preserves_csp_singular_unit_field() -> None:
    assert SpinnerDesc.from_dump({"name": "CAMBER_LF", "unit": "deg"}).units == "deg"


def test_schema_level_validate_clamp_decode_and_unknown_passthrough() -> None:
    s = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "WING_2", "min": 0, "max": 20, "step": 1, "value": 16}]
    )
    assert s.validate("WING_2", 25) is False
    assert s.validate("WING_2.VALUE", 25) is False
    assert s.clamp("WING_2", 25) == 20.0
    assert s.clamp("WING_2.VALUE", 25) == 20.0
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


def test_schema_caution_notes_roundtrip() -> None:
    s = CarSetupSchema.from_json(
        {
            "car_id": "car",
            "spinners": {"FRONT_BIAS": {"name": "FRONT_BIAS"}},
            "cautions": {
                "FRONT_BIAS": [
                    {"direction": "decrease", "message": "move carefully"},
                    {"direction": "increase", "current_lt": 50, "message": "too low"},
                ]
            },
        }
    )

    again = CarSetupSchema.from_json(s.to_json())

    assert again.caution_notes("FRONT_BIAS", direction="decrease", current=66) == ["move carefully"]
    assert again.caution_notes("FRONT_BIAS", direction="increase", current=49) == ["too low"]
    assert again.caution_notes("FRONT_BIAS", direction="increase", current=51) == []


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


def test_load_latest_schema_loads_checked_in_car_asset() -> None:
    s = load_latest_schema("ks_porsche_911_gt3_r_2016")
    assert s is not None
    assert s.car_id == "ks_porsche_911_gt3_r_2016"
    assert s.clamp("FRONT_BIAS", 71) == 70.0
    assert s.validate("FRONT_BIAS", 71) is False


def test_load_latest_schema_prefers_marker_then_lexicographic(tmp_path: Path) -> None:
    root = tmp_path / "schemas"
    car_dir = root / "car"
    car_dir.mkdir(parents=True)
    first = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 1, "step": 1}]
    )
    second = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 2, "step": 1}]
    )
    marked = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 3, "step": 1}]
    )
    (car_dir / "001.json").write_text(json.dumps(first.to_json()), encoding="utf-8")
    (car_dir / "002.json").write_text(json.dumps(second.to_json()), encoding="utf-8")

    assert load_latest_schema("car", schema_dir=root).spinners["ABS"].max == 2

    (car_dir / "latest.json").write_text(json.dumps(marked.to_json()), encoding="utf-8")

    assert load_latest_schema("car", schema_dir=root).spinners["ABS"].max == 3


def test_load_latest_schema_ignores_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "schemas"
    car_dir = root / "car"
    car_dir.mkdir(parents=True)
    safe = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 1, "step": 1}]
    )
    outside = CarSetupSchema.from_spinners_dump(
        "car", [{"name": "ABS", "min": 0, "max": 99, "step": 1}]
    )
    (car_dir / "001.json").write_text(json.dumps(safe.to_json()), encoding="utf-8")
    outside_path = tmp_path / "outside.json"
    outside_path.write_text(json.dumps(outside.to_json()), encoding="utf-8")
    try:
        (car_dir / "999.json").symlink_to(outside_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unsupported on this platform: {exc!r}")

    loaded = load_latest_schema("car", schema_dir=root)

    assert loaded is not None
    assert loaded.spinners["ABS"].max == 1


def test_load_latest_schema_rejects_unsafe_car_id(tmp_path: Path) -> None:
    root = tmp_path / "schemas"
    escape = tmp_path / "escape"
    escape.mkdir()
    (escape / "fake.json").write_text("{}", encoding="utf-8")

    assert load_latest_schema("../escape", schema_dir=root) is None
    assert load_latest_schema("ks/porsche", schema_dir=root) is None
    assert load_latest_schema("ks_porsche..911", schema_dir=root) is None
    assert load_latest_schema(".", schema_dir=root) is None
    assert load_latest_schema("---", schema_dir=root) is None


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
        ],
        car_id="car",
    )
    assert cs.value("WING_2") == 16.0  # existing value path unchanged
    assert cs.spinner_schema is not None
    assert cs.spinner_schema["WING_2"]["max"] == 20  # ranges are NO LONGER discarded
    sch = CarSetupSchema.from_car_setup(cs)
    assert sch is not None
    assert sch.car_id == "car"
    assert sch.validate("WING_2", 25) is False


def test_direct_script_help_runs_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/ai_sidecar/car_schema.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Ingest an ac.getSetupSpinners() dump" in result.stdout


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


def test_optimizer_allows_unchanged_read_only_schema_params() -> None:
    from tools.ai_sidecar.setup_optimizer import suggest_next_setup

    def rec(wing: float, final_ratio: float, lap_ms: int) -> dict:
        return {
            "car": {"id": "c"},
            "track": {"id": "t"},
            "lap": {"lap_ms": lap_ms, "is_valid": True},
            "setup": {
                "hash": f"h{wing}",
                "params": {"WING_2.VALUE": wing, "FINAL_RATIO.VALUE": final_ratio},
            },
        }

    records = [rec(10, 7, 78_000), rec(9, 7, 79_000)]
    schema = CarSetupSchema.from_spinners_dump(
        "c",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1},
            {"name": "FINAL_RATIO", "min": 0, "max": 12, "step": 1, "readOnly": True},
        ],
    )
    out = suggest_next_setup(records, car_id="c", track_id="t", schema=schema)
    assert out["ok"] is True
    assert "WING_2.VALUE" in out["candidate"]["changed_params"]
    assert "FINAL_RATIO.VALUE" not in out["candidate"]["changed_params"]


def test_optimizer_clamps_schema_boundary_candidates_before_filtering() -> None:
    from tools.ai_sidecar.setup_optimizer import suggest_next_setup

    def rec(wing: float, lap_ms: int) -> dict:
        return {
            "car": {"id": "c"},
            "track": {"id": "t"},
            "lap": {"lap_ms": lap_ms, "is_valid": True},
            "setup": {"hash": f"h{wing}", "params": {"WING_2.VALUE": wing}},
        }

    records = [rec(19, 78_000), rec(17, 79_000)]
    schema = CarSetupSchema.from_spinners_dump(
        "c", [{"name": "WING_2", "min": 0, "max": 20, "step": 1}]
    )
    out = suggest_next_setup(records, car_id="c", track_id="t", schema=schema)
    assert out["ok"] is True
    assert out["candidate"]["changed_params"]["WING_2.VALUE"]["to"] == 20.0
