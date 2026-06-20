"""Tests for the setup comprehension layer (tools.ai_sidecar.setup_model)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.setup_model import (
    AERO,
    BALANCE,
    BRAKES,
    DRIVETRAIN,
    TIRES,
    CarSetup,
    from_lap_archive,
    from_snapshot,
    from_spinners,
    load_setup_file,
    parse_setup_ini,
    spec_for,
)

FIXTURES = Path(__file__).parent / "fixtures"

GT3_SNAPSHOT = {
    "FRONT_BIAS.VALUE": "66",
    "ABS.VALUE": "7",
    "TRACTION_CONTROL.VALUE": "3",
    "BRAKE_POWER_MULT.VALUE": "100",
    "WING_1.VALUE": "2",
    "WING_2.VALUE": "20",
    "ARB_FRONT.VALUE": "5",
    "ARB_REAR.VALUE": "3",
    "DIFF_POWER.VALUE": "40",
    "DIFF_COAST.VALUE": "20",
    "TYRES.VALUE": "1",
    "FUEL.VALUE": "30",
    "PRESSURE_LF.VALUE": "27.5",
    "PRESSURE_RF.VALUE": "27.5",
    "PRESSURE_LR.VALUE": "26.0",
    "PRESSURE_RR.VALUE": "26.0",
    "CAMBER_LF.VALUE": "-3.2",
    "CAMBER_RF.VALUE": "-3.2",
}


# --- spec resolution --------------------------------------------------------
def test_spec_for_known_section():
    s = spec_for("FRONT_BIAS")
    assert s.category == BRAKES
    assert "bias" in s.human_name.lower()


def test_spec_for_per_corner_resolves_corner_label():
    s = spec_for("PRESSURE_LF")
    assert s.category == TIRES
    assert s.corner == "LF"
    assert "front-left" in s.human_name


def test_spec_for_meta_and_unknown():
    assert spec_for("__EXT_PATCH").category == "meta"
    assert spec_for("ABOUT").category == "meta"
    assert spec_for("MADE_UP_KNOB").category == "other"


def test_wing_is_flagged_car_specific():
    assert spec_for("WING_1").car_specific is True


# --- snapshot parsing -------------------------------------------------------
def test_from_snapshot_semantic_accessors():
    s = from_snapshot(GT3_SNAPSHOT, car_id="ks_porsche_911_gt3_r_2016", track_id="magione")
    assert s.brake_bias_pct == 66.0
    assert s.abs_level == 7.0
    assert s.tc_level == 3.0
    assert s.wing_front == 2.0
    assert s.wing_rear == 20.0
    assert s.diff_power == 40.0
    assert s.compound_index == 1.0
    assert s.car_id == "ks_porsche_911_gt3_r_2016"


def test_tire_pressures_and_splits():
    s = from_snapshot(GT3_SNAPSHOT)
    p = s.tire_pressures()
    assert p == {"LF": 27.5, "RF": 27.5, "LR": 26.0, "RR": 26.0}
    assert s.mean_pressure() == pytest.approx(26.75)
    split = s.pressure_split()
    assert split is not None
    assert split["front_minus_rear"] == pytest.approx(1.5)
    assert split["left_minus_right"] == pytest.approx(0.0)


def test_arb_balance():
    s = from_snapshot(GT3_SNAPSHOT)
    assert s.arb_balance() == 2.0  # stiffer front -> understeer-biased


def test_missing_knob_returns_none():
    s = from_snapshot({"FRONT_BIAS.VALUE": "60"})
    assert s.tc_level is None
    assert s.tire_pressures() == {}
    assert s.pressure_split() is None
    assert s.arb_balance() is None


def test_non_numeric_value_is_not_tunable():
    s = from_snapshot({"ABOUT.AUTHOR": "someone", "FRONT_BIAS.VALUE": "55"})
    assert s.value("FRONT_BIAS") == 55.0
    assert "ABOUT" not in s.tunables()


def test_value_key_preferred_over_other_keys_same_section():
    # a non-VALUE key must not clobber the VALUE for the same section
    s = from_snapshot({"TYRES.VALUE": "2", "TYRES.NAME": "soft"})
    assert s.compound_index == 2.0


# --- ini parsing ------------------------------------------------------------
def test_parse_setup_ini_and_load_real_fixture():
    setup = load_setup_file(FIXTURES / "setups" / "pt_chip_summary.ini")
    assert setup.brake_bias_pct == 66.0
    assert setup.abs_level == 7.0
    assert setup.tc_level == 3.0
    assert setup.wing_front == 2.0
    assert setup.wing_rear == 20.0


def test_parse_setup_ini_handles_comments_and_blanks():
    text = "[FRONT_BIAS]\nVALUE=64  ; comment\n\n// stray\n[ABS]\nVALUE=5\n"
    snap = parse_setup_ini(text)
    assert snap["FRONT_BIAS.VALUE"] == "64"
    assert snap["ABS.VALUE"] == "5"


# --- lap archive + spinners -------------------------------------------------
def test_from_lap_archive_fixture():
    archive = json.loads((FIXTURES / "lap_archive_valid.json").read_text(encoding="utf-8"))
    s = from_lap_archive(archive)
    assert s.car_id == "ks_abarth500_assetto_corse"
    assert s.track_id == "magione"
    # fixture snapshot only has TYRES.PRESSURE_FRONT -> parsed under section TYRES
    assert s.value("TYRES") == 27.5


def test_from_lap_archive_missing_setup_is_empty_not_error():
    s = from_lap_archive({"car": {"id": "x"}})
    assert isinstance(s, CarSetup)
    assert s.tunables() == {}


def test_from_lap_archive_non_dict_degrades_to_empty():
    for bad in (None, "nope", [1, 2, 3], 42):
        s = from_lap_archive(bad)  # type: ignore[arg-type]
        assert isinstance(s, CarSetup)
        assert s.tunables() == {}


def test_from_spinners_live_read_path():
    spinners = [
        {"name": "FRONT_BIAS", "value": 62, "min": 50, "max": 70, "step": 1},
        {"name": "TRACTION_CONTROL", "value": 4, "min": 0, "max": 11, "step": 1},
        {"name": "PRESSURE_LF", "value": 28.0},
        {"bad": "no name"},
    ]
    s = from_spinners(spinners)
    assert s.brake_bias_pct == 62.0
    assert s.tc_level == 4.0
    assert s.tire_pressures()["LF"] == 28.0


# --- grouping / summary / diff ----------------------------------------------
def test_by_category_groups_tunables():
    s = from_snapshot(GT3_SNAPSHOT)
    cats = s.by_category()
    assert {p.section for p in cats[BRAKES]} >= {"FRONT_BIAS", "ABS", "BRAKE_POWER_MULT"}
    assert {p.section for p in cats[DRIVETRAIN]} >= {"TRACTION_CONTROL", "DIFF_POWER", "DIFF_COAST"}
    assert {p.section for p in cats[AERO]} == {"WING_1", "WING_2"}
    assert {p.section for p in cats[BALANCE]} == {"ARB_FRONT", "ARB_REAR"}


def test_human_summary_is_readable():
    s = from_snapshot(GT3_SNAPSHOT)
    text = "\n".join(s.human_summary())
    assert "Brake bias (front): 66 % front" in text
    assert f"[{BRAKES}]" in text


def test_diff_detects_changed_knobs():
    base = from_snapshot(GT3_SNAPSHOT)
    cand_snap = dict(GT3_SNAPSHOT, **{"FRONT_BIAS.VALUE": "64", "TRACTION_CONTROL.VALUE": "2"})
    cand = from_snapshot(cand_snap)
    d = cand.diff(base)
    assert d["FRONT_BIAS"] == {"from": 66.0, "to": 64.0}
    assert d["TRACTION_CONTROL"] == {"from": 3.0, "to": 2.0}
    assert "ABS" not in d  # unchanged


def test_diff_handles_added_and_removed_knobs():
    base = from_snapshot({"FRONT_BIAS.VALUE": "66"})
    cand = from_snapshot({"FRONT_BIAS.VALUE": "66", "TRACTION_CONTROL.VALUE": "5"})
    d = cand.diff(base)
    assert d["TRACTION_CONTROL"] == {"from": None, "to": 5.0}
