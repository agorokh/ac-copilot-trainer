from __future__ import annotations

import json

import pytest

from tools.ac_harness.reference_lap import (
    GENERATED_IMPORT_FORMAT,
    TRACE_FIELDS,
    LapArchiveSchemaError,
    archive_trace_to_object_trace,
    build_archive_record,
    build_archive_record_from_scenario,
    build_trainer_reference_payload,
    main,
    validate_lap_archive_record,
)
from tools.ac_harness.trace_replay import BRAKE_ENTRY_SPEED_KMH, BRAKE_SPLINE, synthesize_trace


def test_generated_reference_archive_matches_lap_archive_schema_v1() -> None:
    frames = synthesize_trace("brake_too_late")
    record = build_archive_record_from_scenario(
        "brake_too_late",
        car_id="ks_mazda_miata",
        track_id="magione",
        track_length_m=2525.0,
        exported_at="2026-06-16T00:00:00Z",
    )

    validate_lap_archive_record(record)
    assert record["schema_version"] == 1
    assert record["source"] == "imported"
    assert record["import_format"] == GENERATED_IMPORT_FORMAT
    assert record["car"]["id"] == "ks_mazda_miata"
    assert record["track"]["id"] == "magione"
    assert record["track"]["lengthM"] == pytest.approx(2525.0)
    assert record["trace"]["fields"] == list(TRACE_FIELDS)
    assert record["trace"]["samples_count"] == len(frames)
    assert record["lap"]["lap_ms"] == round(frames[-1]["eMs"])
    assert record["corners"][0]["brakePointSpline"] == pytest.approx(BRAKE_SPLINE)
    assert record["corners"][0]["entrySpeed"] == pytest.approx(BRAKE_ENTRY_SPEED_KMH)


def test_archive_trace_converts_to_live_best_lap_trace_shape() -> None:
    record = build_archive_record_from_scenario("brake_too_late")
    frames = archive_trace_to_object_trace(record)

    assert len(frames) == record["trace"]["samples_count"]
    assert tuple(frames[0].keys()) == TRACE_FIELDS
    assert isinstance(frames[0]["gear"], int)
    assert frames[0]["spline"] == pytest.approx(record["trace"]["samples"][0][0])


def test_trainer_reference_payload_bridges_generated_archive_to_live_persistence() -> None:
    record = build_archive_record_from_scenario("brake_too_late")
    payload = build_trainer_reference_payload(record)

    assert "bestLapMs" not in payload
    assert payload["bestReferenceLapMs"] == record["lap"]["lap_ms"]
    assert payload["bestLapTrace"][0]["spline"] == pytest.approx(0.0)
    assert payload["bestLapTrace"][-1]["spline"] <= 1.0
    assert payload["bestBrakePoints"][0]["spline"] == pytest.approx(BRAKE_SPLINE)
    assert payload["bestBrakePoints"][0]["entrySpeed"] == pytest.approx(BRAKE_ENTRY_SPEED_KMH)
    assert payload["bestBrakePoints"][0]["label"] == "T1"
    assert payload["bestCornerFeatures"] == record["corners"]


def test_brake_corner_uses_full_tail_when_brake_never_releases() -> None:
    frames = [
        {
            "spline": 0.0,
            "speed": 160.0,
            "eMs": 0.0,
            "throttle": 1.0,
            "brake": 0.0,
            "steer": 0.0,
            "gear": 4,
            "px": 0.0,
            "py": 0.0,
            "pz": 0.0,
        },
        {
            "spline": 0.2,
            "speed": 140.0,
            "eMs": 1000.0,
            "throttle": 0.0,
            "brake": 1.0,
            "steer": 0.1,
            "gear": 4,
            "px": 1.0,
            "py": 0.0,
            "pz": 0.0,
        },
        {
            "spline": 0.3,
            "speed": 100.0,
            "eMs": 2000.0,
            "throttle": 0.2,
            "brake": 0.5,
            "steer": 0.3,
            "gear": 3,
            "px": 2.0,
            "py": 0.0,
            "pz": 0.0,
        },
    ]

    record = build_archive_record(
        frames,
        car_id="ks_mazda_miata",
        track_id="magione",
        exported_at="2026-06-16T00:00:00Z",
    )

    corner = record["corners"][0]
    assert corner["exitSpeed"] == pytest.approx(100.0)
    assert corner["minSpeed"] == pytest.approx(100.0)
    assert corner["trailBrakeRatio"] == pytest.approx(0.75)


def test_validator_rejects_trace_field_order_drift() -> None:
    record = build_archive_record_from_scenario("clean_lap")
    record["trace"]["fields"] = list(reversed(record["trace"]["fields"]))

    with pytest.raises(LapArchiveSchemaError, match="trace.fields"):
        validate_lap_archive_record(record)


def test_validator_rejects_non_monotonic_elapsed_time() -> None:
    record = build_archive_record_from_scenario("clean_lap")
    record["trace"]["samples"][2][TRACE_FIELDS.index("eMs")] = -1.0

    with pytest.raises(LapArchiveSchemaError, match="monotonic"):
        validate_lap_archive_record(record)


def test_validator_requires_corners_key() -> None:
    record = build_archive_record_from_scenario("clean_lap")
    del record["corners"]

    with pytest.raises(LapArchiveSchemaError, match="missing top-level key: corners"):
        validate_lap_archive_record(record)


def test_validator_rejects_lap_time_that_does_not_match_trace_elapsed() -> None:
    record = build_archive_record_from_scenario("clean_lap")
    record["lap"]["lap_ms"] += 5000

    with pytest.raises(LapArchiveSchemaError, match="lap.lap_ms must match final trace eMs"):
        validate_lap_archive_record(record)


def test_cli_emits_schema_valid_archive_json(tmp_path) -> None:
    output = tmp_path / "generated_ref.json"
    rc = main(
        [
            "--scenario",
            "clean_lap",
            "--car-id",
            "ks_mazda_miata",
            "--track-id",
            "magione",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    record = json.loads(output.read_text(encoding="utf-8"))
    validate_lap_archive_record(record)
    assert record["car"]["id"] == "ks_mazda_miata"
    assert record["track"]["id"] == "magione"


def test_cli_can_emit_trainer_state_payload(tmp_path) -> None:
    output = tmp_path / "generated_state.json"
    rc = main(["--emit", "trainer-state", "--output", str(output)])

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {
        "bestReferenceLapMs",
        "bestLapTrace",
        "bestBrakePoints",
        "bestCornerFeatures",
    }
    assert payload["bestLapTrace"]
