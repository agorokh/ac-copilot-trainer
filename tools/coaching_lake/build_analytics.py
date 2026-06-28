"""Build + query the coaching lakehouse (EPIC #344 / #345 P1).

``build_lake(lap_dir, db_path)`` reads the immutable per-lap JSON corpus and projects it into a
DuckDB star schema:

* ``laps``         — one row per lap (dims: car/track/condition/setup + outcome lap_ms/valid/pb).
* ``corners``      — one row per lap x corner (THE grain for setup x track x corner x condition
                     -> outcome dependency analysis).
* ``setup_params`` — tall (lap_uuid, key, value) bridge of the setup snapshot (empty until the
                     #345 P0 setup-capture lands; the table + queries are ready for it).
* ``samples``      — atomic per-sample trace; columns are :data:`reference_lap.TRACE_FIELDS`, so the
                     table auto-widens when P0b adds physics channels.

The lake is **derived + disposable**: every build drops + recreates the tables from the JSON, which
is never mutated (data-immutability invariant). DuckDB is embedded (single file, no server), so the
agent gets literal SQL over the whole corpus. The realtime <100ms coaching path does NOT use this —
it reads a precomputed reference cache; this is the offline/between-laps analytical plane.

CLI::

    python -m tools.coaching_lake.build_analytics --lap-dir <dir> --db journal/analytics.duckdb
    python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report summary
    python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --query "SELECT ..."
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.ac_harness.reference_lap import TRACE_FIELDS
from tools.lap_archive_export import (
    iter_lap_archive_paths,
    lap_is_valid,
    load_lap_archive,
)

# Per-sample columns = identity keys + the canonical trace fields (auto-widens with TRACE_FIELDS).
_SAMPLE_KEYS = ("lap_uuid", "car_id", "track_id", "sample_index")


@dataclass
class LakeSummary:
    """Result of one :func:`build_lake` run."""

    db_path: str
    laps: int = 0
    valid_laps: int = 0
    corners: int = 0
    samples: int = 0
    setup_params: int = 0
    cars: int = 0
    tracks: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"coaching lake built: {self.db_path}",
            f"  laps={self.laps} (valid={self.valid_laps})  cars={self.cars}  tracks={self.tracks}",
            f"  corners={self.corners}  samples={self.samples}  setup_params={self.setup_params}",
        ]
        if self.skipped:
            lines.append(f"  skipped {len(self.skipped)} archive(s): {self.skipped[:3]}")
        return "\n".join(lines)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _connect(db_path: str | Path):
    import duckdb  # local import so the rest of the repo doesn't hard-depend on duckdb

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def _create_schema(con) -> None:  # noqa: ANN001
    sample_cols = ",\n        ".join(f'"{f}" DOUBLE' for f in TRACE_FIELDS)
    con.execute("DROP TABLE IF EXISTS samples")
    con.execute("DROP TABLE IF EXISTS setup_params")
    con.execute("DROP TABLE IF EXISTS corners")
    con.execute("DROP TABLE IF EXISTS laps")
    con.execute(
        """
        CREATE TABLE laps (
            lap_uuid TEXT, session_uuid TEXT, file TEXT, source TEXT, import_format TEXT,
            car_id TEXT, track_id TEXT, track_layout TEXT, track_length_m DOUBLE,
            lap_n INTEGER, lap_ms BIGINT, lap_s DOUBLE, is_pb BOOLEAN, is_valid BOOLEAN,
            weather_type TEXT, track_grip DOUBLE, ambient_temp_c DOUBLE, track_temp_c DOUBLE,
            setup_hash TEXT, setup_path TEXT, n_setup_params INTEGER,
            n_corners INTEGER, sample_count INTEGER, exported_at TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE corners (
            lap_uuid TEXT, car_id TEXT, track_id TEXT, corner_index INTEGER, label TEXT,
            entry_speed DOUBLE, min_speed DOUBLE, exit_speed DOUBLE, brake_point_spline DOUBLE,
            trail_brake_ratio DOUBLE, throttle_avg DOUBLE, steer_reversals DOUBLE,
            traction_circle_proxy DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE setup_params (
            lap_uuid TEXT, setup_hash TEXT, car_id TEXT, track_id TEXT,
            key TEXT, value DOUBLE, value_text TEXT
        )
        """
    )
    con.execute(
        f"CREATE TABLE samples (\n        {sample_cols},\n        "
        + ", ".join(f'"{k}" {"INTEGER" if k == "sample_index" else "TEXT"}' for k in _SAMPLE_KEYS)
        + "\n    )"
    )


def _iter_setup_items(snapshot: Any):
    """Yield (key, value) from a setup snapshot — tolerant of dict or list-of-pairs shape."""
    if isinstance(snapshot, dict):
        yield from snapshot.items()
    elif isinstance(snapshot, list):
        for item in snapshot:
            if isinstance(item, dict) and "key" in item:
                yield item.get("key"), item.get("value")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                yield item[0], item[1]


def _lap_row(rec: dict, path: Path) -> tuple:
    car = rec.get("car") or {}
    track = rec.get("track") or {}
    cond = rec.get("conditions") or {}
    lap = rec.get("lap") or {}
    setup = rec.get("setup") or {}
    trace = rec.get("trace") or {}
    lap_ms = lap.get("lap_ms")
    lap_ms_i = int(lap_ms) if isinstance(lap_ms, (int, float)) else None
    n_setup = sum(1 for _ in _iter_setup_items(setup.get("snapshot")))
    return (
        rec.get("lap_uuid"),
        rec.get("session_uuid"),
        path.name,
        rec.get("source"),
        rec.get("import_format"),
        car.get("id"),
        track.get("id"),
        track.get("layout"),
        _num(track.get("lengthM")),
        lap.get("lap_n"),
        lap_ms_i,
        (lap_ms_i / 1000.0 if lap_ms_i else None),
        bool(lap.get("is_pb")),
        lap_is_valid(rec),
        cond.get("weatherType"),
        _num(cond.get("trackGripLevel")),
        _num(cond.get("ambientTempC")),
        _num(cond.get("trackTempC")),
        setup.get("hash") or None,
        setup.get("path"),
        n_setup,
        len(rec.get("corners") or []),
        trace.get("samples_count") or len(trace.get("samples") or []),
        rec.get("exported_at"),
    )


def _bulk_load_samples(con, sample_cols: list[str], rows: list[list]) -> int:  # noqa: ANN001
    """Vectorized bulk-load of the per-sample rows via a temp CSV + DuckDB COPY.

    DuckDB's row-by-row ``executemany`` is pathologically slow for hundreds of thousands of rows;
    its CSV reader is vectorized. We write the rows to a temp CSV (NULL = empty cell) and COPY.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    try:
        with tmp:
            writer = csv.writer(tmp)
            writer.writerow(sample_cols)
            for r in rows:
                writer.writerow(["" if v is None else v for v in r])
        con.execute("COPY samples FROM ? (FORMAT CSV, HEADER true, NULLSTR '')", [tmp.name])
        return len(rows)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def build_lake(
    lap_dir: str | Path,
    db_path: str | Path = "journal/analytics.duckdb",
    *,
    include_samples: bool = True,
) -> LakeSummary:
    """Rebuild the DuckDB lake from the per-lap JSON corpus under ``lap_dir`` (idempotent)."""
    summary = LakeSummary(db_path=str(db_path))
    con = _connect(db_path)
    try:
        _create_schema(con)
        sample_cols = list(TRACE_FIELDS) + list(_SAMPLE_KEYS)
        all_sample_rows: list[
            list
        ] = []  # bulk-loaded via COPY at the end (DuckDB hates row-by-row)
        con.execute("BEGIN TRANSACTION")
        for path in iter_lap_archive_paths([lap_dir]):
            try:
                rec = load_lap_archive(path)
            except Exception as exc:  # noqa: BLE001 - one corrupt archive must not abort the build
                summary.skipped.append(f"{path.name}: {type(exc).__name__}")
                continue
            lap_uuid = rec.get("lap_uuid")
            car = (rec.get("car") or {}).get("id")
            track = (rec.get("track") or {}).get("id")
            con.execute(
                "INSERT INTO laps VALUES (" + ", ".join("?" for _ in range(24)) + ")",
                _lap_row(rec, path),
            )
            summary.laps += 1
            for ci, c in enumerate(rec.get("corners") or []):
                if not isinstance(c, dict):
                    continue
                con.execute(
                    "INSERT INTO corners VALUES (" + ", ".join("?" for _ in range(13)) + ")",
                    (
                        lap_uuid,
                        car,
                        track,
                        ci,
                        c.get("label"),
                        _num(c.get("entrySpeed")),
                        _num(c.get("minSpeed")),
                        _num(c.get("exitSpeed")),
                        _num(c.get("brakePointSpline")),
                        _num(c.get("trailBrakeRatio")),
                        _num(c.get("throttleAvg")),
                        _num(c.get("steerReversals")),
                        _num(c.get("tractionCircleProxy")),
                    ),
                )
                summary.corners += 1
            setup = rec.get("setup") or {}
            for k, v in _iter_setup_items(setup.get("snapshot")):
                con.execute(
                    "INSERT INTO setup_params VALUES (?,?,?,?,?,?,?)",
                    (
                        lap_uuid,
                        setup.get("hash"),
                        car,
                        track,
                        str(k),
                        _num(v),
                        None if _num(v) is not None else (str(v) if v is not None else None),
                    ),
                )
                summary.setup_params += 1
            if include_samples:
                trace = rec.get("trace") or {}
                fields = trace.get("fields") or []
                idx = {name: i for i, name in enumerate(fields)}
                rows = []
                for si, samp in enumerate(trace.get("samples") or []):
                    if not isinstance(samp, (list, tuple)):
                        continue
                    vals = [
                        (_num(samp[idx[f]]) if f in idx and idx[f] < len(samp) else None)
                        for f in TRACE_FIELDS
                    ]
                    vals += [lap_uuid, car, track, si]
                    rows.append(vals)
                all_sample_rows.extend(rows)
        con.execute("COMMIT")
        if all_sample_rows:
            summary.samples = _bulk_load_samples(con, sample_cols, all_sample_rows)
        summary.valid_laps = con.execute("SELECT count(*) FROM laps WHERE is_valid").fetchone()[0]
        summary.cars = con.execute("SELECT count(DISTINCT car_id) FROM laps").fetchone()[0]
        summary.tracks = con.execute("SELECT count(DISTINCT track_id) FROM laps").fetchone()[0]
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()
    return summary


# ---------------------------------------------------------------------------
# Flagship reports — the questions the operator wants answered across the corpus.
# ---------------------------------------------------------------------------
REPORTS: dict[str, str] = {
    "summary": """
        SELECT count(*) AS laps, count(*) FILTER (WHERE is_valid) AS valid_laps,
               count(DISTINCT car_id) AS cars, count(DISTINCT track_id) AS tracks,
               min(exported_at) AS first_lap, max(exported_at) AS last_lap,
               (SELECT count(*) FROM samples) AS samples
        FROM laps
    """,
    "best-laps": """
        SELECT car_id, track_id, count(*) AS laps,
               min(lap_ms) FILTER (WHERE is_valid) AS best_ms,
               median(lap_ms) FILTER (WHERE is_valid) AS median_ms
        FROM laps GROUP BY car_id, track_id ORDER BY track_id, best_ms
    """,
    # Corner-grain view: how slow is each corner, across all laps on a track.
    "corner-speed": """
        SELECT track_id, corner_index, any_value(label) AS label, count(*) AS n,
               round(avg(min_speed), 1) AS avg_apex_kmh,
               round(min(min_speed), 1) AS slowest_apex_kmh,
               round(avg(exit_speed), 1) AS avg_exit_kmh
        FROM corners GROUP BY track_id, corner_index
        ORDER BY track_id, corner_index
    """,
    # Tyre thermal profile per car/track (atomic samples).
    "tyre-temps": """
        SELECT car_id, track_id, count(*) AS samples,
               round(avg(tyreCoreTemp_fl), 1) AS fl, round(avg(tyreCoreTemp_fr), 1) AS fr,
               round(avg(tyreCoreTemp_rl), 1) AS rl, round(avg(tyreCoreTemp_rr), 1) AS rr
        FROM samples GROUP BY car_id, track_id ORDER BY car_id, track_id
    """,
    # THE flagship dependency query (needs #345 P0 setup capture to return rows):
    # does a setup parameter value move a corner's apex/exit speed, holding car+track+corner?
    "setup-effect": """
        SELECT c.track_id, c.corner_index, sp.key AS setup_param, sp.value AS setup_value,
               count(*) AS laps, round(avg(c.min_speed), 1) AS avg_apex_kmh,
               round(avg(c.exit_speed), 1) AS avg_exit_kmh
        FROM corners c JOIN setup_params sp USING (lap_uuid)
        GROUP BY c.track_id, c.corner_index, sp.key, sp.value
        HAVING count(*) >= 1
        ORDER BY c.track_id, c.corner_index, sp.key, sp.value
    """,
}


def list_reports() -> list[str]:
    return sorted(REPORTS)


def run_query(db_path: str | Path, sql: str) -> tuple[list[str], list[tuple]]:
    con = _connect(db_path)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, cur.fetchall()
    finally:
        con.close()


def run_report(db_path: str | Path, name: str) -> tuple[list[str], list[tuple]]:
    if name not in REPORTS:
        raise KeyError(f"unknown report {name!r}; available: {list_reports()}")
    return run_query(db_path, REPORTS[name])


def _print_table(cols: list[str], rows: list[tuple], limit: int = 50) -> None:
    if not cols:
        print("(no result)")
        return
    print(" | ".join(cols))
    print("-+-".join("-" * len(c) for c in cols))
    for r in rows[:limit]:
        print(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > limit:
        print(f"... ({len(rows) - limit} more rows)")


def _default_lap_dir() -> str:
    return "journal/laps"


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build + query the coaching lakehouse (EPIC #344/#345)")
    p.add_argument("--lap-dir", default=None, help="lap-archive corpus dir (build mode)")
    p.add_argument("--db", default="journal/analytics.duckdb", help="DuckDB lake path")
    p.add_argument("--no-samples", action="store_true", help="skip the per-sample fact table")
    p.add_argument("--report", choices=list_reports(), help="run a named flagship report")
    p.add_argument("--query", help="run an arbitrary SQL query against the lake")
    p.add_argument("--limit", type=int, default=50, help="max rows to print")
    args = p.parse_args(argv)

    if args.lap_dir is not None:
        print(build_lake(args.lap_dir, args.db, include_samples=not args.no_samples).as_text())
    if args.report:
        cols, rows = run_report(args.db, args.report)
        _print_table(cols, rows, args.limit)
    if args.query:
        cols, rows = run_query(args.db, args.query)
        _print_table(cols, rows, args.limit)
    if args.lap_dir is None and not args.report and not args.query:
        p.error("nothing to do: pass --lap-dir (build), --report, and/or --query")
    return 0


if __name__ == "__main__":
    import sys

    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
