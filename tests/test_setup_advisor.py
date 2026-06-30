"""Tests for complaint-language setup advice and setup diffs."""

from __future__ import annotations

from pathlib import Path

from tools.ai_sidecar.car_schema import load_latest_schema
from tools.ai_sidecar.setup_advisor import (
    advise_from_complaint,
    diff_setup_files,
    setup_diff_summary,
)
from tools.ai_sidecar.setup_model import from_snapshot

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
}


def test_exit_loose_complaint_maps_to_ranked_setup_changes() -> None:
    out = advise_from_complaint(
        "car is loose on exit",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
        track_id="magione",
    )

    assert out["ok"] is True
    assert out["parsed"] == {"issue": "oversteer", "phase": "exit", "speed_hint": None}
    first = out["suggestions"][0]
    assert first["section"] == "TRACTION_CONTROL"
    assert first["direction"] == "increase"
    assert first["current"] == 3.0
    assert first["target"] == 4.0
    assert "wheelspin" in first["reason"]
    assert first["effect"]


def test_front_locks_complaint_gets_911_bias_caution() -> None:
    out = advise_from_complaint(
        "front locks on entry",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
    )

    assert out["ok"] is True
    assert out["parsed"]["issue"] == "lockup_front"
    first = out["suggestions"][0]
    assert first["section"] == "FRONT_BIAS"
    assert first["direction"] == "decrease"
    assert first["target"] == 65.0
    assert any("911" in note for note in first["caution"])


def test_high_speed_understeer_prefers_aero_lever() -> None:
    out = advise_from_complaint(
        "high speed understeer mid corner",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
    )

    assert out["ok"] is True
    sections = [suggestion["section"] for suggestion in out["suggestions"]]
    assert sections.index("WING_1") < sections.index("ARB_FRONT")


def test_mid_corner_text_overrides_generic_turn_word() -> None:
    out = advise_from_complaint(
        "won't turn mid corner",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
    )

    assert out["ok"] is True
    assert out["parsed"] == {"issue": "understeer", "phase": "mid", "speed_hint": None}
    assert out["suggestions"][0]["section"] == "ARB_FRONT"


def test_low_speed_hint_prefers_mechanical_lever() -> None:
    out = advise_from_complaint(
        "low speed understeer mid corner",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
    )

    assert out["ok"] is True
    assert out["parsed"]["speed_hint"] == "low"
    sections = [suggestion["section"] for suggestion in out["suggestions"]]
    assert sections.index("ARB_FRONT") < sections.index("WING_1")


def test_kerb_instability_takes_priority_over_rear_shorthand() -> None:
    out = advise_from_complaint(
        "rear unstable over kerb",
        setup_snapshot=GT3_SNAPSHOT,
        car_id="ks_porsche_911_gt3_r_2016",
    )

    assert out["ok"] is True
    assert out["parsed"]["issue"] == "instability"
    assert out["parsed"]["phase"] == "kerb"
    assert out["suggestions"][0]["section"] == "ARB_REAR"


def test_schema_bound_noop_suggestions_are_skipped() -> None:
    out = advise_from_complaint(
        "rear locks on entry",
        setup_snapshot={**GT3_SNAPSHOT, "FRONT_BIAS.VALUE": "70"},
        car_id="ks_porsche_911_gt3_r_2016",
        schema=load_latest_schema("ks_porsche_911_gt3_r_2016"),
    )

    assert out["ok"] is True
    assert all(suggestion["section"] != "FRONT_BIAS" for suggestion in out["suggestions"])
    assert out["suggestions"][0]["section"] == "BRAKE_POWER_MULT"


def test_schema_read_only_suggestions_are_skipped() -> None:
    out = advise_from_complaint(
        "wheelspin on exit",
        setup_snapshot={**GT3_SNAPSHOT, "FINAL_RATIO.VALUE": "7"},
        car_id="ks_porsche_911_gt3_r_2016",
        schema=load_latest_schema("ks_porsche_911_gt3_r_2016"),
    )

    assert out["ok"] is True
    assert all(suggestion["section"] != "FINAL_RATIO" for suggestion in out["suggestions"])


def test_setup_diff_summary_returns_display_ready_rows() -> None:
    baseline = from_snapshot(GT3_SNAPSHOT, car_id="ks_porsche_911_gt3_r_2016")
    candidate = from_snapshot(
        {
            **GT3_SNAPSHOT,
            "FRONT_BIAS.VALUE": "64",
            "TRACTION_CONTROL.VALUE": "4",
        },
        car_id="ks_porsche_911_gt3_r_2016",
    )

    out = setup_diff_summary(baseline, candidate)

    assert out["ok"] is True
    assert out["changed_count"] == 2
    first = out["rows"][0]
    assert first["section"] == "FRONT_BIAS"
    assert first["direction"] == "decrease"
    assert first["from"] == 66.0
    assert first["to"] == 64.0
    assert "Brake bias" in first["display"]
    assert out["display_lines"][0] == first["display"]


def test_setup_diff_rejects_different_cars() -> None:
    baseline = from_snapshot(GT3_SNAPSHOT, car_id="ks_porsche_911_gt3_r_2016")
    candidate = from_snapshot(GT3_SNAPSHOT, car_id="bmw_z4_gt3")

    out = setup_diff_summary(baseline, candidate)

    assert out["ok"] is False
    assert out["status"] == "car_mismatch"
    assert out["changed_count"] == 0


def test_setup_diff_without_schema_uses_click_units_for_raw_alignment() -> None:
    baseline = from_snapshot({"CAMBER_LF.VALUE": "-18"})
    candidate = from_snapshot({"CAMBER_LF.VALUE": "-19"})

    out = setup_diff_summary(baseline, candidate)

    assert out["rows"][0]["units"] == "clicks"
    assert out["rows"][0]["from_display"] == "-18"
    assert out["rows"][0]["to_display"] == "-19"
    assert out["rows"][0]["display"].endswith("clicks (decrease)")


def test_setup_diff_uses_camber_semantic_direction_with_schema() -> None:
    schema = load_latest_schema("ks_porsche_911_gt3_r_2016")
    baseline = from_snapshot({"CAMBER_LF.VALUE": "-18"}, car_id="ks_porsche_911_gt3_r_2016")
    candidate = from_snapshot({"CAMBER_LF.VALUE": "-19"}, car_id="ks_porsche_911_gt3_r_2016")

    out = setup_diff_summary(baseline, candidate, schema=schema)

    row = out["rows"][0]
    assert row["direction"] == "increase"
    assert row["effect"].startswith("More negative")
    assert row["display"].endswith("deg (increase)")


def test_diff_setup_files_loads_car_schema_for_display_units(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.ini"
    candidate = tmp_path / "candidate.ini"
    baseline.write_text(
        "[CAR]\nMODEL=ks_porsche_911_gt3_r_2016\n[CAMBER_LF]\nVALUE=-18\n",
        encoding="utf-8",
    )
    candidate.write_text(
        "[CAR]\nMODEL=ks_porsche_911_gt3_r_2016\n[CAMBER_LF]\nVALUE=-19\n",
        encoding="utf-8",
    )

    out = diff_setup_files(baseline, candidate)

    assert out["rows"][0]["units"] == "deg"
    assert out["rows"][0]["from_display"] == "-1.8"
    assert out["rows"][0]["to_display"] == "-1.9"
