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
from contextlib import nullcontext
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
_CSV_NULL = "\\N"
# Dedicated coaching-lake filenames under journal/ — prevents wiping unrelated DuckDB files.
_ALLOWED_LAKE_DB_NAMES = frozenset({"analytics.duckdb", "lake.duckdb"})


@dataclass
class LakeSummary:
    """Result of one :func:`build_lake` run."""

    db_path: str
    laps: int = 0
    valid_laps: int = 0
    sessions: int = 0
    stints: int = 0
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
            f"  sessions={self.sessions}  stints={self.stints}",
            f"  corners={self.corners}  samples={self.samples}  setup_params={self.setup_params}",
        ]
        if self.skipped:
            lines.append(f"  skipped {len(self.skipped)} archive(s): {self.skipped[:3]}")
        return "\n".join(lines)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _connect(db_path: str | Path):
    import duckdb  # local import so the rest of the repo doesn't hard-depend on duckdb

    resolved = _resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(resolved))


def _resolve_db_path(db_path: str | Path) -> Path:
    """Resolve ``db_path`` under ``journal/`` (approved analytics write root)."""
    raw = Path(db_path)
    base_dir = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"{raw}: db path must stay within {base_dir}") from exc
    journal_root = (base_dir / "journal").resolve()
    try:
        resolved.relative_to(journal_root)
    except ValueError as exc:
        raise ValueError(f"{raw}: db path must stay under journal/") from exc
    if resolved.exists() and resolved.is_dir():
        raise ValueError(f"{raw}: db path must be a file")
    if not _is_allowed_lake_db(resolved.name):
        allowed = ", ".join(sorted(_ALLOWED_LAKE_DB_NAMES))
        raise ValueError(
            f"{raw}: coaching lake must use a dedicated db filename ({allowed}), "
            f"not {resolved.name!r}"
        )
    return resolved


def _is_allowed_lake_db(name: str) -> bool:
    if name in _ALLOWED_LAKE_DB_NAMES:
        return True
    # Atomic rebuild scratch file: .{allowed_name}.build under journal/
    if name.startswith(".") and name.endswith(".build"):
        return name[1 : -len(".build")] in _ALLOWED_LAKE_DB_NAMES
    return False


def _create_schema(con) -> None:  # noqa: ANN001
    sample_cols = ",\n        ".join(f'"{f}" DOUBLE' for f in TRACE_FIELDS)
    con.execute("DROP TABLE IF EXISTS samples")
    con.execute("DROP TABLE IF EXISTS setup_params")
    con.execute("DROP TABLE IF EXISTS corners")
    con.execute("DROP TABLE IF EXISTS stints")
    con.execute("DROP TABLE IF EXISTS sessions")
    con.execute("DROP TABLE IF EXISTS laps")
    con.execute(
        """
        CREATE TABLE laps (
            lap_uuid TEXT, session_uuid TEXT, file TEXT, source TEXT, import_format TEXT,
            car_id TEXT, track_id TEXT, track_layout TEXT, track_length_m DOUBLE,
            lap_n INTEGER, lap_ms BIGINT, lap_s DOUBLE, is_pb BOOLEAN, is_valid BOOLEAN,
            weather_type TEXT, track_grip DOUBLE, ambient_temp_c DOUBLE, track_temp_c DOUBLE,
            setup_hash TEXT, setup_path TEXT, n_setup_params INTEGER,
            n_corners INTEGER, sample_count INTEGER, exported_at TEXT,
            -- First-class tyre identity from the lap header (issue #478 Part C), distinct from
            -- setup_hash; NULL for archives written before the tyres block existed.
            tyre_set TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE sessions (
            session_uuid TEXT, car_id TEXT, track_id TEXT, track_layout TEXT,
            first_exported_at TEXT, last_exported_at TEXT,
            first_lap_n INTEGER, last_lap_n INTEGER,
            lap_count INTEGER, valid_laps INTEGER,
            best_lap_ms BIGINT, median_lap_ms DOUBLE, consistency_ms DOUBLE,
            pb_lap_uuid TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE stints (
            stint_id TEXT, session_uuid TEXT, stint_index INTEGER,
            car_id TEXT, track_id TEXT, setup_hash TEXT, tyre_set_key TEXT,
            first_lap_n INTEGER, last_lap_n INTEGER,
            lap_count INTEGER, valid_laps INTEGER,
            best_lap_ms BIGINT, median_lap_ms DOUBLE, consistency_ms DOUBLE,
            first_file TEXT, last_file TEXT
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
        for k, v in snapshot.items():
            if k is not None:
                yield k, v
    elif isinstance(snapshot, list):
        for item in snapshot:
            if isinstance(item, dict) and "key" in item:
                k = item.get("key")
                if k is not None:
                    yield k, item.get("value")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                k = item[0]
                if k is not None:
                    yield k, item[1]


def _tyre_set_key(tyres: Any) -> str | None:
    """First-class tyre identity for a lap (issue #478 Part C).

    Prefers the human tyre-set name (``ac.getTyresName``), else the compound index, else None so the
    lakehouse falls back to the setup-hash proxy for archives written before the tyres block.
    """
    if not isinstance(tyres, dict):
        return None
    # Canonicalize on the numeric compound INDEX whenever it is a finite number: the index is stable
    # across laps, whereas the human name can be intermittent (getTyresName may fail on some laps),
    # so preferring name would split one physical set into multiple stints (cursor #483). Guard
    # non-finite (inf/NaN): int(inf) raises OverflowError and would break ingest (qodo #483).
    idx = tyres.get("compoundIndex")
    if isinstance(idx, (int, float)) and not isinstance(idx, bool) and math.isfinite(idx):
        return f"compound:{int(idx)}"
    name = tyres.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


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
    tyre_set = _tyre_set_key(rec.get("tyres"))
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
        tyre_set,
    )


def _materialize_session_tables(con) -> None:  # noqa: ANN001
    """Project first-class session/stint rollups from the loaded lap fact table."""
    con.execute(
        """
        INSERT INTO sessions
        WITH best AS (
            SELECT session_uuid, lap_uuid
            FROM (
                SELECT session_uuid, lap_uuid,
                       row_number() OVER (
                           PARTITION BY session_uuid
                           ORDER BY lap_ms ASC NULLS LAST, exported_at ASC NULLS LAST, file ASC
                       ) AS rn
                FROM laps
                WHERE is_valid AND lap_ms IS NOT NULL AND lap_ms > 0
            )
            WHERE rn = 1
        )
        SELECT l.session_uuid,
               any_value(l.car_id),
               any_value(l.track_id),
               any_value(l.track_layout),
               min(l.exported_at),
               max(l.exported_at),
               min(l.lap_n),
               max(l.lap_n),
               count(*)::INTEGER,
               count(*) FILTER (WHERE l.is_valid)::INTEGER,
               min(l.lap_ms) FILTER (WHERE l.is_valid AND l.lap_ms > 0),
               median(l.lap_ms) FILTER (WHERE l.is_valid AND l.lap_ms > 0),
               stddev_samp(l.lap_ms) FILTER (WHERE l.is_valid AND l.lap_ms > 0),
               any_value(best.lap_uuid)
        FROM laps l
        LEFT JOIN best ON l.session_uuid IS NOT DISTINCT FROM best.session_uuid
        GROUP BY l.session_uuid
        """
    )
    con.execute(
        """
        INSERT INTO stints
        WITH ordered AS (
            SELECT *,
                   -- A stint boundary is a change in the tyre-set identity (issue #478 Part C) OR
                   -- the setup; keying on both promotes stints off the raw setup_hash proxy while
                   -- still splitting when only the setup changed.
                   CASE
                     WHEN lag(coalesce(tyre_set, '') || '|' || coalesce(setup_hash, '')) OVER (
                         PARTITION BY session_uuid
                         ORDER BY lap_n ASC NULLS LAST, exported_at ASC NULLS LAST, file ASC
                     ) IS NOT DISTINCT FROM (
                         coalesce(tyre_set, '') || '|' || coalesce(setup_hash, '')
                     )
                     THEN 0 ELSE 1
                   END AS stint_start
            FROM laps
        ),
        grouped AS (
            SELECT *,
                   sum(stint_start) OVER (
                       PARTITION BY session_uuid
                       ORDER BY lap_n ASC NULLS LAST, exported_at ASC NULLS LAST, file ASC
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) - 1 AS stint_index
            FROM ordered
        )
        SELECT coalesce(session_uuid, 'session') || ':' || stint_index::TEXT AS stint_id,
               session_uuid,
               stint_index::INTEGER,
               any_value(car_id),
               any_value(track_id),
               nullif(any_value(setup_hash), ''),
               coalesce(nullif(any_value(tyre_set), ''), nullif(any_value(setup_hash), ''),
                        'unknown-tyre-set'),
               min(lap_n),
               max(lap_n),
               count(*)::INTEGER,
               count(*) FILTER (WHERE is_valid)::INTEGER,
               min(lap_ms) FILTER (WHERE is_valid AND lap_ms > 0),
               median(lap_ms) FILTER (WHERE is_valid AND lap_ms > 0),
               stddev_samp(lap_ms) FILTER (WHERE is_valid AND lap_ms > 0),
               min(file),
               max(file)
        FROM grouped
        GROUP BY session_uuid, stint_index
        """
    )


class _SamplesCsvStaging:
    """Append-only staging CSV for vectorized DuckDB COPY (one lap batch at a time)."""

    def __init__(self, staging_dir: Path, sample_cols: list[str]) -> None:
        staging_dir.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            newline="",
            encoding="utf-8",
            dir=staging_dir,
            prefix=".coaching_lake_samples_",
        )
        self._writer = csv.writer(self._tmp)
        self._writer.writerow(sample_cols)
        self._path = self._tmp.name
        self.count = 0

    def __enter__(self) -> _SamplesCsvStaging:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._cleanup()

    def write_rows(self, rows: list[list]) -> None:
        for r in rows:
            self._writer.writerow([_CSV_NULL if v is None else v for v in r])
            self.count += 1

    def copy_into(self, con) -> int:  # noqa: ANN001
        if self._tmp and not self._tmp.closed:
            self._tmp.close()
        try:
            if self.count:
                con.execute(
                    f"COPY samples FROM ? (FORMAT CSV, HEADER true, NULLSTR '{_CSV_NULL}')",
                    [self._path],
                )
            return self.count
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        if self._tmp and not self._tmp.closed:
            self._tmp.close()
        if self._path:
            try:
                os.unlink(self._path)
            except OSError:
                pass
            self._path = ""


def build_lake(
    lap_dir: str | Path,
    db_path: str | Path = "journal/analytics.duckdb",
    *,
    include_samples: bool = True,
) -> LakeSummary:
    """Rebuild the DuckDB lake from the per-lap JSON corpus under ``lap_dir`` (idempotent)."""
    resolved_db = _resolve_db_path(db_path)
    build_tmp = resolved_db.parent / f".{resolved_db.name}.build"
    if build_tmp.exists():
        build_tmp.unlink()
    summary = LakeSummary(db_path=str(resolved_db))
    con = _connect(build_tmp)
    sample_cols = list(TRACE_FIELDS) + list(_SAMPLE_KEYS)
    staging_ctx: Any = (
        _SamplesCsvStaging(resolved_db.parent, sample_cols)
        if include_samples
        else nullcontext(None)
    )
    build_ok = False
    try:
        with staging_ctx as samples_staging:
            _create_schema(con)
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
                    "INSERT INTO laps VALUES (" + ", ".join("?" for _ in range(25)) + ")",
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
                    num_v = _num(v)
                    con.execute(
                        "INSERT INTO setup_params VALUES (?,?,?,?,?,?,?)",
                        (
                            lap_uuid,
                            setup.get("hash"),
                            car,
                            track,
                            str(k),
                            num_v,
                            None if num_v is not None else (str(v) if v is not None else None),
                        ),
                    )
                    summary.setup_params += 1
                if samples_staging is not None:
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
                    if rows:
                        samples_staging.write_rows(rows)
            if samples_staging is not None:
                summary.samples = samples_staging.copy_into(con)
            _materialize_session_tables(con)
            con.execute("COMMIT")
            summary.valid_laps = con.execute("SELECT count(*) FROM laps WHERE is_valid").fetchone()[
                0
            ]
            summary.sessions = con.execute("SELECT count(*) FROM sessions").fetchone()[0]
            summary.stints = con.execute("SELECT count(*) FROM stints").fetchone()[0]
            summary.cars = con.execute("SELECT count(DISTINCT car_id) FROM laps").fetchone()[0]
            summary.tracks = con.execute("SELECT count(DISTINCT track_id) FROM laps").fetchone()[0]
            build_ok = True
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()
    if build_ok:
        os.replace(build_tmp, resolved_db)
    elif build_tmp.exists():
        try:
            build_tmp.unlink()
        except OSError:
            pass
    return summary


# ---------------------------------------------------------------------------
# Flagship reports — the questions the operator wants answered across the corpus.
# ---------------------------------------------------------------------------
REPORTS: dict[str, str] = {
    "summary": """
        SELECT count(*) AS laps, count(*) FILTER (WHERE is_valid) AS valid_laps,
               count(DISTINCT car_id) AS cars, count(DISTINCT track_id) AS tracks,
               min(exported_at) AS first_lap, max(exported_at) AS last_lap,
               (SELECT count(*) FROM sessions) AS sessions,
               (SELECT count(*) FROM stints) AS stints,
               (SELECT count(*) FROM samples) AS samples
        FROM laps
    """,
    "sessions": """
        SELECT car_id, track_id, session_uuid, lap_count, valid_laps,
               best_lap_ms, round(median_lap_ms, 1) AS median_lap_ms,
               round(consistency_ms, 1) AS consistency_ms, pb_lap_uuid,
               first_exported_at, last_exported_at
        FROM sessions
        ORDER BY last_exported_at, session_uuid
    """,
    "stints": """
        SELECT car_id, track_id, session_uuid, stint_index, tyre_set_key,
               lap_count, valid_laps, best_lap_ms,
               round(median_lap_ms, 1) AS median_lap_ms,
               round(consistency_ms, 1) AS consistency_ms,
               first_lap_n, last_lap_n
        FROM stints
        ORDER BY session_uuid, stint_index
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
    con = _connect(_resolve_db_path(db_path))
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
