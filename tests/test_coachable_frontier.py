"""Issue #529 P5: alien envelope → bounded, human-usable Coach v2 targets."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.test_alien_line import _circle_line, _l3_plant, _write_fast_lane
from tools.ac_harness.alien_line import build_alien_line_artifact, save_alien_line_artifact
from tools.ac_harness.plant_id import REQUIRED_PLANT_CONSTANTS
from tools.ai_sidecar.coachable_frontier import FrontierError, load_verified_alien_evidence
from tools.ai_sidecar.coaching_runtime import build_coach_runtime

_REFERENCE = Path(__file__).parent / "fixtures" / "magione_gt3r_reference.json"
_EXPECTED_PROVENANCE = {
    "alien_expected_plant_sha12": "abc123def456",  # pragma: allowlist secret
    "alien_expected_fast_lane_sha12": "def456abc123",  # pragma: allowlist secret
}


def _reference() -> dict:
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def _alien_artifact(reference: dict, *, speed_scale: float = 1.08) -> dict:
    trace = reference["trace"]
    field_index = {field: index for index, field in enumerate(trace["fields"])}
    return {
        "schema_version": 1,
        "car_id": reference["car"]["id"],
        "track_id": reference["track"]["id"],
        "layout": reference["track"].get("layout"),
        "plant_provenance": {"sha12": "abc123def456"},  # pragma: allowlist secret
        "fast_lane_sha12": "def456abc123",  # pragma: allowlist secret
        "line": [
            [row[field_index["px"]], row[field_index["py"]], row[field_index["pz"]]]
            for row in trace["samples"]
        ],
        "v_target_mps": [row[field_index["speed"]] / 3.6 * speed_scale for row in trace["samples"]],
        "corridor": {"max_ay_utilisation": 0.99},
    }


def _same_combo_profile(reference: dict) -> dict:
    baseline = build_coach_runtime(reference)
    assert baseline is not None
    car_id = reference["car"]["id"]
    track_id = reference["track"]["id"]
    return {
        "schema_version": 1,
        "driver_id": "local-driver",
        "corner_history": {
            f"{car_id}|{track_id}||corner:{index}": {
                "car_id": car_id,
                "track_id": track_id,
                "track_layout": "",
                "corner_index": index,
                "valid_laps": 4,
                "best_min_speed_kmh": signature.min_speed_kmh,
                "delta_min_speed_kmh": 1.0,
                "avg_steer_reversals": 1.0,
                "corner_samples_by_lap_uuid": {
                    f"lap-{index}": {
                        "min_speed_kmh": signature.min_speed_kmh,
                        "brake_point_spline": signature.brake_point_spline,
                        "steer_reversals": 1.0,
                    }
                },
            }
            for index, signature in baseline.ref_sigs.items()
        },
    }


def test_frontier_changes_only_minimum_speed_signature() -> None:
    reference = _reference()
    baseline = build_coach_runtime(reference, driver_profile=_same_combo_profile(reference))
    runtime = build_coach_runtime(
        reference,
        driver_profile=_same_combo_profile(reference),
        alien_line_artifact=_alien_artifact(reference),
        **_EXPECTED_PROVENANCE,
    )
    assert baseline is not None and runtime is not None
    assert runtime.frontier["active"] is True
    assert runtime.frontier["source"] == "alien_coachable_frontier"

    for corner_index, signature in runtime.ref_sigs.items():
        before = asdict(baseline.ref_sigs[corner_index])
        after = asdict(signature)
        assert after.pop("min_speed_kmh") > before.pop("min_speed_kmh")
        assert after == before, "alien evidence must not replace demonstrated driving technique"


def test_frontier_gain_is_bounded_by_driver_level() -> None:
    reference = _reference()
    profile = _same_combo_profile(reference)
    runtime = build_coach_runtime(
        reference,
        driver_profile=profile,
        alien_line_artifact=_alien_artifact(reference, speed_scale=1.25),
        **_EXPECTED_PROVENANCE,
    )
    assert runtime is not None
    assert runtime.cue_policy.level == "novice"
    for corner in runtime.frontier["corners"]:
        assert corner["target_kmh"] == round(corner["driver_best_kmh"] + 2.0, 1)


def test_steering_corrections_reduce_the_personalized_step() -> None:
    reference = _reference()
    profile = _same_combo_profile(reference)
    for row in profile["corner_history"].values():
        row["avg_steer_reversals"] = 8.0
        for sample in row["corner_samples_by_lap_uuid"].values():
            sample["steer_reversals"] = 8.0
    runtime = build_coach_runtime(
        reference,
        driver_profile=profile,
        alien_line_artifact=_alien_artifact(reference, speed_scale=1.25),
        **_EXPECTED_PROVENANCE,
    )

    assert runtime is not None
    assert {corner["gain_cap_kmh"] for corner in runtime.frontier["corners"]} == {1.0}


def test_wrong_combo_fails_closed_with_explicit_reason() -> None:
    reference = _reference()
    artifact = _alien_artifact(reference)
    artifact["track_id"] = "wrong-track"

    baseline = build_coach_runtime(reference, driver_profile=_same_combo_profile(reference))
    runtime = build_coach_runtime(
        reference,
        driver_profile=_same_combo_profile(reference),
        alien_line_artifact=artifact,
        **_EXPECTED_PROVENANCE,
    )

    assert baseline is not None and runtime is not None
    assert runtime.frontier["active"] is False
    assert runtime.frontier["source"] == "reference"
    assert runtime.frontier["reason"].startswith("alien_combo_mismatch")
    assert runtime.ref_sigs == baseline.ref_sigs


def test_profile_corner_indices_are_ignored_in_favor_of_brake_geometry() -> None:
    reference = _reference()
    profile = _same_combo_profile(reference)
    rows = list(profile["corner_history"].values())
    for row, reversed_index in zip(rows, reversed(range(len(rows))), strict=True):
        row["corner_index"] = reversed_index

    runtime = build_coach_runtime(
        reference,
        driver_profile=profile,
        alien_line_artifact=_alien_artifact(reference),
        **_EXPECTED_PROVENANCE,
    )

    assert runtime is not None
    assert runtime.frontier["active"] is True
    assert [corner["corner_index"] for corner in runtime.frontier["corners"]] == list(
        range(len(rows))
    )


def test_unverified_envelope_fails_closed() -> None:
    reference = _reference()
    artifact = _alien_artifact(reference)
    artifact["corridor"]["max_ay_utilisation"] = 1.2

    runtime = build_coach_runtime(
        reference,
        driver_profile=_same_combo_profile(reference),
        alien_line_artifact=artifact,
        **_EXPECTED_PROVENANCE,
    )

    assert runtime is not None
    assert runtime.frontier["active"] is False
    assert runtime.frontier["reason"].startswith("alien_envelope_unverified")


def test_driver_above_alien_ceiling_keeps_reference_for_every_corner() -> None:
    reference = _reference()
    profile = _same_combo_profile(reference)
    first_row = next(iter(profile["corner_history"].values()))
    first_row["best_min_speed_kmh"] = 400.0
    next(iter(first_row["corner_samples_by_lap_uuid"].values()))["min_speed_kmh"] = 400.0

    runtime = build_coach_runtime(
        reference,
        driver_profile=profile,
        alien_line_artifact=_alien_artifact(reference),
        **_EXPECTED_PROVENANCE,
    )

    assert runtime is not None
    assert runtime.frontier["active"] is False
    assert runtime.frontier["reason"].startswith("driver_at_or_above_alien_ceiling")
    assert all(ref.coachable_apex_kmh is None for ref in runtime.refs)


def test_missing_driver_history_reports_reference_fallback() -> None:
    reference = _reference()
    runtime = build_coach_runtime(
        reference,
        alien_line_artifact=_alien_artifact(reference),
        **_EXPECTED_PROVENANCE,
    )

    assert runtime is not None
    assert runtime.frontier == {
        "configured": True,
        "active": False,
        "source": "reference",
        "reason": "no_same_combo_driver_corner_history",
        "driver_level": "unknown",
        "plant_sha12": "abc123def456",  # pragma: allowlist secret
        "fast_lane_sha12": "def456abc123",  # pragma: allowlist secret
        "corners": [],
    }


def test_missing_artifact_path_reports_fallback_without_disabling_runtime(tmp_path: Path) -> None:
    runtime = build_coach_runtime(_reference(), alien_line_path=tmp_path / "missing.json")

    assert runtime is not None
    assert runtime.frontier["active"] is False
    assert runtime.frontier["source"] == "reference"
    assert runtime.frontier["reason"] == "alien_artifact_unreadable"


def _write_external_evidence(tmp_path: Path) -> tuple[Path, Path]:
    plant = _l3_plant()
    points = _circle_line()
    ac_root = tmp_path / "ac"
    lane_path = ac_root / "content" / "tracks" / "trk" / "ai" / "fast_lane.ai"
    lane_path.parent.mkdir(parents=True)
    _write_fast_lane(lane_path, points, [6.0] * len(points), [6.0] * len(points))
    plant_artifact = {
        "schema_version": 3,
        "created_utc": "2026-07-22T00:00:00Z",
        "car_id": "car_a",
        "track_id": "trk",
        "layout": None,
        "setup": None,
        "constants": {key: 1.0 for key in REQUIRED_PLANT_CONSTANTS},
        "ggv": {"ok": True, "model": plant.to_dict()},
    }
    plant_dir = tmp_path / "plant_id"
    plant_dir.mkdir()
    (plant_dir / "car_a__trk.json").write_text(json.dumps(plant_artifact), encoding="utf-8")
    artifact = build_alien_line_artifact(
        points,
        lane_path,
        plant,
        plant_artifact,
        car_id="car_a",
        track_id="trk",
        iters=20,
    )
    return save_alien_line_artifact(tmp_path, artifact), ac_root


def test_disk_evidence_is_reverified_against_current_sources(tmp_path: Path) -> None:
    artifact_path, ac_root = _write_external_evidence(tmp_path)

    artifact, plant_sha, lane_sha = load_verified_alien_evidence(
        artifact_path, combo=("car_a", "trk", ""), ac_root=ac_root
    )

    assert artifact["car_id"] == "car_a"
    assert plant_sha == artifact["plant_provenance"]["sha12"]
    assert lane_sha == artifact["fast_lane_sha12"]


def test_tampered_speed_profile_is_rejected_despite_unchanged_source_hashes(tmp_path: Path) -> None:
    artifact_path, ac_root = _write_external_evidence(tmp_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["v_target_mps"] = [speed * 3.0 for speed in payload["v_target_mps"]]
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FrontierError, match="alien_content_revalidation_failed"):
        load_verified_alien_evidence(artifact_path, combo=("car_a", "trk", ""), ac_root=ac_root)
