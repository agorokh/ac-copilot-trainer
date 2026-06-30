from __future__ import annotations

import json
from pathlib import Path

from tools.ai_sidecar.coaching_diagnosis import RootError
from tools.ai_sidecar.coaching_runtime import CoachRuntime, _Anchors
from tools.ai_sidecar.driver_profile import build_profile, load_profile, update_profile
from tools.ai_sidecar.driver_progression import (
    LEVEL_ADVANCED,
    LEVEL_INTERMEDIATE,
    LEVEL_NOVICE,
    build_progression_report,
    cue_policy_from_profile,
)
from tools.ai_sidecar.lap_dynamics import CornerSignature
from tools.ai_sidecar.track_reference import CornerReference


def _write_archive(
    path: Path,
    *,
    lap_uuid: str,
    session_uuid: str,
    lap_ms: int,
    lap_n: int,
    exported_at: str,
    min_speed: float,
    throttle: float = 0.4,
    trail: float = 0.1,
    steer_reversals: float = 4.0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "test",
                "lap_uuid": lap_uuid,
                "session_uuid": session_uuid,
                "exported_at": exported_at,
                "car": {"id": "car-a"},
                "track": {"id": "track-a", "layout": ""},
                "lap": {"lap_n": lap_n, "lap_ms": lap_ms, "is_valid": True},
                "trace": {"fields": ["spline", "speed"], "samples": [[0.0, 100.0]]},
                "corners": [
                    {
                        "label": "T1",
                        "entrySpeed": min_speed + 30.0,
                        "minSpeed": min_speed,
                        "exitSpeed": min_speed + 25.0,
                        "brakePointSpline": 0.2,
                        "trailBrakeRatio": trail,
                        "throttleAvg": throttle,
                        "steerReversals": steer_reversals,
                        "tractionCircleProxy": 0.7,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _corner_history(
    *,
    count: int,
    delta: float,
    trail: float,
    throttle: float,
    steer: float,
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for idx in range(count):
        rows[f"car-a|track-a||corner:{idx}"] = {
            "car_id": "car-a",
            "track_id": "track-a",
            "track_layout": "",
            "corner_index": idx,
            "label": f"T{idx + 1}",
            "session_count": 3,
            "valid_laps": 6,
            "delta_min_speed_kmh": delta,
            "avg_trail_brake_ratio": trail,
            "avg_throttle": throttle,
            "avg_steer_reversals": steer,
        }
    return rows


def _profile(
    *,
    corner_count: int = 4,
    apex_delta: float = -1.0,
    trail: float = 0.1,
    throttle: float = 0.3,
    steer: float = 4.0,
    consistency_ms: float = 5000.0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "driver_id": "driver-a",
        "updated_at": "2026-06-30T12:00:00Z",
        "corner_history": _corner_history(
            count=corner_count,
            delta=apex_delta,
            trail=trail,
            throttle=throttle,
            steer=steer,
        ),
        "consistency": {
            "car-a|track-a|": {
                "session_count": 3,
                "valid_laps": 12,
                "median_session_best_ms": 100000,
                "consistency_ms": consistency_ms,
            }
        },
    }


def test_profile_builds_session_pb_and_corner_history(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    lap_dir = tmp_path / "journal" / "laps"
    lap_dir.mkdir(parents=True)
    _write_archive(
        lap_dir / "lap_001.json",
        lap_uuid="lap-1",
        session_uuid="session-1",
        lap_ms=91000,
        lap_n=1,
        exported_at="2026-06-01T10:00:00Z",
        min_speed=80.0,
    )
    _write_archive(
        lap_dir / "lap_002.json",
        lap_uuid="lap-2",
        session_uuid="session-2",
        lap_ms=90000,
        lap_n=2,
        exported_at="2026-06-02T10:00:00Z",
        min_speed=84.0,
        throttle=0.5,
        trail=0.2,
        steer_reversals=2.0,
    )

    summary = update_profile([lap_dir], generated_at="2026-06-30T12:00:00Z")
    profile = load_profile(summary.path)

    assert summary.sessions == 2
    assert profile["personal_bests"]["car-a|track-a|"]["lap_uuid"] == "lap-2"
    corner = profile["corner_history"]["car-a|track-a||corner:0"]
    assert corner["valid_laps"] == 2
    assert corner["delta_min_speed_kmh"] == 4.0
    assert corner["avg_throttle"] == 0.45


def test_existing_preferences_and_focus_survive_profile_rebuild(tmp_path: Path) -> None:
    lap_dir = tmp_path / "laps"
    lap_dir.mkdir()
    _write_archive(
        lap_dir / "lap_001.json",
        lap_uuid="lap-1",
        session_uuid="session-1",
        lap_ms=91000,
        lap_n=1,
        exported_at="2026-06-01T10:00:00Z",
        min_speed=80.0,
    )
    profile = build_profile(
        [lap_dir],
        existing={"preferences": {"verbosity": "low"}, "focus_corners": {"track-a": ["T1"]}},
    )

    assert profile["preferences"] == {"verbosity": "low"}
    assert profile["focus_corners"] == {"track-a": ["T1"]}


def test_corrupt_profile_loads_as_safe_default(tmp_path: Path) -> None:
    profile_path = tmp_path / "journal" / "driver" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("{not-json", encoding="utf-8")

    profile = load_profile(profile_path, driver_id="driver-safe")
    report = build_progression_report(profile)

    assert profile["driver_id"] == "driver-safe"
    assert report["level"] == "unknown"
    assert report["cue_policy"]["lap_budget"] == 4


def test_novice_policy_reduces_density_and_suppresses_trail_brake_roots() -> None:
    policy = cue_policy_from_profile(_profile(apex_delta=-2.0, trail=0.05, throttle=0.2))

    assert policy.level == LEVEL_NOVICE
    assert policy.lap_budget == 2
    assert policy.assess_laps == 3
    assert RootError.NO_TRAIL not in policy.allowed_roots
    assert policy.allows(RootError.SLOW_APEX)


def test_progression_report_graduates_first_drill_and_recommends_next() -> None:
    report = build_progression_report(
        _profile(apex_delta=4.0, trail=0.08, throttle=0.2, consistency_ms=2000.0)
    )

    assert report["skills"]["apex_speed"]["level"] == LEVEL_INTERMEDIATE
    assert report["drills"][0]["status"] == "graduated"
    assert report["next_drill"]["id"] == "throttle-to-apex"
    assert report["trends"][0]["trend"] == "improving"


def test_advanced_profile_graduates_curriculum() -> None:
    report = build_progression_report(
        _profile(
            corner_count=8,
            apex_delta=3.0,
            trail=0.4,
            throttle=0.7,
            steer=1.0,
            consistency_ms=1000.0,
        )
    )

    assert report["level"] == LEVEL_ADVANCED
    assert report["next_drill"] is None
    assert {row["status"] for row in report["drills"]} == {"graduated"}


def _sig(**over: object) -> CornerSignature:
    base = dict(
        index=0,
        entry_i=0,
        apex_i=10,
        exit_i=20,
        apex_spline=0.30,
        min_speed_kmh=80.0,
        entry_speed_kmh=180.0,
        exit_speed_kmh=150.0,
        peak_lat_g=1.4,
        peak_brake_g=1.2,
        peak_accel_g=0.8,
        brake_point_spline=0.250,
        brake_to_apex_m=60.0,
        throttle_on_spline=0.360,
        apex_to_throttle_m=30.0,
        trail_brake_frac=0.50,
        max_abs_steer=0.6,
        direction="right",
    )
    base.update(over)
    return CornerSignature(**base)


def test_runtime_skill_gate_suppresses_no_trail_for_novice_profile() -> None:
    ref = CornerReference(
        index=0,
        apex_spline=0.30,
        spline_lo=0.20,
        spline_hi=0.40,
        optimal_apex_kmh=80.0,
    )
    runtime = CoachRuntime(
        refs=[ref],
        ref_sigs={0: _sig()},
        anchors={0: _Anchors(brake=0.20, turn_in=0.22, apex=0.30)},
        cue_policy=cue_policy_from_profile(_profile(apex_delta=-2.0, trail=0.05)),
    )
    state = runtime._pass[0]
    state.active = True
    state.entry_count = 8
    state.trail_count = 0
    state.brake_onset_spline = 0.25
    state.min_speed_kmh = 80.0
    state.throttle_on_spline = 0.36

    runtime._finalize_pass(ref)

    assert runtime.ledger.state(0).root is RootError.NONE
