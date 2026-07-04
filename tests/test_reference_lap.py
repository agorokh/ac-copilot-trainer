from __future__ import annotations

import json
import re
from pathlib import Path

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


def test_validator_accepts_old_10_field_schema_v1_trace() -> None:
    # codex #274: SCHEMA_VERSION is still 1 and old archives carry only the 10 required columns.
    # The validator must still accept them (per-wheel channels are an optional extension).
    record = build_archive_record_from_scenario("brake_too_late")
    full = record["trace"]["fields"]
    keep = list(full[:10])
    idxs = list(range(10))
    record["trace"]["fields"] = keep
    record["trace"]["samples"] = [[row[i] for i in idxs] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)  # must not raise
    # and conversion must degrade to 10-field frames, not IndexError on the missing wheel columns
    frames = archive_trace_to_object_trace(record)
    assert tuple(frames[0].keys()) == TRACE_FIELDS[:10]
    assert "wheelAngularSpeed_fl" not in frames[0]


def test_generated_archive_carries_per_wheel_channels() -> None:
    # #266/#442: a generated reference archive must include the per-wheel columns plus rpm,
    # with physically plausible synthetic wheel values.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    for name in ("wheelAngularSpeed_fl", "wheelSlip_rr", "tyreCoreTemp_fl"):
        assert name in fields
    assert "rpm" in fields
    # Append-only history: #478 pressure block, then #490 Tier-1 (last was accG_vert at idx 75),
    # then #488 Part A Tier-2 force/slip — so the final column is now dy_rr.
    assert fields[-1] == "dy_rr"
    frames = archive_trace_to_object_trace(record)
    f0 = frames[0]
    speed_ms = f0["speed"] / 3.6
    assert f0["wheelAngularSpeed_fl"] == pytest.approx(speed_ms / 0.347, rel=1e-6)
    assert f0["wheelSlip_fl"] == pytest.approx(0.0)
    assert f0["tyreCoreTemp_rr"] == pytest.approx(80.0)
    assert f0["rpm"] == pytest.approx(0.0)


def test_generated_archive_carries_tier_b_chassis_channels() -> None:
    # #478: a generated reference archive includes the chassis + hot-pressure columns. The synthetic
    # generator does not model them, so they are 0.0 -> the analysis layer's all-zero guard treats a
    # generated reference as honestly having no measured chassis/pressure signal.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    for name in (
        "accG_long",
        "accG_lat",
        "yaw_rate",
        "wheelsPressure_fl",
        "wheelsPressure_fr",
        "wheelsPressure_rl",
        "wheelsPressure_rr",
    ):
        assert name in fields
    f0 = archive_trace_to_object_trace(record)[0]
    for name in ("accG_long", "accG_lat", "yaw_rate", "wheelsPressure_fl", "wheelsPressure_rr"):
        assert f0[name] == pytest.approx(0.0)


def test_lua_and_python_trace_fields_are_byte_identical() -> None:
    # #490 acceptance #4 (and the load-bearing contract behind #266/#442/#478): the capture-side Lua
    # TRACE_FIELDS and the Python mirror MUST be byte-identical - a drift silently corrupts every
    # archive's column mapping. Parse the Lua list and compare to reference_lap.TRACE_FIELDS.
    lua_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ac_copilot_trainer"
        / "modules"
        / "lap_archive.lua"
    )
    lua_src = lua_path.read_text(encoding="utf-8")
    match = re.search(r"local TRACE_FIELDS = \{(.*?)\n\}", lua_src, re.S)
    assert match is not None, "TRACE_FIELDS block not found in lap_archive.lua"
    lua_fields = re.findall(r'"([^"]+)"', match.group(1))
    assert lua_fields == list(TRACE_FIELDS)


def test_generated_archive_carries_tier1_dynamic_channels() -> None:
    # #490: a generated reference archive includes the Tier-1 dynamic columns. The synthetic
    # generator does not model them, so they are 0.0 -> the analysis all-zero guard treats a
    # generated reference as honestly having no measured dynamic signal.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    for name in (
        "tyreTempInner_fl",
        "tyreTempOuter_rr",
        "brakeTemp_fl",
        "wheelLoad_rr",
        "tyreWear_fl",
        "tyreDirty_rr",
        "camber_fl",
        "suspTravel_rr",
        "damperVel_fl",
        "rideHeightFront",
        "rideHeightRear",
        "brakeBias",
        "turboBoost",
        "fuel",
        "accG_vert",
    ):
        assert name in fields
    # accG_vert is the last Tier-1 column (index 75); #488 Part A appends Tier-2 after it.
    assert fields[75] == "accG_vert"
    f0 = archive_trace_to_object_trace(record)[0]
    for name in ("tyreTempInner_fl", "camber_rr", "rideHeightFront", "fuel", "accG_vert"):
        assert f0[name] == pytest.approx(0.0)


def test_validator_accepts_pre_490_30_field_trace() -> None:
    # #490: the Tier-1 dynamic channels append AFTER the #478 pressure block; a lap captured between
    # #478 and #490 declares 30 columns and stays schema-v1-valid, converting without the #490 keys.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    record["trace"]["fields"] = list(fields[:30])
    record["trace"]["samples"] = [[row[i] for i in range(30)] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)  # must not raise
    frames = archive_trace_to_object_trace(record)
    assert "wheelsPressure_rr" in frames[0]
    assert "tyreTempInner_fl" not in frames[0]
    assert "accG_vert" not in frames[0]


def test_generated_archive_carries_tier2_dynamic_channels() -> None:
    # #488 Part A: a generated reference archive includes the Tier-2 CSP force/slip columns. The
    # synthetic generator does not model them, so they are 0.0 -> the all-zero guard treats a
    # generated reference as honestly having no measured force/slip signal.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    for name in (
        "slipRatio_fl",
        "slipRatio_rr",
        "slipAngle_fl",
        "slipAngle_rr",
        "mz_fl",
        "mz_rr",
        "fx_fl",
        "fy_rr",
        "dy_fl",
        "dy_rr",
    ):
        assert name in fields
    assert fields[-1] == "dy_rr"
    assert len(fields) == 100
    f0 = archive_trace_to_object_trace(record)[0]
    for name in ("slipRatio_fl", "slipAngle_rr", "mz_fl", "fx_rr", "dy_rr"):
        assert f0[name] == pytest.approx(0.0)


def test_validator_accepts_pre_488_76_field_trace() -> None:
    # #488 Part A: the Tier-2 force/slip channels append AFTER the #490 Tier-1 block; a lap captured
    # between #490 and #488 declares 76 columns and stays schema-v1-valid, converting without the
    # Tier-2 keys.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    record["trace"]["fields"] = list(fields[:76])
    record["trace"]["samples"] = [[row[i] for i in range(76)] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)  # must not raise
    frames = archive_trace_to_object_trace(record)
    assert "accG_vert" in frames[0]
    assert "slipRatio_fl" not in frames[0]
    assert "dy_rr" not in frames[0]


def test_validator_accepts_pre_478_23_field_trace() -> None:
    # #478: chassis/pressure append AFTER rpm; a lap captured between #442 and #478 declares 23
    # columns (legacy + per-wheel + rpm) and stays schema-v1-valid, converting without #478 keys.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    record["trace"]["fields"] = list(fields[:23])
    record["trace"]["samples"] = [[row[i] for i in range(23)] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)  # must not raise
    frames = archive_trace_to_object_trace(record)
    assert "rpm" in frames[0]
    assert "accG_long" not in frames[0]
    assert "wheelsPressure_fl" not in frames[0]


def test_generated_archive_carries_tyres_header() -> None:
    # #478 Part C: the header carries a first-class tyres block (None for a generated reference,
    # which has no real tyre set -> the lakehouse falls back to the setup-hash proxy).
    record = build_archive_record_from_scenario("brake_too_late")
    assert record["tyres"] == {"compoundIndex": None, "name": None}


def test_validator_accepts_old_22_field_schema_v1_trace() -> None:
    # #442: rpm is appended after the #266 fields; archives captured between #266 and #442
    # remain schema-v1-valid and convert without an rpm key.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    keep = list(fields[:22])
    idxs = list(range(22))
    record["trace"]["fields"] = keep
    record["trace"]["samples"] = [[row[i] for i in idxs] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)
    frames = archive_trace_to_object_trace(record)
    assert "rpm" not in frames[0]


def test_validator_accepts_legacy_trace_with_rpm_extension() -> None:
    # #442: the MoTeC importer can carry rpm without claiming the optional #266 wheel channels.
    record = build_archive_record_from_scenario("brake_too_late")
    fields = record["trace"]["fields"]
    keep = list(fields[:10]) + ["rpm"]
    idxs = list(range(10)) + [fields.index("rpm")]
    record["trace"]["fields"] = keep
    record["trace"]["samples"] = [[row[i] for i in idxs] for row in record["trace"]["samples"]]
    validate_lap_archive_record(record)
    frames = archive_trace_to_object_trace(record)
    assert "rpm" in frames[0]
    assert "wheelAngularSpeed_fl" not in frames[0]


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
