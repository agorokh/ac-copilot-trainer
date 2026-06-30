"""Off-sim tests for the coaching lakehouse (EPIC #344 / #345 P1).

Build the DuckDB star from synthetic lap-archive JSON (no AC, no rig), then assert the tables and
the flagship reports — including the headline setup×corner dependency query.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")  # analytics extra; skip if not installed

from tools.ac_harness.reference_lap import TRACE_FIELDS  # noqa: E402
from tools.coaching_lake.build_analytics import (  # noqa: E402
    build_lake,
    list_reports,
    run_query,
    run_report,
)


def _archive(
    lap_uuid: str,
    car: str,
    track: str,
    lap_ms: int,
    *,
    session_uuid="sess",
    is_valid=True,
    min_speed=80.0,
    snapshot=None,
    setup_hash="setup-default",
    n_samples=4,
) -> dict:
    fields = list(TRACE_FIELDS)
    samples = [
        [(i / 100.0 if f == "spline" else float(i + (ord(f[0]) % 7))) for f in fields]
        for i in range(n_samples)
    ]
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": lap_uuid,
        "session_uuid": session_uuid,
        "exported_at": "2026-06-28T00:00:00Z",
        "car": {"id": car},
        "track": {"id": track, "lengthM": 4000.0},
        "conditions": {"ambientTempC": 26, "trackGripLevel": 0.98, "weatherType": "clear"},
        "lap": {"lap_n": 1, "lap_ms": lap_ms, "is_pb": True, "is_valid": is_valid},
        "setup": {"hash": setup_hash, "path": "x/race.ini", "snapshot": snapshot or {}},
        "trace": {"samples_count": n_samples, "fields": fields, "samples": samples},
        "corners": [
            {
                "label": "T1",
                "entrySpeed": 120.0,
                "minSpeed": min_speed,
                "exitSpeed": 110.0,
                "brakePointSpline": 0.1,
                "trailBrakeRatio": 0.3,
                "throttleAvg": 0.5,
                "steerReversals": 1.0,
                "tractionCircleProxy": 0.9,
            }
        ],
    }


def _write(dirpath, name: str, rec: dict) -> None:
    (dirpath / f"lap_{name}.json").write_text(json.dumps(rec), encoding="utf-8")


@pytest.fixture
def lake_cwd(tmp_path, monkeypatch):
    """Chdir to an isolated workspace with an approved journal/ write root."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "journal").mkdir()
    return tmp_path


def _db_path() -> Path:
    return Path("journal/lake.duckdb")


def _build(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(
        laps,
        "a",
        _archive("a", "bmw_z4_gt3", "spa", 110000, session_uuid="sess-a", min_speed=80.0),
    )
    _write(
        laps,
        "b",
        _archive("b", "bmw_z4_gt3", "spa", 108000, session_uuid="sess-a", min_speed=85.0),
    )
    _write(
        laps,
        "c",
        _archive(
            "c",
            "ks_audi_r8_lms",
            "imola",
            95000,
            session_uuid="sess-b",
            min_speed=70.0,
        ),
    )
    _write(
        laps,
        "d",
        _archive("d", "bmw_z4_gt3", "spa", 0, session_uuid="sess-a", is_valid=False),
    )
    db = _db_path()
    summary = build_lake(laps, db)
    return db, summary


def test_build_lake_counts(lake_cwd):
    db, summary = _build(lake_cwd)
    assert summary.laps == 4
    assert summary.valid_laps == 3  # the 0-ms lap is invalid
    assert summary.sessions == 2
    assert summary.stints == 2
    assert summary.corners == 4  # one corner each
    assert summary.samples == 16  # 4 laps x 4 samples
    assert summary.cars == 2
    assert summary.tracks == 2
    assert not summary.skipped


def test_summary_and_best_laps_reports(lake_cwd):
    db, _ = _build(lake_cwd)
    cols, rows = run_report(db, "summary")
    assert rows[0][cols.index("laps")] == 4
    assert rows[0][cols.index("sessions")] == 2
    assert rows[0][cols.index("stints")] == 2
    assert rows[0][cols.index("samples")] == 16

    cols, rows = run_report(db, "best-laps")
    spa = [r for r in rows if r[cols.index("track_id")] == "spa"][0]
    assert spa[cols.index("best_ms")] == 108000  # min valid lap on spa


def test_session_and_stint_rollups_are_queryable(lake_cwd):
    db, _ = _build(lake_cwd)
    cols, rows = run_report(db, "sessions")
    sess_a = [r for r in rows if r[cols.index("session_uuid")] == "sess-a"][0]
    assert sess_a[cols.index("lap_count")] == 3
    assert sess_a[cols.index("valid_laps")] == 2
    assert sess_a[cols.index("best_lap_ms")] == 108000
    assert sess_a[cols.index("pb_lap_uuid")] == "b"

    cols, rows = run_report(db, "stints")
    assert len(rows) == 2
    stint_a = [r for r in rows if r[cols.index("session_uuid")] == "sess-a"][0]
    assert stint_a[cols.index("tyre_set_key")] == "setup-default"
    assert stint_a[cols.index("lap_count")] == 3


def test_corner_speed_report_is_corner_grain(lake_cwd):
    db, _ = _build(lake_cwd)
    cols, rows = run_report(db, "corner-speed")
    spa = [r for r in rows if r[cols.index("track_id")] == "spa"][0]
    # spa T1 apex averaged across the spa laps (corners table holds all laps, valid or not)
    assert spa[cols.index("corner_index")] == 0
    assert spa[cols.index("avg_apex_kmh")] is not None


def test_setup_bool_stored_as_text_not_numeric(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(
        laps,
        "flag",
        _archive("flag", "bmw_z4_gt3", "spa", 110000, snapshot={"TC_ACTIVE": True}),
    )
    db = _db_path()
    build_lake(laps, db)
    cols, rows = run_query(db, "SELECT value, value_text FROM setup_params WHERE key = 'TC_ACTIVE'")
    assert rows[0][cols.index("value")] is None
    assert rows[0][cols.index("value_text")] == "True"


def test_setup_params_and_setup_effect_flagship(lake_cwd):
    """The headline dependency query: setup param value -> corner apex speed."""
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(
        laps,
        "w1",
        _archive("w1", "bmw_z4_gt3", "spa", 110000, min_speed=80.0, snapshot={"WING_FRONT": 3}),
    )
    _write(
        laps,
        "w2",
        _archive("w2", "bmw_z4_gt3", "spa", 109000, min_speed=84.0, snapshot={"WING_FRONT": 4}),
    )
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.setup_params == 2  # one WING_FRONT each

    cols, rows = run_report(db, "setup-effect")
    wing_rows = [r for r in rows if r[cols.index("setup_param")] == "WING_FRONT"]
    assert len(wing_rows) == 2  # one per distinct wing value
    by_val = {r[cols.index("setup_value")]: r[cols.index("avg_apex_kmh")] for r in wing_rows}
    assert by_val[3.0] == 80.0 and by_val[4.0] == 84.0  # the dependency is queryable


def test_idempotent_rebuild(lake_cwd):
    db, s1 = _build(lake_cwd)
    s2 = build_lake(lake_cwd / "laps", db)  # rebuild over the same db
    assert (s2.laps, s2.corners, s2.samples) == (s1.laps, s1.corners, s1.samples)


def test_corrupt_archive_is_skipped_not_fatal(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "ok", _archive("ok", "bmw_z4_gt3", "spa", 100000))
    (laps / "lap_bad.json").write_text("{not valid json", encoding="utf-8")
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.laps == 1
    assert len(summary.skipped) == 1


def test_run_query_arbitrary_sql(lake_cwd):
    db, _ = _build(lake_cwd)
    cols, rows = run_query(db, "SELECT count(*) AS n FROM laps WHERE car_id = 'bmw_z4_gt3'")
    assert rows[0][0] == 3


def test_reports_registry_nonempty():
    assert {"summary", "sessions", "stints", "best-laps", "corner-speed", "setup-effect"} <= set(
        list_reports()
    )


def test_db_path_outside_journal_rejected(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _archive("a", "bmw_z4_gt3", "spa", 110000))
    with pytest.raises(ValueError, match="journal/"):
        build_lake(laps, "lake.duckdb")


def test_zero_sample_build_cleans_staging_csv(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    rec = _archive("a", "bmw_z4_gt3", "spa", 110000, n_samples=0)
    rec["trace"]["samples"] = []
    _write(laps, "a", rec)
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.samples == 0
    leaked = list((lake_cwd / "journal").glob(".coaching_lake_samples_*"))
    assert not leaked


def test_build_without_samples_skips_staging(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _archive("a", "bmw_z4_gt3", "spa", 110000))
    db = _db_path()
    summary = build_lake(laps, db, include_samples=False)
    assert summary.samples == 0
    assert summary.laps == 1
    cols, rows = run_query(db, "SELECT count(*) FROM samples")
    assert rows[0][0] == 0


def test_non_lake_duckdb_filename_rejected(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _archive("a", "bmw_z4_gt3", "spa", 110000))
    with pytest.raises(ValueError, match="dedicated db filename"):
        build_lake(laps, "journal/my_notes.duckdb")


def test_null_setup_key_skipped(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    rec = _archive("a", "bmw_z4_gt3", "spa", 110000, snapshot={"WING": 3})
    rec["setup"]["snapshot"] = [{"key": None, "value": 1}, {"key": "WING", "value": 3}]
    _write(laps, "a", rec)
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.setup_params == 1
    cols, rows = run_query(db, "SELECT key FROM setup_params")
    assert rows[0][cols.index("key")] == "WING"
