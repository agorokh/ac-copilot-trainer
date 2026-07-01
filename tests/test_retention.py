from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.coaching_lake.retention import (
    RetentionPolicy,
    apply_retention,
    plan_retention,
)
from tools.coaching_lake.retention import (
    main as retention_main,
)


def _archive(
    lap_uuid: str,
    *,
    exported_at: str,
    is_pb: bool = False,
    source: str = "in_game",
    import_format: str | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "source": source,
        "import_format": import_format,
        "lap_uuid": lap_uuid,
        "session_uuid": "sess",
        "exported_at": exported_at,
        "car": {"id": "bmw_z4_gt3"},
        "track": {"id": "spa"},
        "lap": {"lap_n": 1, "lap_ms": 90000, "is_pb": is_pb, "is_valid": True},
        "trace": {"fields": ["eMs"], "samples": [[0], [90000]]},
    }


def _write_lap(root: Path, name: str, payload: dict) -> Path:
    path = root / f"lap_{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_lap_retention_deletes_only_unprotected_candidates(tmp_path: Path) -> None:
    laps = tmp_path / "journal" / "laps"
    profile_path = tmp_path / "journal" / "driver" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    laps.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "personal_bests": {"bmw_z4_gt3|spa|": {"lap_uuid": "lap-profile"}},
            }
        ),
        encoding="utf-8",
    )
    eligible = _write_lap(
        laps,
        "eligible",
        _archive("lap-eligible", exported_at="2026-01-01T00:00:00Z"),
    )
    protected_pb = _write_lap(
        laps,
        "pb",
        _archive("lap-pb", exported_at="2026-01-02T00:00:00Z", is_pb=True),
    )
    protected_ref = _write_lap(
        laps,
        "ref",
        _archive(
            "lap-ref",
            exported_at="2026-01-03T00:00:00Z",
            source="imported",
            import_format="motec_csv",
        ),
    )
    protected_pin = _write_lap(
        laps,
        "pin",
        _archive("lap-pin", exported_at="2026-01-04T00:00:00Z"),
    )
    protected_pin.with_suffix(".pin").write_text("manual", encoding="utf-8")
    protected_profile = _write_lap(
        laps,
        "profile",
        _archive("lap-profile", exported_at="2026-01-05T00:00:00Z"),
    )

    plan = plan_retention(
        lap_dir=laps,
        policy=RetentionPolicy(max_lap_files=3),
        profile_path=profile_path,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [eligible]
    protected_paths = {item.path for item in plan.protected}
    assert {protected_pb, protected_ref, protected_pin, protected_profile} <= protected_paths

    result = apply_retention(plan)
    assert result.deleted == 1
    assert not eligible.exists()
    assert protected_pb.exists()
    assert protected_ref.exists()
    assert protected_pin.exists()
    assert protected_profile.exists()


def test_lap_retention_fails_closed_when_profile_is_invalid(tmp_path: Path) -> None:
    laps = tmp_path / "journal" / "laps"
    profile_path = tmp_path / "journal" / "driver" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    laps.mkdir(parents=True)
    profile_path.write_text("{not-json", encoding="utf-8")
    _write_lap(laps, "eligible", _archive("lap-eligible", exported_at="2026-01-01T00:00:00Z"))

    with pytest.raises(ValueError, match="profile invalid JSON"):
        plan_retention(
            lap_dir=laps,
            policy=RetentionPolicy(max_lap_files=0),
            profile_path=profile_path,
            now=datetime(2026, 6, 30, tzinfo=UTC),
        )


def test_lap_retention_age_cap_is_dry_run_until_apply(tmp_path: Path) -> None:
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    old = _write_lap(laps, "old", _archive("lap-old", exported_at="2026-01-01T00:00:00Z"))
    new = _write_lap(laps, "new", _archive("lap-new", exported_at="2026-06-29T00:00:00Z"))

    plan = plan_retention(
        lap_dir=laps,
        policy=RetentionPolicy(max_lap_age_days=30),
        profile_path=None,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [old]
    assert old.exists()
    assert new.exists()


def test_retention_rejects_negative_caps(tmp_path: Path) -> None:
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)

    with pytest.raises(ValueError, match="max_lap_age_days must be non-negative"):
        RetentionPolicy(max_lap_age_days=-1)
    with pytest.raises(SystemExit) as exc_info:
        retention_main(["--lap-dir", str(laps), "--max-lap-age-days", "-1"])
    assert exc_info.value.code == 2


def test_tt_retention_excludes_indexes_and_honors_pins(tmp_path: Path) -> None:
    tt = tmp_path / "journal" / "tt"
    raw_dir = tt / "assettoCorsa" / "car" / "spa" / "sess"
    raw_dir.mkdir(parents=True)
    delete_me = raw_dir / "session.json"
    keep_me = raw_dir / "coaching_lap1.json"
    curriculum = raw_dir / "curriculum_lap1.json"
    index = tt / "index.json"
    sessions_index = tt / "sessions_index.json"
    delete_me.write_text('{"raw":1}', encoding="utf-8")
    keep_me.write_text('{"raw":2}', encoding="utf-8")
    curriculum.write_text('{"derived":true}', encoding="utf-8")
    keep_me.with_suffix(".pin").write_text("manual", encoding="utf-8")
    index.write_text('{"derived":true}', encoding="utf-8")
    sessions_index.write_text('{"derived":true}', encoding="utf-8")
    old = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    os.utime(delete_me, (old, old))
    os.utime(keep_me, (old + 1, old + 1))

    plan = plan_retention(
        tt_dir=tt,
        policy=RetentionPolicy(max_tt_files=1),
        profile_path=None,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [delete_me]
    assert index not in {item.path for item in plan.items}
    assert curriculum not in {item.path for item in plan.items}
    result = apply_retention(plan)
    assert result.invalidated_indexes == 2
    assert not delete_me.exists()
    assert keep_me.exists()
    assert curriculum.exists()
    assert not index.exists()
    assert not sessions_index.exists()


def test_tt_retention_cascades_curriculum_when_source_is_deleted(tmp_path: Path) -> None:
    tt = tmp_path / "journal" / "tt"
    raw_dir = tt / "assettoCorsa" / "car" / "spa" / "sess"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "coaching_lap5.json"
    curriculum = raw_dir / "curriculum_lap5.json"
    survivor = raw_dir / "session.json"
    source.write_text('{"raw":true}', encoding="utf-8")
    curriculum.write_text('{"derived":true}', encoding="utf-8")
    survivor.write_text('{"raw":2}', encoding="utf-8")
    old = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    os.utime(source, (old, old))
    os.utime(curriculum, (old + 1, old + 1))
    os.utime(survivor, (old + 2, old + 2))

    plan = plan_retention(
        tt_dir=tt,
        policy=RetentionPolicy(max_tt_files=1),
        profile_path=None,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [source, curriculum]
    assert curriculum in {item.path for item in plan.items}
    assert {item.path: item.reasons for item in plan.delete}[curriculum] == (
        "cascade-from-coaching",
    )
    result = apply_retention(plan)
    assert result.deleted == 2
    assert not source.exists()
    assert not curriculum.exists()
    assert survivor.exists()


def test_tt_retention_honors_pinned_curriculum_during_cascade(tmp_path: Path) -> None:
    tt = tmp_path / "journal" / "tt"
    raw_dir = tt / "assettoCorsa" / "car" / "spa" / "sess"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "coaching_lap5.json"
    curriculum = raw_dir / "curriculum_lap5.json"
    survivor = raw_dir / "session.json"
    source.write_text('{"raw":true}', encoding="utf-8")
    curriculum.write_text('{"derived":true}', encoding="utf-8")
    curriculum.with_suffix(".pin").write_text("manual", encoding="utf-8")
    survivor.write_text('{"raw":2}', encoding="utf-8")
    old = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    os.utime(source, (old, old))
    os.utime(curriculum, (old + 1, old + 1))
    os.utime(survivor, (old + 2, old + 2))

    plan = plan_retention(
        tt_dir=tt,
        policy=RetentionPolicy(max_tt_files=1),
        profile_path=None,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [source]
    result = apply_retention(plan)
    assert result.deleted == 1
    assert not source.exists()
    assert curriculum.exists()
    assert survivor.exists()


def test_tt_retention_does_not_cascade_curriculum_for_last_session_only(tmp_path: Path) -> None:
    tt = tmp_path / "journal" / "tt"
    raw_dir = tt / "assettoCorsa" / "car" / "spa" / "sess"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "last_session_lap5.json"
    curriculum = raw_dir / "curriculum_lap5.json"
    survivor = raw_dir / "coaching_lap5.json"
    source.write_text('{"raw":true}', encoding="utf-8")
    curriculum.write_text('{"derived":true}', encoding="utf-8")
    survivor.write_text('{"raw":2}', encoding="utf-8")
    old = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    os.utime(source, (old, old))
    os.utime(curriculum, (old + 1, old + 1))
    os.utime(survivor, (old + 2, old + 2))

    plan = plan_retention(
        tt_dir=tt,
        policy=RetentionPolicy(max_tt_files=1),
        profile_path=None,
        now=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert [item.path for item in plan.delete] == [source]
    result = apply_retention(plan)
    assert result.deleted == 1
    assert not source.exists()
    assert curriculum.exists()
    assert survivor.exists()
