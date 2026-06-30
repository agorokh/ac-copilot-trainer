"""Tests for live stint-level race management cues."""

from __future__ import annotations

from tools.ai_sidecar.race_management import RaceManagementObserver


def _tick(**payload):
    base = {
        "spline": 0.2,
        "speed_kmh": 120.0,
        "brake": 0.0,
        "throttle": 0.8,
        "lap": 0,
    }
    base.update(payload)
    return {"type": "telemetry_tick", "payload": base}


def test_fuel_save_cue_uses_observed_per_lap_burn_and_target() -> None:
    observer = RaceManagementObserver()

    assert observer.observe(_tick(lap=0, fuel_l=10.0)) == []
    out = observer.observe(_tick(lap=1, fuel_l=8.0, target_laps_remaining=5.0))

    save = next(a for a in out if a.kind == "fuel_save")
    assert save.register == "critical"
    assert "lift and coast" in save.message
    assert save.detail["fuel_per_lap_l"] == 2.0
    assert save.detail["laps_remaining"] == 4.0
    assert save.detail["target_laps_remaining"] == 5.0
    assert save.detail["deficit_laps"] == 1.0


def test_fuel_status_cue_when_fuel_is_enough() -> None:
    observer = RaceManagementObserver()

    observer.observe(_tick(lap=0, fuel_l=10.0))
    out = observer.observe(_tick(lap=1, fuel_l=8.0, target_laps_remaining=3.0))

    assert [a.kind for a in out] == ["fuel_status"]
    assert out[0].detail["laps_remaining"] == 4.0


def test_fuel_uses_frame_per_lap_until_observed_lap_sample_exists() -> None:
    observer = RaceManagementObserver()

    out = observer.observe(
        _tick(lap=2, fuel_l=3.0, fuel_per_lap_l=1.0, target_laps_remaining=4.0)
    )

    cue = next(a for a in out if a.kind == "fuel_save")
    assert cue.detail["fuel_per_lap_l"] == 1.0
    assert cue.detail["fuel_per_lap_source"] == "frame"


def test_fuel_burn_normalizes_when_lap_counter_skips() -> None:
    observer = RaceManagementObserver()

    observer.observe(_tick(lap=0, fuel_l=10.0))
    out = observer.observe(_tick(lap=2, fuel_l=6.0, target_laps_remaining=2.0))

    status = next(a for a in out if a.kind == "fuel_status")
    assert status.detail["fuel_per_lap_l"] == 2.0
    assert status.detail["fuel_per_lap_source"] == "observed_laps"


def test_tyre_overheat_is_distinct_from_wear() -> None:
    observer = RaceManagementObserver()
    out = observer.observe(
        _tick(
            lap=4,
            tyre_temps_c={"fl": 112.0, "fr": 111.0, "rl": 93.0, "rr": 94.0},
            tyre_wear_pct={"fl": 30.0, "fr": 28.0, "rl": 35.0, "rr": 34.0},
            tyre_compound="medium",
        )
    )

    cue = next(a for a in out if a.kind == "tyre_manage")
    assert cue.detail["classification"] == "overheat"
    assert "overheating" in cue.message
    assert cue.detail["wear_signal"] is True


def test_tyre_wear_cue_when_worn_but_not_hot() -> None:
    observer = RaceManagementObserver()
    out = observer.observe(
        _tick(
            lap=8,
            tyre_temps_c={"fl": 88.0, "fr": 88.0, "rl": 90.0, "rr": 91.0},
            tyre_wear_pct={"fl": 20.0, "fr": 25.0, "rl": 78.0, "rr": 80.0},
            tyre_compound="medium",
        )
    )

    cue = next(a for a in out if a.kind == "tyre_manage")
    assert cue.detail["classification"] == "wear"
    assert "without an overheat signal" in cue.message


def test_brake_temperature_management_cue_when_channel_is_available() -> None:
    observer = RaceManagementObserver()
    out = observer.observe(
        _tick(lap=3, brake_temps_c={"fl": 880.0, "fr": 870.0, "rl": 600.0, "rr": 610.0})
    )

    cue = next(a for a in out if a.kind == "brake_manage")
    assert cue.detail["classification"] == "critical_temp"
    assert cue.register == "critical"


def test_conditions_strategy_wet_and_deduped() -> None:
    observer = RaceManagementObserver()
    frame = _tick(weather_type="light_rain", track_temp_c=15.0, track_grip_level=0.92)

    first = observer.observe(frame)
    second = observer.observe(frame)

    cue = next(a for a in first if a.kind == "conditions_strategy")
    assert cue.urgency == "act"
    assert cue.detail["classification"] == "wet_regime"
    assert second == []
