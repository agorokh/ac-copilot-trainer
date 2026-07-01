"""Unit tests for tools.tt_ingest.tt_normalize (issue #353)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ac_harness.reference_lap import validate_lap_archive_record
from tools.tt_ingest.tt_normalize import (
    DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
    INDEX_SCHEMA_VERSION,
    TT_CURRICULUM_FORMAT,
    TT_REFERENCE_IMPORT_FORMAT,
    TTNormalizeError,
    build_harness_curriculum,
    build_reference_archive,
    build_sessions_index,
    normalize_session,
    normalize_sessions,
    reference_coverage,
    reference_frames_from_payload,
    split_session_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"
FIXTURES = Path(__file__).parent / "fixtures"


def _sessions() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["sessions"]


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_split_session_id() -> None:
    assert split_session_id("uid-1#sess-aaa") == ("uid-1", "sess-aaa")
    assert split_session_id("no-sep") == (None, None)
    assert split_session_id(123) == (None, None)


def test_normalize_session_full_row() -> None:
    row = normalize_session(_sessions()[0])
    assert row["session_id"] == "fake-uid-001#sess-aaa"
    assert row["uid"] == "fake-uid-001"
    assert row["session_key"] == "sess-aaa"
    assert row["car_id"] == "syn_mercedes_w09"
    assert row["car_name"] == "Mercedes W09"
    assert row["track_id"] == "ks_red_bull_ring"
    assert row["best_lap_ms"] == 64321
    assert row["lap_count"] == 12
    assert row["game_name"] == "Assetto Corsa"


def test_normalize_session_lifts_conditions() -> None:
    row = normalize_session(_sessions()[0])
    cond = row["conditions"]
    assert cond["airTemp"] == 24.0
    assert cond["tyreCompound"] == "Pirelli SuperSoft (SS)"
    assert cond["carSetupName"] == "quali"
    assert cond["isFixedSetup"] is False
    assert cond["trackGrip"] == 0.98


def test_normalize_session_degrades_missing_fields() -> None:
    row = normalize_session(_sessions()[2])  # minimal session
    assert row["car_id"] == "ks_abarth500"
    assert row["best_lap_ms"] is None
    assert row["lap_count"] is None
    assert row["car_name"] is None
    # conditions keys all present but None when lap_attributes absent
    assert row["conditions"]["airTemp"] is None
    assert set(row["conditions"]).issuperset({"airTemp", "tyreCompound", "trackGrip"})


def test_normalize_session_uid_from_user_id_when_id_unusable() -> None:
    row = normalize_session({"car_id": "c", "user_id": "uid-only"})
    assert row["uid"] == "uid-only"
    assert row["session_id"] is None


def test_normalize_session_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        normalize_session("not a mapping")


def test_normalize_sessions_skips_non_mappings() -> None:
    rows = normalize_sessions([_sessions()[0], "garbage", 7, _sessions()[1]])
    assert len(rows) == 2


def test_build_sessions_index() -> None:
    rows = normalize_sessions(_sessions())
    index = build_sessions_index(rows, generated_at="2026-06-28T00:00:00Z")
    assert index["index_schema_version"] == INDEX_SCHEMA_VERSION
    assert index["session_count"] == 3
    assert index["generated_at"] == "2026-06-28T00:00:00Z"
    assert len(index["sessions"]) == 3


def _tt_reference_payload(start: float, end: float, *, samples: int = 16) -> dict:
    frames = []
    for i in range(samples):
        t = i / (samples - 1)
        dist = start + (end - start) * t
        frames.append(
            {
                "dist": round(dist, 6),
                "brak": 0.7 if 0.18 <= dist <= 0.28 else 0.0,
                "gear": 3 if dist < 0.4 else 4,
                "Kmh": 155.0 - 45.0 * max(0.0, 1.0 - abs(dist - 0.24) / 0.12)
                if 0.12 <= dist <= 0.36
                else 155.0,
                "lTime": round(71000.0 * dist, 3),
                "ovSteer": 0,
                "steer": 0.35 if 0.12 <= dist <= 0.36 else 0.02,
                "throt": 0.1 if 0.18 <= dist <= 0.28 else 1.0,
                "unSteer": 0,
                "useGrip": 0,
                "X": 1000.0 * dist,
                "Y": 120.0 * dist * dist,
                "distM": None,
            }
        )
    return {
        "success": True,
        "status": 200,
        "data": {
            "session": {
                "id": "own-uid#sess-full",
                "session_id": "own-uid#sess-full",
                "game_id": "assettoCorsa",
                "car": "ks_porsche_911_gt3_r_2016",
                "track_id": "magione",
                "lap_number": 5,
            },
            "referenceLap": {
                "user_id": "ref-uid",
                "session_key": "ref-session",
                "lap_number": 5,
                "lap_time": "71000",
            },
            "telemetry": {
                "telemetry": {
                    "reference": frames,
                    "user": frames,
                },
                "format": "sanitized-test",
            },
        },
    }


def _session_payload(
    start: float,
    end: float,
    *,
    session_key: str,
    car: object = "ks_porsche_911_gt3_r_2016",
    track_id: str = "magione",
) -> dict:
    payload = _tt_reference_payload(start, end)
    session = payload["data"]["session"]
    session["id"] = f"own-uid#{session_key}"
    session["session_id"] = f"own-uid#{session_key}"
    session["car"] = car
    session["track_id"] = track_id
    return payload


def test_reference_frames_from_payload_maps_tt_channels() -> None:
    frame = reference_frames_from_payload(_tt_reference_payload(0.4, 0.41, samples=2))[0]
    assert frame["spline"] == pytest.approx(0.4)
    assert frame["speed"] == pytest.approx(155.0)
    assert frame["eMs"] == pytest.approx(28400.0)
    assert frame["px"] == pytest.approx(400.0)
    assert frame["py"] == 0.0
    assert frame["pz"] == pytest.approx(19.2)


def test_reference_frames_reject_malformed_services_envelope() -> None:
    with pytest.raises(TTNormalizeError, match="missing data object"):
        reference_frames_from_payload({"success": True})


def test_reference_frames_clamp_minor_pedal_noise() -> None:
    payload = _tt_reference_payload(0.4, 0.41, samples=2)
    payload["data"]["telemetry"]["telemetry"]["reference"][0]["throt"] = 1.00001
    payload["data"]["telemetry"]["telemetry"]["reference"][0]["brak"] = -0.00001

    frame = reference_frames_from_payload(payload)[0]

    assert frame["throttle"] == 1.0
    assert frame["brake"] == 0.0


def test_build_reference_archive_rejects_single_segment_window() -> None:
    with pytest.raises(TTNormalizeError, match="partial"):
        build_reference_archive([_tt_reference_payload(0.265, 0.359, samples=20)])


def test_build_reference_archive_allows_partial_with_marker() -> None:
    record = build_reference_archive(
        [_tt_reference_payload(0.265, 0.359, samples=20)],
        allow_partial=True,
        exported_at="2026-06-30T00:00:00Z",
    )

    validate_lap_archive_record(record)
    assert record["import_format"] == TT_REFERENCE_IMPORT_FORMAT
    meta = record["generator"]["tt_reference"]
    assert meta["partial"] is True
    assert meta["coverage"] < DEFAULT_REFERENCE_COVERAGE_THRESHOLD


def test_build_reference_archive_stitches_full_lap_windows() -> None:
    record = build_reference_archive(
        [
            _tt_reference_payload(0.0, 0.5, samples=26),
            _tt_reference_payload(0.5, 1.0, samples=26),
        ],
        exported_at="2026-06-30T00:00:00Z",
    )

    validate_lap_archive_record(record)
    assert record["car"]["id"] == "ks_porsche_911_gt3_r_2016"
    assert record["track"]["id"] == "magione"
    assert record["lap"]["lap_ms"] == 71000
    assert record["generator"]["decision_issue"] == 353
    assert record["generator"]["tt_reference"]["partial"] is False
    assert record["generator"]["tt_reference"]["payload_count"] == 2
    assert record["generator"]["tt_reference"]["max_spline_gap"] == pytest.approx(0.08)
    assert record["generator"]["tt_reference"]["observed_max_spline_gap"] < 0.08
    assert record["generator"]["tt_reference"]["reference_lap_ms"] == 71000
    assert record["generator"]["tt_reference"]["lap_time_mismatch_ms"] == 0
    assert record["corners"]  # non-vacuous for the M0 observer path


def test_build_reference_archive_uses_reference_lap_identity() -> None:
    first = _tt_reference_payload(0.0, 0.5, samples=26)
    second = _tt_reference_payload(0.5, 1.0, samples=26)
    for payload in (first, second):
        payload["data"]["session"]["lap_number"] = 5
        payload["data"]["referenceLap"]["lap_number"] = 4
        payload["data"]["referenceLap"]["session_key"] = "pro-reference-session"

    record = build_reference_archive([first, second], exported_at="2026-06-30T00:00:00Z")

    assert record["lap"]["lap_n"] == 4
    assert record["lap"]["lap_ms"] == 71000


def test_build_reference_archive_rejects_incomplete_lap_time() -> None:
    payload = _tt_reference_payload(0.02, 0.98, samples=80)

    with pytest.raises(TTNormalizeError, match="reference_lap_ms=71000"):
        build_reference_archive([payload], max_spline_gap=0.05)


def test_build_reference_archive_rejects_spatial_gaps_even_with_wide_range() -> None:
    with pytest.raises(TTNormalizeError, match="partial"):
        build_reference_archive(
            [
                _tt_reference_payload(0.0, 0.2, samples=12),
                _tt_reference_payload(0.8, 1.0, samples=12),
            ],
        )


def test_build_reference_archive_rejects_single_corner_sized_hole() -> None:
    with pytest.raises(TTNormalizeError, match="partial"):
        build_reference_archive(
            [
                _tt_reference_payload(0.0, 0.46, samples=30),
                _tt_reference_payload(0.55, 1.0, samples=30),
            ],
        )


def test_reference_coverage_counts_start_finish_wrap_as_closed_loop() -> None:
    frames = reference_frames_from_payload(_tt_reference_payload(0.02, 0.98, samples=80))

    coverage = reference_coverage(frames, max_spline_gap=0.05)

    assert coverage.partial is False
    assert coverage.coverage == pytest.approx(1.0)


def test_build_reference_archive_marks_lap_time_mismatch_partial() -> None:
    record = build_reference_archive(
        [_tt_reference_payload(0.02, 0.98, samples=80)],
        max_spline_gap=0.05,
        allow_partial=True,
        exported_at="2026-06-30T00:00:00Z",
    )

    assert record["generator"]["tt_reference"]["partial"] is True
    assert record["generator"]["tt_reference"]["coverage"] == pytest.approx(1.0)
    assert record["generator"]["tt_reference"]["reference_lap_ms"] == 71000
    assert record["generator"]["tt_reference"]["trace_lap_ms"] == 69580
    assert record["generator"]["tt_reference"]["lap_time_mismatch_ms"] == 1420


def test_build_reference_archive_resolves_car_id_from_object() -> None:
    record = build_reference_archive(
        [
            _session_payload(
                0.0,
                0.5,
                session_key="sess-object-car",
                car={"car_id": "ks_audi_r8_lms", "name": "Audi R8 LMS"},
            ),
            _session_payload(
                0.5,
                1.0,
                session_key="sess-object-car",
                car={"car_id": "ks_audi_r8_lms", "name": "Audi R8 LMS"},
            ),
        ],
        exported_at="2026-06-30T00:00:00Z",
    )

    assert record["car"]["id"] == "ks_audi_r8_lms"


def test_build_reference_archive_rejects_mixed_sessions() -> None:
    with pytest.raises(TTNormalizeError, match="one session/lap"):
        build_reference_archive(
            [
                _session_payload(0.0, 0.5, session_key="sess-a"),
                _session_payload(0.5, 1.0, session_key="sess-b"),
            ],
        )


def _curriculum_bundle() -> dict:
    return {
        "reference_lap": _load_fixture("tt_services_dynamic_reference.json")["lap"],
        "dynamic_reference": ["ref-uid-002", "20220611194228"],
        "advice_reference": ["fake-uid-001", "20260629005756", "theoreticalBestRef"],
        "segments": [
            {"segment": 3, "advice_raw": _load_fixture("tt_services_advice.json")},
            {"segment": 4, "stories": [{"diagnosis": "Good corner", "time_loss": 0.0}]},
        ],
    }


def test_build_harness_curriculum_maps_tt_advice_to_objective() -> None:
    curriculum = build_harness_curriculum(
        _curriculum_bundle(),
        session_payload=_load_fixture("tt_services_last_session.json"),
        exported_at="2026-06-30T00:00:00Z",
    )

    assert curriculum["format"] == TT_CURRICULUM_FORMAT
    assert curriculum["session"]["car_id"] == "ks_porsche_911_gt3_r_2016"
    assert curriculum["session"]["track_id"] == "magione"
    assert curriculum["reference"]["username"] == "Reference Driver"
    assert curriculum["summary"] == {
        "segments": 2,
        "objectives": 1,
        "total_time_loss_s": 0.001,
        "primary_objective_id": "tt-c03-coaching-diagnosis-rotation-insufficient-1",
    }
    objective = curriculum["objectives"][0]
    assert objective["corner"] == 3
    assert objective["skill"] == "rotation"
    assert objective["intent"] == "improve_rotation_to_apex"
    assert objective["diagnosis_key"] == "coaching.diagnosis.rotation_insufficient"
    assert objective["highlight_norm"] == {
        "start": 0.04054,
        "end": 0.073504,
    }
    assert objective["targets"]["reference_segment_time_ms"] is None
    assert objective["targets"]["driver_segment_time_ms"] == pytest.approx(10815.7)
    assert objective["targets"]["segment_delta_ms"] is None
    assert objective["harness"]["acceptance"]["baseline_s"] == pytest.approx(0.001)


def test_build_harness_curriculum_uses_unwrapped_session_timing() -> None:
    session = _load_fixture("tt_services_last_session.json")["data"]["session"]

    curriculum = build_harness_curriculum(_curriculum_bundle(), session_payload=session)

    objective = curriculum["objectives"][0]
    assert objective["targets"]["driver_segment_time_ms"] == pytest.approx(10815.7)
    assert objective["targets"]["segment_delta_ms"] is None


def test_build_harness_curriculum_uses_reference_times_when_advice_reference_matches() -> None:
    bundle = _curriculum_bundle()
    bundle["advice_reference"] = list(bundle["dynamic_reference"])

    curriculum = build_harness_curriculum(
        bundle,
        session_payload=_load_fixture("tt_services_last_session.json"),
    )

    objective = curriculum["objectives"][0]
    assert objective["targets"]["reference_segment_time_ms"] == pytest.approx(8765.1)
    assert objective["targets"]["segment_delta_ms"] == pytest.approx(2050.6)


def test_build_harness_curriculum_filters_non_actionable_stories() -> None:
    curriculum = build_harness_curriculum(_curriculum_bundle(), min_time_loss_s=0.01)

    assert curriculum["objectives"] == []
    assert curriculum["summary"]["objectives"] == 0


def test_build_harness_curriculum_falls_back_when_advice_raw_is_malformed() -> None:
    bundle = _curriculum_bundle()
    bundle["segments"][0] = {
        "segment": 3,
        "advice_raw": {"success": True, "data": []},
        "stories": [
            {
                "diagnosis": "Turn in earlier",
                "diagnosis_key": "coaching.diagnosis.rotation_insufficient",
                "time_loss": 0.2,
            }
        ],
    }

    curriculum = build_harness_curriculum(
        bundle,
        session_payload=_load_fixture("tt_services_last_session.json"),
    )

    assert curriculum["summary"]["objectives"] == 1
    assert curriculum["objectives"][0]["time_loss_s"] == pytest.approx(0.2)
