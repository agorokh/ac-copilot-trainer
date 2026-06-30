"""Tests for complaint-language setup advice and setup diffs."""

from __future__ import annotations

from tools.ai_sidecar.setup_advisor import advise_from_complaint, setup_diff_summary
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
