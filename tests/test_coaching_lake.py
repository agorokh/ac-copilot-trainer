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
    DEFAULT_FUEL_EFFECT_S_PER_KG,
    LAKE_SCHEMA_VERSION,
    build_lake,
    export_parquet,
    list_reports,
    read_parquet_surface,
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


def test_tyre_set_key_rejects_non_finite_compound_index():
    # qodo #483: a non-finite compoundIndex (e.g. +inf leaking from a bad CSP read) must not crash
    # the lakehouse — _tyre_set_key falls back to None (→ setup_hash) instead of int(inf) raising.
    from tools.coaching_lake.build_analytics import _tyre_set_key

    assert _tyre_set_key({"compoundIndex": float("inf")}) is None
    assert _tyre_set_key({"compoundIndex": float("-inf")}) is None
    assert _tyre_set_key({"compoundIndex": float("nan")}) is None
    assert _tyre_set_key({"compoundIndex": 2}) == "compound:2"
    assert _tyre_set_key({"name": "Soft (S)"}) == "Soft (S)"
    assert _tyre_set_key({}) is None


def test_stints_split_on_first_class_tyre_set(lake_cwd):
    # #478 Part C AC3: two laps in one session on DIFFERENT tyre sets (identical setup_hash) split
    # into two stints keyed on the tyre-set identity, not the setup_hash proxy.
    laps = lake_cwd / "laps"
    laps.mkdir()
    a = _archive("ta", "bmw_z4_gt3", "spa", 110000, session_uuid="sess-t", setup_hash="same-setup")
    a["tyres"] = {"compoundIndex": 1, "name": "Soft (S)"}
    a["lap"]["lap_n"] = 1
    b = _archive("tb", "bmw_z4_gt3", "spa", 109000, session_uuid="sess-t", setup_hash="same-setup")
    b["tyres"] = {"compoundIndex": 2, "name": "Medium (M)"}
    b["lap"]["lap_n"] = 2
    _write(laps, "ta", a)
    _write(laps, "tb", b)
    summary = build_lake(laps, _db_path())
    assert summary.stints == 2  # split on tyre-set id despite identical setup_hash
    cols, rows = run_report(_db_path(), "stints")
    # keyed on the canonical compound INDEX (stable), not the intermittent name (cursor #483).
    assert sorted(r[cols.index("tyre_set_key")] for r in rows) == ["compound:1", "compound:2"]


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


# ---------------------------------------------------------------------------
# Issue #488 Part C + D — grain/serialization + setup⟷outcome linkage.
# ---------------------------------------------------------------------------
_WHEELS = ("fl", "fr", "rl", "rr")


def _phys(
    lap_uuid,
    *,
    car="nissan",
    track="magione",
    lap_ms=100000,
    lap_n=1,
    session_uuid="sess",
    setup_hash="setupA",
    n_samples=10,
    fuel=50.0,
    run_camber=-3.0,
    core=90.0,
    hot_press=27.0,
    wear_base=0.0,
    dirty=0.0,
    optimal_temp=90.0,
    snapshot=None,
    is_valid=True,
) -> dict:
    """A physically-shaped archive with the full 100-col trace and controllable channels."""
    fields = list(TRACE_FIELDS)
    samples = []
    for i in range(n_samples):
        vals = dict.fromkeys(fields, 0.0)
        vals["spline"] = i / max(n_samples, 1)
        vals["eMs"] = i * 100.0  # 10 Hz => dt 100 ms
        vals["fuel"] = fuel
        vals["accG_long"] = 1.0
        vals["accG_lat"] = 1.0
        for w in _WHEELS:
            vals[f"tyreCoreTemp_{w}"] = core
            vals[f"tyreTempInner_{w}"] = core + 5.0
            vals[f"tyreTempOuter_{w}"] = core - 5.0
            vals[f"wheelsPressure_{w}"] = hot_press + i * 0.1
            vals[f"tyreWear_{w}"] = wear_base + i * 0.01
            vals[f"wheelLoad_{w}"] = 3000.0
            vals[f"slipRatio_{w}"] = 0.05
            vals[f"camber_{w}"] = run_camber
            vals[f"tyreDirty_{w}"] = dirty
        samples.append([vals[f] for f in fields])
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": lap_uuid,
        "session_uuid": session_uuid,
        "exported_at": f"2026-07-04T00:{lap_n:02d}:00Z",
        "car": {"id": car},
        "track": {"id": track, "lengthM": 2500.0},
        "conditions": {"ambientTempC": 26.0, "trackTempC": 31.0, "trackGripLevel": 0.98},
        "lap": {"lap_n": lap_n, "lap_ms": lap_ms, "is_pb": False, "is_valid": is_valid},
        "setup": {
            "hash": setup_hash,
            "path": "x/race.ini",
            "snapshot": {"CAMBER_LF": -3.2, "PRESSURE_LF": 24.0} if snapshot is None else snapshot,
        },
        "tyres": {"compoundIndex": 4, "name": "R888R", "optimalTempC": optimal_temp},
        "trace": {"samples_count": n_samples, "fields": fields, "samples": samples},
        "corners": [],
    }


def test_lap_features_scalars_and_confounds(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "s", _phys("s", lap_ms=95000, core=90.0, hot_press=27.0, wear_base=0.1, dirty=0.1))
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.lap_features == 1
    cols, rows = run_query(
        db,
        "SELECT core_temp_avg_fl, core_temp_end_fl, tread_gradient_avg_fl, pressure_rise_fl, "
        "wear_delta_fl, tyre_energy_fl, thermal_window_residence_pct, cold_pressure_fl, "
        "camber_avg_fl, is_dirty, compound, tyre_set_key, ambient_temp_c, track_temp_c, "
        "grip_level, fuel_used_kg, sample_count, schema_version FROM lap_features",
    )
    r = dict(zip(cols, rows[0], strict=True))
    assert r["core_temp_avg_fl"] == pytest.approx(90.0)
    assert r["core_temp_end_fl"] == pytest.approx(90.0)
    assert r["tread_gradient_avg_fl"] == pytest.approx(10.0)  # inner(95) − outer(85)
    assert r["pressure_rise_fl"] == pytest.approx(0.9)  # (10−1) samples × 0.1
    assert r["wear_delta_fl"] == pytest.approx(0.09)  # (10−1) × 0.01
    assert r["tyre_energy_fl"] == pytest.approx(135.0)  # 0.05 × 3000 × 0.1 × 9 intervals
    assert r["thermal_window_residence_pct"] == pytest.approx(100.0)
    assert r["cold_pressure_fl"] == pytest.approx(24.0)  # from setup PRESSURE_LF
    assert r["camber_avg_fl"] == pytest.approx(-3.0)  # running (setup is −3.2)
    assert r["is_dirty"] is True
    assert r["compound"] == "R888R"
    assert r["tyre_set_key"] == "compound:4"
    assert r["ambient_temp_c"] == pytest.approx(26.0)
    assert r["track_temp_c"] == pytest.approx(31.0)
    assert r["grip_level"] == pytest.approx(0.98)
    assert r["fuel_used_kg"] == pytest.approx(0.0)  # constant fuel this lap
    assert r["sample_count"] == 10
    assert r["schema_version"] == LAKE_SCHEMA_VERSION


def test_laps_on_set_and_out_in_lap(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    # stint A: 2 laps (setupA); stint B: 2 laps (setupB) — a mid-session change makes A's last lap
    # an in-lap and B's first lap an out-lap.
    _write(laps, "a1", _phys("a1", lap_n=1, setup_hash="A"))
    _write(laps, "a2", _phys("a2", lap_n=2, setup_hash="A"))
    _write(laps, "b3", _phys("b3", lap_n=3, setup_hash="B"))
    _write(laps, "b4", _phys("b4", lap_n=4, setup_hash="B"))
    db = _db_path()
    summary = build_lake(laps, db)
    assert summary.stint_deg == 2
    cols, rows = run_query(
        db,
        "SELECT lap_n, laps_on_set, is_new_set, out_lap, in_lap FROM lap_features ORDER BY lap_n",
    )
    got = {row[0]: tuple(row[1:]) for row in rows}
    assert got[1] == (0, True, True, False)  # stint A out-lap
    assert got[2] == (1, False, False, True)  # stint A last lap → in-lap (B follows)
    assert got[3] == (0, True, True, False)  # stint B out-lap
    assert got[4] == (1, False, False, False)  # session's final lap → not an in-lap


def test_deg_slope_and_fuel_correction(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    # one stint, 5 laps; laptime rises 500 ms per lap of age, fuel constant (fuel-corr == raw slope)
    for k in range(5):
        _write(laps, f"d{k}", _phys(f"d{k}", lap_ms=100000 + 500 * k, lap_n=k + 1, fuel=50.0))
    db = _db_path()
    summary = build_lake(laps, db)
    assert (summary.lap_features, summary.stint_deg) == (5, 1)
    cols, rows = run_query(
        db,
        "SELECT laps_on_set, lap_ms, fuel_corrected_lap_ms FROM lap_features ORDER BY laps_on_set",
    )
    by_age = {row[0]: dict(zip(cols, row, strict=True)) for row in rows}
    # fuel correction: lap_ms − fuel_effect(0.03 s/kg) × 1000 × 50 kg = lap_ms − 1500
    expect = 100500 - DEFAULT_FUEL_EFFECT_S_PER_KG * 1000.0 * 50.0
    assert by_age[1]["fuel_corrected_lap_ms"] == pytest.approx(expect)
    cols, rows = run_report(db, "degradation")
    r = dict(zip(cols, rows[0], strict=True))
    assert r["n_laps_in_fit"] == 4  # ages 1..4 (age 0 is the excluded out-lap)
    assert r["deg_ms_per_lap"] == pytest.approx(500.0)
    assert r["deg_raw_ms_per_lap"] == pytest.approx(500.0)
    assert r["deg_r2"] == pytest.approx(1.0)
    assert r["wear_rate_pct_per_lap"] == pytest.approx(0.0)  # constant wear this synthetic stint


def test_deg_null_when_insufficient_fit(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    # stint A is internal (out-lap + in-lap only) → 0 representative laps → deg undefined (NULL)
    _write(laps, "a1", _phys("a1", lap_n=1, setup_hash="A"))
    _write(laps, "a2", _phys("a2", lap_n=2, setup_hash="A"))
    _write(laps, "b3", _phys("b3", lap_n=3, setup_hash="B"))
    _write(laps, "b4", _phys("b4", lap_n=4, setup_hash="B"))
    db = _db_path()
    build_lake(laps, db)
    cols, rows = run_query(
        db, "SELECT stint_id, deg_slope_ms_per_lap, n_laps_in_fit FROM stint_deg ORDER BY stint_id"
    )
    first = dict(zip(cols, rows[0], strict=True))
    assert first["n_laps_in_fit"] == 0
    assert first["deg_slope_ms_per_lap"] is None  # NULL, never NaN


def test_parquet_export_roundtrip_and_schemaver(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _phys("a", car="nissan", track="magione", lap_n=1))
    _write(laps, "b", _phys("b", car="audi", track="spa", lap_n=1, session_uuid="sess2"))
    db = _db_path()
    summary = build_lake(laps, db)
    meta = export_parquet(db, "journal/parquet")
    assert meta["schema_version"] == LAKE_SCHEMA_VERSION
    assert meta["grains"]["lap_features"] == summary.lap_features
    assert (lake_cwd / "journal/parquet/_schema.json").exists()
    cols, rows = read_parquet_surface("journal/parquet", "lap_features", columns="count(*) n")
    assert rows[0][0] == summary.lap_features
    # samples read back as a hive-partitioned tree — partition columns recovered
    cols, rows = read_parquet_surface(
        "journal/parquet",
        "samples",
        columns="count(*) n, count(distinct track_id) t, count(distinct car_id) c",
    )
    assert tuple(rows[0]) == (summary.samples, 2, 2)
    cols, rows = run_query(db, "SELECT value FROM lake_meta WHERE key = 'schema_version'")
    assert rows[0][0] == LAKE_SCHEMA_VERSION


def test_parquet_union_by_name_tolerates_added_column(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _phys("a", car="nissan", track="magione", lap_n=1))
    db = _db_path()
    summary = build_lake(laps, db)
    export_parquet(db, "journal/parquet")
    # a next-generation partition file whose schema diverges (extra column, missing others)
    con = duckdb.connect()
    try:
        extra = lake_cwd / "journal/parquet/samples/track_id=zzz/car_id=zzz"
        extra.mkdir(parents=True)
        target = (extra / "gen2.parquet").as_posix()
        con.execute(
            f"COPY (SELECT 0.5 AS spline, 42.0 AS future_channel) TO '{target}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    # union_by_name merges divergent schemas instead of erroring on the read
    cols, rows = read_parquet_surface("journal/parquet", "samples", columns="count(*) n")
    assert rows[0][0] == summary.samples + 1


def test_part_d_dynamic_static_delta(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(
        laps,
        "a",
        _phys(
            "a",
            lap_n=1,
            run_camber=-3.0,
            hot_press=27.0,
            snapshot={"CAMBER_LF": -3.2, "PRESSURE_LF": 24.0},
        ),
    )
    db = _db_path()
    build_lake(laps, db)
    cols, rows = run_report(db, "dynamic-static-delta")
    r = dict(zip(cols, rows[0], strict=True))
    assert r["run_camber_fl"] == pytest.approx(-3.0)
    assert r["set_camber_fl"] == pytest.approx(-3.2)
    assert r["camber_delta_fl"] == pytest.approx(0.2)  # running − set
    assert r["cold_press_fl"] == pytest.approx(24.0)
    assert r["hot_press_fl"] == pytest.approx(27.45)  # 27 + mean(i×0.1)
    assert r["press_rise_fl"] == pytest.approx(3.45)  # hot − cold


def test_part_d_setup_vs_dynamic_and_coverage(lake_cwd):
    laps = lake_cwd / "laps"
    laps.mkdir()
    _write(laps, "a", _phys("a", lap_n=1, snapshot={"WING_FRONT": 3, "PRESSURE_LF": 24.0}))
    _write(laps, "b", _phys("b", lap_n=2, snapshot={}))  # no setup captured this lap
    db = _db_path()
    build_lake(laps, db)
    cols, rows = run_report(db, "setup-coverage")
    r = dict(zip(cols, rows[0], strict=True))
    assert r["laps"] == 2
    assert r["laps_with_setup"] == 1
    assert r["setup_coverage_pct"] == pytest.approx(50.0)
    cols, rows = run_report(db, "setup-vs-dynamic")
    params = {row[cols.index("setup_param")] for row in rows}
    assert "WING_FRONT" in params


def test_parquet_refuses_raw_corpus_dir(lake_cwd):
    # Data-immutability guard: --parquet must never target a dir holding raw lap_*.json archives.
    raw = lake_cwd / "journal" / "laps"
    raw.mkdir()
    _write(raw, "a", _phys("a"))
    db = _db_path()
    build_lake(raw, db)
    with pytest.raises(ValueError, match="raw lap-archive"):
        export_parquet(db, "journal/laps")


def test_new_reports_registered():
    assert {
        "degradation",
        "lap-features",
        "setup-vs-dynamic",
        "dynamic-static-delta",
        "setup-coverage",
    } <= set(list_reports())


def test_summary_has_new_grain_columns(lake_cwd):
    db, _ = _build(lake_cwd)
    cols, rows = run_report(db, "summary")
    r = dict(zip(cols, rows[0], strict=True))
    assert r["lap_features"] == 4  # 4 laps in the shared fixture
    assert "stint_deg" in cols
    assert r["setup_coverage_pct"] is not None  # 0.0 — fixture archives carry no setup snapshot
