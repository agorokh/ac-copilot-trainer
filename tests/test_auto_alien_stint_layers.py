"""#674 auto_alien Layer-0 / Layer-4 composition helpers (offline)."""

from __future__ import annotations

from tools.ac_harness.auto_alien import compose_stint_layers
from tools.ac_harness.auto_drive import generic_gt3_ggv
from tools.ac_harness.ggv_profile import with_binned_uncertainty
from tools.ac_harness.reference_lap import TRACE_FIELDS


def _plant() -> dict:
    prior = generic_gt3_ggv()
    rows = [
        {"speed_kmh": float(speed), "accg_lat": 1.2, "accg_lon": -1.2, "source": "brake_probe"}
        for speed in range(50, 151, 10)
        for _ in range(40)
    ]
    model = with_binned_uncertainty(prior, rows, prior)
    return {
        "schema_version": 3,
        "ok": True,
        "car_id": "car_a",
        "track_id": "track_a",
        "layout": None,
        "setup": "race",
        "constants": {
            "ff_sign": 1.0,
            "ff_c1": 0.5,
            "ff_c2": 0.0,
            "rpm_up": 7000.0,
            "rpm_dn": 5000.0,
            "r_eff_m": 0.32,
        },
        "ggv": {
            "ok": True,
            "model": model.to_dict(),
            "thermal_cohort": {
                "core_temp_c": 90.0,
                "pressure_psi": 27.0,
                "core_tolerance_c": 5.0,
                "pressure_tolerance_psi": 2.0,
                "compound": 1,
                "setup_hash": "setup-a",
                "thermal_tag": "optimal",
            },
        },
    }


def _archive(lap_uuid: str, *, lap_n: int, core_c: float) -> dict:
    fields = list(TRACE_FIELDS)
    samples = []
    for i in range(120):
        values = dict.fromkeys(fields, 0.0)
        values.update({"spline": i / 120.0, "speed": 70.0, "eMs": i * 10.0, "fuel": 18.0})
        for wheel in ("fl", "fr", "rl", "rr"):
            values[f"tyreCoreTemp_{wheel}"] = core_c
            values[f"tyreTempInner_{wheel}"] = core_c
            values[f"tyreTempMid_{wheel}"] = core_c
            values[f"tyreTempOuter_{wheel}"] = core_c
            values[f"wheelsPressure_{wheel}"] = 27.0
            values[f"dy_{wheel}"] = 1.4
        samples.append([values[field] for field in fields])
    return {
        "schema_version": 1,
        "lap_uuid": lap_uuid,
        "lap": {"lap_n": lap_n, "lap_ms": 91_000, "is_valid": True},
        "setup": {"hash": "setup-a"},
        "tyres": {"compoundIndex": 1, "name": "M", "optimalTempC": 90.0},
        "trace": {"fields": fields, "samples": samples, "samples_count": len(samples)},
    }


def test_compose_stint_layers_ok_without_archives() -> None:
    block = compose_stint_layers(
        plant_artifact=_plant(),
        archive_payloads=[],
        laps_remaining=5,
        fuel_start_l=30.0,
        fuel_burn_l_per_lap=2.0,
        tyre_temp_target_c=90.0,
        tyre_temp_tolerance_c=5.0,
        wear_budget_fraction=0.35,
        v_top_kmh=250.0,
    )
    assert block["ok"] is True
    assert block["stint"]["pace_scale"] == 1.0
    assert block["inner_loop"]["ggv_scale"] == 1.0
    assert block["environment"] is None


def test_compose_stint_layers_flags_environment_drift() -> None:
    block = compose_stint_layers(
        plant_artifact=_plant(),
        archive_payloads=[
            _archive("lap-1", lap_n=1, core_c=70.0),
            _archive("lap-2", lap_n=2, core_c=115.0),
        ],
        laps_remaining=4,
        fuel_start_l=20.0,
        fuel_burn_l_per_lap=2.0,
        tyre_temp_target_c=90.0,
        tyre_temp_tolerance_c=5.0,
        wear_budget_fraction=0.35,
        v_top_kmh=240.0,
    )
    assert block["ok"] is True
    assert block["environment"]["nonstationary"] is True
    assert block["stint"]["degraded"] is True
    assert block["inner_loop"]["ggv_scale"] < 1.0


def test_compose_stint_layers_names_missing_plant() -> None:
    block = compose_stint_layers(
        plant_artifact=None,
        archive_payloads=[],
        laps_remaining=1,
        fuel_start_l=30.0,
        fuel_burn_l_per_lap=2.0,
        tyre_temp_target_c=90.0,
        tyre_temp_tolerance_c=5.0,
        wear_budget_fraction=0.35,
        v_top_kmh=250.0,
    )
    assert block["ok"] is False
    assert "stint_plant_missing" in block["error"]
