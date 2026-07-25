"""EPIC #529 / #674 Layer-0 environment observer — offline, no rig."""

from __future__ import annotations

import pytest

from tools.ac_harness.env_observer import (
    EnvironmentObserverError,
    environment_for_plan,
    environment_from_archives,
    observation_from_lap_archive,
    update_environment,
)
from tools.ac_harness.reference_lap import TRACE_FIELDS


def _archive(
    lap_uuid: str,
    *,
    lap_n: int,
    core_c: float,
    pressure_psi: float = 27.0,
    grip_dy: float = 1.5,
    fuel: float = 20.0,
    wear: float = 0.1,
    valid: bool = True,
) -> dict:
    fields = list(TRACE_FIELDS)
    samples = []
    for i in range(200):
        values = dict.fromkeys(fields, 0.0)
        values.update(
            {
                "spline": i / 200.0,
                "speed": 80.0,
                "eMs": i * 10.0,
                "fuel": fuel,
                "accG_lat": 1.1,
                "accG_long": -0.2,
            }
        )
        for wheel in ("fl", "fr", "rl", "rr"):
            values[f"tyreCoreTemp_{wheel}"] = core_c
            values[f"tyreTempInner_{wheel}"] = core_c + 1.0
            values[f"tyreTempMid_{wheel}"] = core_c
            values[f"tyreTempOuter_{wheel}"] = core_c - 1.0
            values[f"wheelsPressure_{wheel}"] = pressure_psi
            values[f"tyreWear_{wheel}"] = wear
            values[f"dy_{wheel}"] = grip_dy
        samples.append([values[field] for field in fields])
    return {
        "schema_version": 1,
        "lap_uuid": lap_uuid,
        "lap": {"lap_n": lap_n, "lap_ms": 90_000, "is_valid": valid},
        "setup": {"hash": "setup-a"},
        "tyres": {"compoundIndex": 1, "name": "M", "optimalTempC": 90.0},
        "trace": {"fields": fields, "samples": samples, "samples_count": len(samples)},
    }


def test_observation_validates_finite_ranges() -> None:
    obs = observation_from_lap_archive(_archive("lap-1", lap_n=1, core_c=90.0))
    assert obs.core_temp_c == pytest.approx(90.0)
    assert obs.pressure_psi == pytest.approx(27.0)
    assert obs.grip_multiplier is not None
    assert obs.fuel_end_l == pytest.approx(20.0)
    assert obs.fit_eligible is True

    bad = _archive("lap-bad", lap_n=1, core_c=90.0, valid=False)
    with pytest.raises(EnvironmentObserverError, match="environment_lap_invalid"):
        observation_from_lap_archive(bad)

    nan_arch = _archive("lap-nan", lap_n=1, core_c=90.0)
    nan_arch["lap"]["lap_ms"] = float("nan")
    with pytest.raises(EnvironmentObserverError, match="environment_lap_ms_non_finite"):
        observation_from_lap_archive(nan_arch)


def test_stationary_sequence_keeps_low_uncertainty() -> None:
    state = None
    for n in range(1, 4):
        state = update_environment(
            state, observation_from_lap_archive(_archive(f"lap-{n}", lap_n=n, core_c=90.0))
        )
    assert state is not None
    assert state.n_laps == 3
    assert state.nonstationary is False
    assert state.reidentify_recommended is False
    assert state.track_grip_std is not None
    assert state.track_grip_std < 0.05
    plan_view = environment_for_plan(state)
    assert plan_view["nonstationary"] is False
    assert plan_view["evidence_lap_uuids"] == ["lap-1", "lap-2", "lap-3"]


def test_thermal_and_grip_drift_flags_nonstationarity() -> None:
    cold = observation_from_lap_archive(
        _archive("lap-1", lap_n=1, core_c=70.0, pressure_psi=25.0, grip_dy=1.6)
    )
    hot = observation_from_lap_archive(
        _archive("lap-2", lap_n=2, core_c=110.0, pressure_psi=29.0, grip_dy=0.9)
    )
    state = update_environment(None, cold)
    state = update_environment(state, hot)
    assert state.nonstationary is True
    assert state.reidentify_recommended is True
    assert state.thermal_delta_c is not None and state.thermal_delta_c >= 8.0
    assert "thermal_delta" in (state.reason or "")


def test_duplicate_lap_and_empty_archives_fail_loud() -> None:
    first = observation_from_lap_archive(_archive("lap-1", lap_n=1, core_c=90.0))
    state = update_environment(None, first)
    with pytest.raises(EnvironmentObserverError, match="environment_lap_duplicate"):
        update_environment(state, first)
    with pytest.raises(EnvironmentObserverError, match="environment_archives_empty"):
        environment_from_archives([])
