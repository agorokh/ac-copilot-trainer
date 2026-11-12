"""Regression from the #956 autonomous rig capture; no real-driver acceptance."""

from __future__ import annotations

import json

import pytest
from test_setup_prescription import bind, card_for, inputs
from test_setup_prescription import isolated_ledger as isolated_ledger

from tools.ai_sidecar.tyre_specs import read_tyre_peak_window, read_tyre_specs


def tyre_car(tmp_path, front, rear="70|0.9\n90|1\n100|0.9\n"):
    car = tmp_path / "peak_car"
    data = car / "data"
    data.mkdir(parents=True)
    (data / "tyres.ini").write_text(
        "[FRONT]\nPRESSURE_IDEAL=26\n[REAR]\nPRESSURE_IDEAL=27\n"
        "[THERMAL_FRONT]\nPERFORMANCE_CURVE=front.lut\n"
        "[THERMAL_REAR]\nPERFORMANCE_CURVE=rear.lut\n"
    )
    (data / "front.lut").write_text(front)
    (data / "rear.lut").write_text(rear)
    return car


def test_authored_plateau_preserves_scalar_contract_and_strict_axles(tmp_path):
    # Real Porsche medium plateau captured before implementation; surrounding
    # nonmaximum values prevent confusing the plateau with a global tolerance.
    car = tyre_car(tmp_path, "70|0.98\n80|1\n90|1\n95|1\n105|0.97\n")
    assert read_tyre_specs(car, 0, axle="front").optimal_temp_c == 80
    assert read_tyre_peak_window(car, 0, axle="front") == (80, 95)
    assert read_tyre_peak_window(car, 0, axle="rear") == (90, 90)
    assert read_tyre_peak_window(car, 1, axle="front") is None
    assert read_tyre_peak_window(car, 0, axle="unknown") is None


@pytest.mark.parametrize(
    "curve",
    [
        "80|1\n90|0.9\n95|1\n",  # disconnected maxima
        "80|1\n80|1\n",  # duplicate abscissa
        "95|1\n80|1\n",  # reversed curve
        "80|1\nnot-a-point\n95|1\n",  # no silent malformed-point skip
        "80|1\n90|1e999\n95|1\n",
        "80|nan\n95|1\n",
        "80|0\n95|0\n",
    ],
)
def test_unverifiable_peak_curve_fails_closed(tmp_path, curve):
    assert read_tyre_peak_window(tyre_car(tmp_path, curve), 0, axle="front") is None


def plateau_inputs(historical=95):
    data = inputs()
    for archive in data[0]:
        archive["tyres"]["optimalTempC"] = historical
        bind(archive)
    for target in data[3].values():
        target.update(peak_temp_min_c=80, peak_temp_max_c=95)
    return data


def test_native_optimum_can_match_another_authored_peak():
    data = plateau_inputs()
    assert card_for(data)["status"] == "proposed"
    for target in data[3].values():
        target.pop("peak_temp_min_c")
        target.pop("peak_temp_max_c")
    assert "thermal target changed" in card_for(data)["reason"]


@pytest.mark.parametrize("historical", [78.9, 96.1])
def test_outside_authored_peaks_retains_changed_content_guard(historical):
    assert "thermal target changed" in card_for(plateau_inputs(historical))["reason"]


@pytest.mark.parametrize(
    "bad", [{"peak_temp_min_c": None}, {"peak_temp_max_c": 79}, {"peak_temp_max_c": float("nan")}]
)
def test_production_unknown_or_invalid_peak_cannot_use_scalar_fallback(bad):
    data = plateau_inputs()
    data[3]["fl"].update(bad)
    assert "peak window unavailable" in card_for(data)["reason"]


def test_authored_peak_is_hashed_without_widening_thermal_policy():
    data = plateau_inputs()
    original = card_for(data)
    data[3]["fl"]["peak_temp_max_c"] = 96
    assert card_for(data)["prescription_id"] != original["prescription_id"]
    for archive in data[0]:
        fields = archive["trace"]["fields"]
        for row in archive["trace"]["samples"]:
            for wheel in ("fl", "fr", "rl", "rr"):
                row[fields.index("tyreCoreTemp_" + wheel)] = 95
        bind(archive)
    assert "thermal confounding" in card_for(data)["reason"]
    assert json.dumps(original, allow_nan=False)
