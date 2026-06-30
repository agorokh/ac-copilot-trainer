from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.driver_profile import (
    ProfileLoadError,
    build_profile,
    update_profile,
    write_profile,
)


def _archive(
    lap_uuid: str,
    *,
    session_uuid: str,
    lap_ms: int,
    car_id: str = "bmw_z4_gt3",
    track_id: str = "spa",
    exported_at: str = "2026-06-28T00:00:00Z",
) -> dict:
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": lap_uuid,
        "session_uuid": session_uuid,
        "exported_at": exported_at,
        "car": {"id": car_id},
        "track": {"id": track_id, "layout": None},
        "lap": {"lap_n": 1, "lap_ms": lap_ms, "is_pb": True, "is_valid": True},
        "trace": {"fields": ["eMs"], "samples": [[0], [lap_ms]]},
    }


def _write_lap(root: Path, name: str, payload: dict) -> Path:
    path = root / f"lap_{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_profile_builds_session_rollups_pb_and_preserves_preferences(tmp_path: Path) -> None:
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(
        laps,
        "a",
        _archive("lap-a", session_uuid="sess-a", lap_ms=91000, exported_at="2026-06-28T00:00:00Z"),
    )
    _write_lap(
        laps,
        "b",
        _archive("lap-b", session_uuid="sess-b", lap_ms=89000, exported_at="2026-06-29T00:00:00Z"),
    )
    existing = {
        "preferences": {"voice_verbosity": "low"},
        "focus_corners": {"spa": ["T1"]},
    }

    profile = build_profile([laps], driver_id="driver-1", existing=existing, generated_at="stamp")

    assert profile["driver_id"] == "driver-1"
    assert profile["preferences"] == {"voice_verbosity": "low"}
    assert profile["focus_corners"] == {"spa": ["T1"]}
    assert len(profile["session_rollups"]) == 2
    pb = profile["personal_bests"]["bmw_z4_gt3|spa|"]
    assert pb["lap_ms"] == 89000
    assert pb["lap_uuid"] == "lap-b"
    consistency = profile["consistency"]["bmw_z4_gt3|spa|"]
    assert consistency["session_count"] == 2
    assert consistency["valid_laps"] == 2


def test_profile_keeps_compacted_pb_when_raw_archive_was_pruned(tmp_path: Path) -> None:
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(laps, "new", _archive("lap-new", session_uuid="sess-new", lap_ms=90000))
    existing = {
        "session_rollups": {
            "sess-old|bmw_z4_gt3|spa|": {
                "session_uuid": "sess-old",
                "car_id": "bmw_z4_gt3",
                "track_id": "spa",
                "track_layout": None,
                "valid_laps": 1,
                "best_lap_ms": 85000,
                "best_lap_uuid": "lap-old",
                "best_source_file": "lap_old.json",
                "last_exported_at": "2026-06-01T00:00:00Z",
            }
        }
    }

    profile = build_profile([laps], existing=existing, generated_at="stamp")

    pb = profile["personal_bests"]["bmw_z4_gt3|spa|"]
    assert pb["lap_ms"] == 85000
    assert pb["lap_uuid"] == "lap-old"
    assert len(profile["session_rollups"]) == 2


def test_profile_merges_partial_session_without_losing_compacted_best(tmp_path: Path) -> None:
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(laps, "new", _archive("lap-new", session_uuid="sess-a", lap_ms=90000))
    existing = {
        "session_rollups": {
            "sess-a|bmw_z4_gt3|spa|": {
                "session_uuid": "sess-a",
                "car_id": "bmw_z4_gt3",
                "track_id": "spa",
                "track_layout": None,
                "lap_count": 4,
                "valid_laps": 4,
                "best_lap_ms": 85000,
                "median_lap_ms": 87000.0,
                "consistency_ms": 500.0,
                "best_lap_uuid": "lap-old",
                "best_source_file": "lap_old.json",
                "first_exported_at": "2026-06-01T00:00:00Z",
                "last_exported_at": "2026-06-02T00:00:00Z",
            }
        }
    }

    profile = build_profile([laps], existing=existing, generated_at="stamp")

    rollup = profile["session_rollups"]["sess-a|bmw_z4_gt3|spa|"]
    assert rollup["lap_count"] == 4
    assert rollup["valid_laps"] == 4
    assert rollup["best_lap_ms"] == 85000
    assert rollup["best_lap_uuid"] == "lap-old"
    assert rollup["best_source_file"] == "lap_old.json"
    pb = profile["personal_bests"]["bmw_z4_gt3|spa|"]
    assert pb["lap_ms"] == 85000
    assert pb["lap_uuid"] == "lap-old"


def test_profile_keeps_existing_pb_ledger_without_rollup(tmp_path: Path) -> None:
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(laps, "new", _archive("lap-new", session_uuid="sess-new", lap_ms=90000))
    existing = {
        "personal_bests": {
            "bmw_z4_gt3|spa|": {
                "car_id": "bmw_z4_gt3",
                "track_id": "spa",
                "lap_ms": 85000,
                "lap_uuid": "lap-old",
                "session_uuid": "sess-old",
                "source_file": "lap_old.json",
                "exported_at": "2026-06-01T00:00:00Z",
            }
        }
    }

    profile = build_profile([laps], existing=existing, generated_at="stamp")

    pb = profile["personal_bests"]["bmw_z4_gt3|spa|"]
    assert pb["lap_ms"] == 85000
    assert pb["lap_uuid"] == "lap-old"
    assert "sess-old|bmw_z4_gt3|spa|" in profile["session_rollups"]


def test_update_profile_writes_under_journal_driver(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "journal").mkdir()
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(laps, "a", _archive("lap-a", session_uuid="sess-a", lap_ms=91000))

    summary = update_profile([laps], driver_id="driver-1")

    assert summary.personal_bests == 1
    profile_path = tmp_path / "journal" / "driver" / "profile.json"
    assert profile_path.exists()
    assert json.loads(profile_path.read_text(encoding="utf-8"))["driver_id"] == "driver-1"


def test_update_profile_fails_closed_on_invalid_existing_profile(tmp_path: Path) -> None:
    laps = tmp_path / "laps"
    laps.mkdir()
    _write_lap(laps, "a", _archive("lap-a", session_uuid="sess-a", lap_ms=91000))
    profile_path = tmp_path / "journal" / "driver" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ProfileLoadError, match="profile invalid JSON"):
        update_profile([laps], profile_path=profile_path)

    assert profile_path.read_text(encoding="utf-8") == "{not-json"


def test_profile_write_rejects_noncanonical_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "journal").mkdir()
    with pytest.raises(ValueError, match="journal/driver"):
        write_profile({}, "profile.json")
