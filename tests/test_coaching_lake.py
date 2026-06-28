"""Off-sim tests for the coaching lakehouse (EPIC #344 / #345 P1).

Build the DuckDB star from synthetic lap-archive JSON (no AC, no rig), then assert the tables and
the flagship reports — including the headline setup×corner dependency query.
"""

from __future__ import annotations

import json

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
    is_valid=True,
    min_speed=80.0,
    snapshot=None,
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
        "session_uuid": "sess",
        "exported_at": "2026-06-28T00:00:00Z",
        "car": {"id": car},
        "track": {"id": track, "lengthM": 4000.0},
        "conditions": {"ambientTempC": 26, "trackGripLevel": 0.98, "weatherType": "clear"},
        "lap": {"lap_n": 1, "lap_ms": lap_ms, "is_pb": True, "is_valid": is_valid},
        "setup": {"hash": f"h{lap_uuid}", "path": "x/race.ini", "snapshot": snapshot or {}},
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


def _build(tmp_path):
    laps = tmp_path / "laps"
    laps.mkdir()
    _write(laps, "a", _archive("a", "bmw_z4_gt3", "spa", 110000, min_speed=80.0))
    _write(laps, "b", _archive("b", "bmw_z4_gt3", "spa", 108000, min_speed=85.0))
    _write(laps, "c", _archive("c", "ks_audi_r8_lms", "imola", 95000, min_speed=70.0))
    _write(laps, "d", _archive("d", "bmw_z4_gt3", "spa", 0, is_valid=False))  # invalid (0 ms)
    db = tmp_path / "lake.duckdb"
    summary = build_lake(laps, db)
    return db, summary


def test_build_lake_counts(tmp_path):
    db, summary = _build(tmp_path)
    assert summary.laps == 4
    assert summary.valid_laps == 3  # the 0-ms lap is invalid
    assert summary.corners == 4  # one corner each
    assert summary.samples == 16  # 4 laps x 4 samples
    assert summary.cars == 2
    assert summary.tracks == 2
    assert not summary.skipped


def test_summary_and_best_laps_reports(tmp_path):
    db, _ = _build(tmp_path)
    cols, rows = run_report(db, "summary")
    assert rows[0][cols.index("laps")] == 4
    assert rows[0][cols.index("samples")] == 16

    cols, rows = run_report(db, "best-laps")
    spa = [r for r in rows if r[cols.index("track_id")] == "spa"][0]
    assert spa[cols.index("best_ms")] == 108000  # min valid lap on spa


def test_corner_speed_report_is_corner_grain(tmp_path):
    db, _ = _build(tmp_path)
    cols, rows = run_report(db, "corner-speed")
    spa = [r for r in rows if r[cols.index("track_id")] == "spa"][0]
    # spa T1 apex averaged across the spa laps (corners table holds all laps, valid or not)
    assert spa[cols.index("corner_index")] == 0
    assert spa[cols.index("avg_apex_kmh")] is not None


def test_setup_params_and_setup_effect_flagship(tmp_path):
    """The headline dependency query: setup param value -> corner apex speed."""
    laps = tmp_path / "laps"
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
    db = tmp_path / "lake.duckdb"
    summary = build_lake(laps, db)
    assert summary.setup_params == 2  # one WING_FRONT each

    cols, rows = run_report(db, "setup-effect")
    wing_rows = [r for r in rows if r[cols.index("setup_param")] == "WING_FRONT"]
    assert len(wing_rows) == 2  # one per distinct wing value
    by_val = {r[cols.index("setup_value")]: r[cols.index("avg_apex_kmh")] for r in wing_rows}
    assert by_val[3.0] == 80.0 and by_val[4.0] == 84.0  # the dependency is queryable


def test_idempotent_rebuild(tmp_path):
    db, s1 = _build(tmp_path)
    s2 = build_lake(tmp_path / "laps", db)  # rebuild over the same db
    assert (s2.laps, s2.corners, s2.samples) == (s1.laps, s1.corners, s1.samples)


def test_corrupt_archive_is_skipped_not_fatal(tmp_path):
    laps = tmp_path / "laps"
    laps.mkdir()
    _write(laps, "ok", _archive("ok", "bmw_z4_gt3", "spa", 100000))
    (laps / "lap_bad.json").write_text("{not valid json", encoding="utf-8")
    db = tmp_path / "lake.duckdb"
    summary = build_lake(laps, db)
    assert summary.laps == 1
    assert len(summary.skipped) == 1


def test_run_query_arbitrary_sql(tmp_path):
    db, _ = _build(tmp_path)
    cols, rows = run_query(db, "SELECT count(*) AS n FROM laps WHERE car_id = 'bmw_z4_gt3'")
    assert rows[0][0] == 3


def test_reports_registry_nonempty():
    assert {"summary", "best-laps", "corner-speed", "setup-effect"} <= set(list_reports())
