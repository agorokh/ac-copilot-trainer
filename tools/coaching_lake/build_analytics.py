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
import json
import math
import os
import shutil
import statistics
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

# ---------------------------------------------------------------------------
# Grain + serialization (issue #488 Part C).
# ---------------------------------------------------------------------------
# SchemaVer MODEL.REVISION.ADDITION for the DERIVED lake surface: bump ADDITION for a new
# optional column/grain, REVISION for a compatible reshape, MODEL for a breaking change.
# 1.0.0 = the original star schema (laps/sessions/stints/corners/setup_params/samples);
# 1.1.0 adds the lap_features + stint_deg grains, the lake_meta table, and Parquet emit.
LAKE_SCHEMA_VERSION = "1.1.0"

# Fuel-corrected laptime prior (issue #488 Part C). A heavier fuel load costs lap time roughly
# linearly; ~0.03 s/kg is a widely-cited sim/real prior. Documented + configurable (never hidden)
# so the correction is transparent: we SUBTRACT a modelled fuel penalty from each lap, we do NOT
# regress fuel out of the within-stint fuel/age-collinear signal (which is ill-posed). Degradation
# is then the residual slope of fuel-corrected laptime vs tyre-set age.
DEFAULT_FUEL_EFFECT_S_PER_KG = 0.03

# Half-width (°C) of the car-true tyre thermal window around tyres.optimalTempC, for the per-lap
# thermal-window-residence feature. Residence is NULL when the archive lacks optimalTempC.
_THERMAL_WINDOW_HALF_WIDTH_C = 10.0

# tyreDirty fraction above which a lap sample counts as dirty (marbles / off-track pickup).
_DIRTY_SAMPLE_THRESHOLD = 0.05

_WHEELS: tuple[str, ...] = ("fl", "fr", "rl", "rr")

# Per-wheel per-lap reductions. Ordered; each expands to one DOUBLE column per wheel as
# ``f"{base}_{wheel}"``. Kept as data so CREATE TABLE and the INSERT stay in sync (the count-
# mismatch bug class prior reviews flagged on this file).
_PER_WHEEL_FEATURE_BASES: tuple[str, ...] = (
    "core_temp_avg",  # tyre carcass thermal state (avg / max / end-of-lap)
    "core_temp_max",
    "core_temp_end",
    "tread_gradient_avg",  # inner − outer °C (camber / pressure health)
    "pressure_avg",  # hot running pressure + in-lap rise
    "pressure_rise",
    "wear_end",  # degradation: end level + Δ over the lap
    "wear_delta",
    "brake_temp_max",  # brake thermal peak
    "load_avg",  # vertical wheel load
    "camber_avg",  # dynamic running camber (vs the static set value → Part D delta)
    "tyre_energy",  # Σ|slipRatio|·load·dt — frictional-heat / degradation driver
)

# Extra columns lap_features carries beyond the Python-computed scalars: tyre-set age + stint
# identity (window-derived from lap ordering in _materialize_analytics_tables) + the SchemaVer.
_LAP_AGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("stint_id", "TEXT"),
    ("stint_index", "INTEGER"),
    ("laps_on_set", "INTEGER"),
    ("is_new_set", "BOOLEAN"),
    ("out_lap", "BOOLEAN"),
    ("in_lap", "BOOLEAN"),
    ("schema_version", "TEXT"),
)


def _lap_scalar_columns() -> tuple[tuple[str, str], ...]:
    """Ordered ``(name, duckdb_type)`` for the Python-computed per-lap scalar features.

    The stint/age fields (``laps_on_set``, ``is_new_set``, ``out_lap``, ``in_lap``, ``stint_id``)
    are NOT here — they are window-derived in :func:`_materialize_analytics_tables` from lap order.
    """
    cols: list[tuple[str, str]] = [
        ("lap_uuid", "TEXT"),
        ("session_uuid", "TEXT"),
        ("car_id", "TEXT"),
        ("track_id", "TEXT"),
        ("lap_n", "INTEGER"),
        ("is_valid", "BOOLEAN"),
        ("lap_ms", "BIGINT"),
        ("fuel_corrected_lap_ms", "DOUBLE"),
        ("compound", "TEXT"),
        ("tyre_set_key", "TEXT"),
        ("optimal_temp_c", "DOUBLE"),
        ("ambient_temp_c", "DOUBLE"),
        ("track_temp_c", "DOUBLE"),
        ("grip_level", "DOUBLE"),
        ("cold_pressure_fl", "DOUBLE"),
        ("cold_pressure_fr", "DOUBLE"),
        ("cold_pressure_rl", "DOUBLE"),
        ("cold_pressure_rr", "DOUBLE"),
        ("is_dirty", "BOOLEAN"),
        ("fuel_start_kg", "DOUBLE"),
        ("fuel_end_kg", "DOUBLE"),
        ("fuel_used_kg", "DOUBLE"),
        ("gg_envelope_max", "DOUBLE"),
        ("slip_ratio_abs_avg", "DOUBLE"),
        ("slip_angle_abs_avg", "DOUBLE"),
        ("thermal_window_residence_pct", "DOUBLE"),
        ("sample_count", "INTEGER"),
        ("sample_dt_ms_median", "DOUBLE"),
        ("trace_hz", "DOUBLE"),
    ]
    cols += [(f"{base}_{w}", "DOUBLE") for w in _WHEELS for base in _PER_WHEEL_FEATURE_BASES]
    return tuple(cols)


_LAP_SCALAR_COLUMNS: tuple[tuple[str, str], ...] = _lap_scalar_columns()
_LAP_SCALAR_NAMES: tuple[str, ...] = tuple(name for name, _ in _LAP_SCALAR_COLUMNS)
# Cold set pressures live in the setup snapshot under these AC INI keys (LF/RF/LR/RR).
_COLD_PRESSURE_SETUP_KEYS: dict[str, str] = {
    "fl": "PRESSURE_LF",
    "fr": "PRESSURE_RF",
    "rl": "PRESSURE_LR",
    "rr": "PRESSURE_RR",
}


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
    lap_features: int = 0
    stint_deg: int = 0
    cars: int = 0
    tracks: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"coaching lake built: {self.db_path}",
            f"  laps={self.laps} (valid={self.valid_laps})  cars={self.cars}  tracks={self.tracks}",
            f"  sessions={self.sessions}  stints={self.stints}",
            f"  corners={self.corners}  samples={self.samples}  setup_params={self.setup_params}",
            f"  lap_features={self.lap_features}  stint_deg={self.stint_deg}  "
            f"schema={LAKE_SCHEMA_VERSION}",
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


class _Agg:
    """Streaming per-channel aggregate: count, sum, max, first, last (silently skips ``None``)."""

    __slots__ = ("n", "total", "max", "first", "last")

    def __init__(self) -> None:
        self.n = 0
        self.total = 0.0
        self.max: float | None = None
        self.first: float | None = None
        self.last: float | None = None

    def add(self, value: float | None) -> None:
        if value is None:
            return
        self.n += 1
        self.total += value
        self.max = value if self.max is None else max(self.max, value)
        if self.first is None:
            self.first = value
        self.last = value

    @property
    def avg(self) -> float | None:
        return self.total / self.n if self.n else None

    @property
    def rise(self) -> float | None:
        if self.first is None or self.last is None:
            return None
        return self.last - self.first


def _compute_lap_scalars(rec: dict, *, fuel_effect_s_per_kg: float) -> dict[str, Any]:
    """One-pass per-lap scalar features from the trace samples (issue #488 Part C).

    Returns a dict keyed by :data:`_LAP_SCALAR_NAMES` (the age/stint fields are added later in
    :func:`_materialize_analytics_tables`). Robust to missing channels — an absent field yields a
    ``None`` feature, never a crash — so older/narrower archives still project cleanly.
    """
    trace = rec.get("trace") or {}
    fields = trace.get("fields") or []
    idx = {name: i for i, name in enumerate(fields) if isinstance(name, str)}
    samples = trace.get("samples") or []

    def val(sample: Any, name: str) -> float | None:
        i = idx.get(name)
        if i is None or not isinstance(sample, (list, tuple)) or i >= len(sample):
            return None
        return _num(sample[i])

    core = {w: _Agg() for w in _WHEELS}
    pressure = {w: _Agg() for w in _WHEELS}
    wear = {w: _Agg() for w in _WHEELS}
    brake = {w: _Agg() for w in _WHEELS}
    load = {w: _Agg() for w in _WHEELS}
    camber = {w: _Agg() for w in _WHEELS}  # dynamic running camber (deg)
    tread = {w: _Agg() for w in _WHEELS}  # inner − outer °C
    energy = dict.fromkeys(_WHEELS, 0.0)
    energy_has = dict.fromkeys(_WHEELS, False)

    slip_ratio_abs = _Agg()
    slip_angle_abs = _Agg()
    fuel = _Agg()
    gg_max: float | None = None
    thermal_in = 0
    thermal_total = 0
    dirty = False
    prev_ems: float | None = None
    dts: list[float] = []
    n_samples = 0

    tyres = rec.get("tyres") if isinstance(rec.get("tyres"), dict) else {}
    optimal = _num(tyres.get("optimalTempC"))

    for s in samples:
        if not isinstance(s, (list, tuple)):
            continue
        n_samples += 1
        ems = val(s, "eMs")
        dt_s: float | None = None
        if ems is not None:
            if prev_ems is not None and ems > prev_ems:
                dt_ms = ems - prev_ems
                dts.append(dt_ms)
                dt_s = dt_ms / 1000.0
            prev_ems = ems
        core_vals: list[float] = []
        for w in _WHEELS:
            c = val(s, f"tyreCoreTemp_{w}")
            core[w].add(c)
            if c is not None:
                core_vals.append(c)
            inner = val(s, f"tyreTempInner_{w}")
            outer = val(s, f"tyreTempOuter_{w}")
            if inner is not None and outer is not None:
                tread[w].add(inner - outer)
            pressure[w].add(val(s, f"wheelsPressure_{w}"))
            wear[w].add(val(s, f"tyreWear_{w}"))
            brake[w].add(val(s, f"brakeTemp_{w}"))
            ld = val(s, f"wheelLoad_{w}")
            load[w].add(ld)
            camber[w].add(val(s, f"camber_{w}"))
            sr = val(s, f"slipRatio_{w}")
            if sr is not None:
                slip_ratio_abs.add(abs(sr))
            sa = val(s, f"slipAngle_{w}")
            if sa is not None:
                slip_angle_abs.add(abs(sa))
            if sr is not None and ld is not None and dt_s is not None:
                energy[w] += abs(sr) * ld * dt_s
                energy_has[w] = True
            dv = val(s, f"tyreDirty_{w}")
            if dv is not None and dv > _DIRTY_SAMPLE_THRESHOLD:
                dirty = True
        g_long = val(s, "accG_long")
        g_lat = val(s, "accG_lat")
        if g_long is not None and g_lat is not None:
            combined = math.hypot(g_long, g_lat)
            gg_max = combined if gg_max is None else max(gg_max, combined)
        fuel.add(val(s, "fuel"))
        if optimal is not None and core_vals:
            thermal_total += 1
            mean_core = sum(core_vals) / len(core_vals)
            if abs(mean_core - optimal) <= _THERMAL_WINDOW_HALF_WIDTH_C:
                thermal_in += 1

    lap = rec.get("lap") or {}
    cond = rec.get("conditions") or {}
    car = rec.get("car") or {}
    track = rec.get("track") or {}
    setup = rec.get("setup") or {}
    setup_map = {str(k): v for k, v in _iter_setup_items(setup.get("snapshot"))}

    lap_ms = lap.get("lap_ms")
    lap_ms_i = (
        int(lap_ms) if isinstance(lap_ms, (int, float)) and not isinstance(lap_ms, bool) else None
    )
    fuel_start = fuel.first
    if lap_ms_i and fuel_start is not None:
        fuel_corrected = float(lap_ms_i) - fuel_effect_s_per_kg * 1000.0 * fuel_start
    elif lap_ms_i:
        fuel_corrected = float(lap_ms_i)  # no fuel channel → degrades to the raw laptime
    else:
        fuel_corrected = None

    median_dt = statistics.median(dts) if dts else None
    tyre_set_key = _tyre_set_key(rec.get("tyres"))
    compound = None
    if isinstance(tyres, dict):
        compound = (tyres.get("name") or tyres.get("longName") or "").strip() or None
    compound = compound or tyre_set_key

    out: dict[str, Any] = {
        "lap_uuid": rec.get("lap_uuid"),
        "session_uuid": rec.get("session_uuid"),
        "car_id": car.get("id"),
        "track_id": track.get("id"),
        "lap_n": lap.get("lap_n"),
        "is_valid": lap_is_valid(rec),
        "lap_ms": lap_ms_i,
        "fuel_corrected_lap_ms": fuel_corrected,
        "compound": compound,
        "tyre_set_key": tyre_set_key,
        "optimal_temp_c": optimal,
        "ambient_temp_c": _num(cond.get("ambientTempC")),
        "track_temp_c": _num(cond.get("trackTempC")),
        "grip_level": _num(cond.get("trackGripLevel")),
        "is_dirty": dirty,
        "fuel_start_kg": fuel.first,
        "fuel_end_kg": fuel.last,
        "fuel_used_kg": (
            fuel.first - fuel.last if fuel.first is not None and fuel.last is not None else None
        ),
        "gg_envelope_max": gg_max,
        "slip_ratio_abs_avg": slip_ratio_abs.avg,
        "slip_angle_abs_avg": slip_angle_abs.avg,
        "thermal_window_residence_pct": (
            100.0 * thermal_in / thermal_total if thermal_total else None
        ),
        "sample_count": n_samples,
        "sample_dt_ms_median": median_dt,
        "trace_hz": (1000.0 / median_dt if median_dt else None),
    }
    for w in _WHEELS:
        out[f"cold_pressure_{w}"] = _num(setup_map.get(_COLD_PRESSURE_SETUP_KEYS[w]))
        out[f"core_temp_avg_{w}"] = core[w].avg
        out[f"core_temp_max_{w}"] = core[w].max
        out[f"core_temp_end_{w}"] = core[w].last
        out[f"tread_gradient_avg_{w}"] = tread[w].avg
        out[f"pressure_avg_{w}"] = pressure[w].avg
        out[f"pressure_rise_{w}"] = pressure[w].rise
        out[f"wear_end_{w}"] = wear[w].last
        out[f"wear_delta_{w}"] = wear[w].rise
        out[f"brake_temp_max_{w}"] = brake[w].max
        out[f"load_avg_{w}"] = load[w].avg
        out[f"camber_avg_{w}"] = camber[w].avg
        out[f"tyre_energy_{w}"] = energy[w] if energy_has[w] else None
    return out


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


def _cols_ddl(cols: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f'"{name}" {sqltype}' for name, sqltype in cols)


def _create_schema(con) -> None:  # noqa: ANN001
    sample_cols = ",\n        ".join(f'"{f}" DOUBLE' for f in TRACE_FIELDS)
    con.execute("DROP TABLE IF EXISTS lake_meta")
    con.execute("DROP TABLE IF EXISTS stint_deg")
    con.execute("DROP TABLE IF EXISTS lap_features")
    con.execute("DROP TABLE IF EXISTS lap_scalars")
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
    # Per-lap scalar staging (Python-computed) — projected into lap_features with age fields, then
    # dropped so the final DB carries only the two first-class grains (issue #488 Part C).
    con.execute(f"CREATE TABLE lap_scalars ({_cols_ddl(_LAP_SCALAR_COLUMNS)})")
    con.execute(f"CREATE TABLE lap_features ({_cols_ddl(_LAP_SCALAR_COLUMNS + _LAP_AGE_COLUMNS)})")
    con.execute(
        """
        CREATE TABLE stint_deg (
            stint_id TEXT, session_uuid TEXT, car_id TEXT, track_id TEXT,
            tyre_set_key TEXT, compound TEXT,
            first_lap_n INTEGER, last_lap_n INTEGER,
            lap_count INTEGER, valid_laps INTEGER, laps_on_set_max INTEGER,
            -- deg_slope: OLS slope of fuel-corrected laptime (ms) vs laps_on_set over valid,
            -- non-out/in laps. Positive = the car slows as the tyre-set ages. raw = uncorrected.
            deg_slope_ms_per_lap DOUBLE, deg_slope_raw_ms_per_lap DOUBLE,
            deg_intercept_ms DOUBLE, deg_r2 DOUBLE, n_laps_in_fit INTEGER,
            wear_rate_pct_per_lap DOUBLE, thermal_window_residence_pct DOUBLE,
            best_lap_ms BIGINT, median_lap_ms DOUBLE,
            fuel_effect_s_per_kg DOUBLE, schema_version TEXT
        )
        """
    )
    con.execute("CREATE TABLE lake_meta (key TEXT, value TEXT)")


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


# Fit filter for the degradation OLS: valid, representative laps only (exclude cold out-laps and
# pit in-laps; require a real laptime and a known tyre-set age).
_DEG_FIT_FILTER = (
    "is_valid AND NOT coalesce(out_lap, false) AND NOT coalesce(in_lap, false) "
    "AND lap_ms IS NOT NULL AND lap_ms > 0 AND laps_on_set IS NOT NULL"
)


def _nan_to_null(col: str) -> str:
    """SQL wrapper: an OLS fit over <2 points yields NaN — present that as NULL (undefined),
    not a fake number. NULL inputs pass through as NULL."""
    return f"CASE WHEN isnan({col}) OR isinf({col}) THEN NULL ELSE {col} END"


def _materialize_analytics_tables(con, *, fuel_effect_s_per_kg: float) -> None:  # noqa: ANN001
    """Project the per-lap scalar staging into the lap_features + stint_deg grains (#488 Part C).

    ``lap_features`` = the Python-computed scalars ⋈ window-derived tyre-set age (``laps_on_set``,
    ``is_new_set``, ``out_lap``, ``in_lap``) using the SAME stint-boundary rule as the ``stints``
    rollup (a change in tyre-set OR setup). ``stint_deg`` = per-stint OLS of fuel-corrected laptime
    vs age (DuckDB ``regr_slope``), wear rate, and thermal-window residence.
    """
    scalar_select = ", ".join(f's."{name}"' for name in _LAP_SCALAR_NAMES)
    scalar_insert = ", ".join(f'"{name}"' for name in _LAP_SCALAR_NAMES)
    con.execute(
        f"""
        INSERT INTO lap_features (
            {scalar_insert}, stint_id, stint_index, laps_on_set, is_new_set, out_lap, in_lap,
            schema_version
        )
        WITH ordered AS (
            SELECT lap_uuid, session_uuid, lap_n, exported_at, file,
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
        seq AS (
            SELECT *,
                   sum(stint_start) OVER (
                       PARTITION BY session_uuid
                       ORDER BY lap_n ASC NULLS LAST, exported_at ASC NULLS LAST, file ASC
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) - 1 AS stint_index
            FROM ordered
        ),
        aged AS (
            SELECT lap_uuid, session_uuid, stint_index,
                   coalesce(session_uuid, 'session') || ':' || stint_index::TEXT AS stint_id,
                   row_number() OVER (
                       PARTITION BY session_uuid, stint_index
                       ORDER BY lap_n ASC NULLS LAST, exported_at ASC NULLS LAST, file ASC
                   ) - 1 AS laps_on_set,
                   max(stint_index) OVER (PARTITION BY session_uuid) AS max_stint_index,
                   count(*) OVER (PARTITION BY session_uuid, stint_index) AS stint_len
            FROM seq
        )
        SELECT {scalar_select},
               a.stint_id, a.stint_index, a.laps_on_set,
               (a.laps_on_set = 0) AS is_new_set,
               (a.laps_on_set = 0) AS out_lap,
               -- in-lap = last lap of a stint that is followed by another stint in the session
               -- (a real tyre/setup change happened after it). AC exposes no pit-in flag to Lua,
               -- so this is the deterministic proxy; the final stint's last lap is NOT marked.
               (a.laps_on_set = a.stint_len - 1 AND a.stint_index < a.max_stint_index) AS in_lap,
               '{LAKE_SCHEMA_VERSION}'
        FROM lap_scalars s JOIN aged a USING (lap_uuid)
        """
    )
    fuel_effect = float(fuel_effect_s_per_kg)
    fit = _DEG_FIT_FILTER
    age = "CAST(laps_on_set AS DOUBLE)"
    con.execute(
        f"""
        INSERT INTO stint_deg
        WITH agg AS (
            SELECT
                stint_id,
                any_value(session_uuid) AS session_uuid,
                any_value(car_id) AS car_id,
                any_value(track_id) AS track_id,
                coalesce(nullif(any_value(tyre_set_key), ''), 'unknown-tyre-set') AS tyre_set_key,
                any_value(compound) AS compound,
                min(lap_n) AS first_lap_n,
                max(lap_n) AS last_lap_n,
                count(*)::INTEGER AS lap_count,
                count(*) FILTER (WHERE is_valid)::INTEGER AS valid_laps,
                max(laps_on_set) AS laps_on_set_max,
                regr_slope(fuel_corrected_lap_ms, {age}) FILTER (WHERE {fit}) AS deg_slope,
                regr_slope(CAST(lap_ms AS DOUBLE), {age}) FILTER (WHERE {fit}) AS deg_raw,
                regr_intercept(fuel_corrected_lap_ms, {age}) FILTER (WHERE {fit}) AS deg_intercept,
                regr_r2(fuel_corrected_lap_ms, {age}) FILTER (WHERE {fit}) AS deg_r2,
                regr_count(fuel_corrected_lap_ms, {age}) FILTER (WHERE {fit})::INTEGER AS n_fit,
                regr_slope(
                    (wear_end_fl + wear_end_fr + wear_end_rl + wear_end_rr) / 4.0, {age}
                ) FILTER (WHERE is_valid AND laps_on_set IS NOT NULL) AS wear_rate,
                avg(thermal_window_residence_pct) FILTER (WHERE is_valid) AS thermal_pct,
                min(lap_ms) FILTER (WHERE is_valid AND lap_ms > 0) AS best_lap_ms,
                median(lap_ms) FILTER (WHERE is_valid AND lap_ms > 0) AS median_lap_ms
            FROM lap_features
            GROUP BY stint_id
        )
        SELECT
            stint_id, session_uuid, car_id, track_id, tyre_set_key, compound,
            first_lap_n, last_lap_n, lap_count, valid_laps, laps_on_set_max,
            {_nan_to_null("deg_slope")}, {_nan_to_null("deg_raw")}, {_nan_to_null("deg_intercept")},
            {_nan_to_null("deg_r2")}, n_fit, {_nan_to_null("wear_rate")},
            thermal_pct, best_lap_ms, median_lap_ms,
            {fuel_effect}, '{LAKE_SCHEMA_VERSION}'
        FROM agg
        """
    )
    built_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    con.execute(
        "INSERT INTO lake_meta VALUES (?,?),(?,?),(?,?),(?,?),(?,?)",
        [
            "schema_version",
            LAKE_SCHEMA_VERSION,
            "fuel_effect_s_per_kg",
            repr(fuel_effect),
            "trace_field_count",
            str(len(TRACE_FIELDS)),
            "thermal_window_half_width_c",
            repr(_THERMAL_WINDOW_HALF_WIDTH_C),
            "built_at",
            built_at,
        ],
    )
    con.execute("DROP TABLE IF EXISTS lap_scalars")


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
    fuel_effect_s_per_kg: float = DEFAULT_FUEL_EFFECT_S_PER_KG,
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
                scalars = _compute_lap_scalars(rec, fuel_effect_s_per_kg=fuel_effect_s_per_kg)
                con.execute(
                    "INSERT INTO lap_scalars ("
                    + ", ".join(f'"{n}"' for n in _LAP_SCALAR_NAMES)
                    + ") VALUES ("
                    + ", ".join("?" for _ in _LAP_SCALAR_NAMES)
                    + ")",
                    [scalars.get(n) for n in _LAP_SCALAR_NAMES],
                )
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
            _materialize_analytics_tables(con, fuel_effect_s_per_kg=fuel_effect_s_per_kg)
            con.execute("COMMIT")
            summary.valid_laps = con.execute("SELECT count(*) FROM laps WHERE is_valid").fetchone()[
                0
            ]
            summary.sessions = con.execute("SELECT count(*) FROM sessions").fetchone()[0]
            summary.stints = con.execute("SELECT count(*) FROM stints").fetchone()[0]
            summary.lap_features = con.execute("SELECT count(*) FROM lap_features").fetchone()[0]
            summary.stint_deg = con.execute("SELECT count(*) FROM stint_deg").fetchone()[0]
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
               (SELECT count(*) FROM samples) AS samples,
               (SELECT count(*) FROM lap_features) AS lap_features,
               (SELECT count(*) FROM stint_deg) AS stint_deg,
               round(100.0 * count(*) FILTER (WHERE n_setup_params > 0) / nullif(count(*), 0), 1)
                   AS setup_coverage_pct
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
    # THE degradation headline (issue #488 Part C): per-stint tyre-set-age slope of fuel-corrected
    # laptime, wear rate, and thermal-window residence — segmented by compound × tyre-set.
    "degradation": """
        SELECT car_id, track_id, compound, tyre_set_key,
               lap_count, valid_laps, laps_on_set_max, n_laps_in_fit,
               round(deg_slope_ms_per_lap, 1) AS deg_ms_per_lap,
               round(deg_slope_raw_ms_per_lap, 1) AS deg_raw_ms_per_lap,
               round(deg_r2, 3) AS deg_r2,
               round(wear_rate_pct_per_lap, 3) AS wear_rate_pct_per_lap,
               round(thermal_window_residence_pct, 1) AS thermal_pct,
               best_lap_ms
        FROM stint_deg
        ORDER BY car_id, track_id, stint_id
    """,
    # Per-lap ML scalar surface (issue #488 Part C) — one row/lap, segmentable by tyre-set age.
    "lap-features": """
        SELECT car_id, track_id, lap_n, compound, laps_on_set, is_new_set, out_lap, in_lap,
               lap_ms, round(fuel_corrected_lap_ms, 0) AS fuel_corr_ms,
               round(core_temp_avg_fl, 1) AS core_fl, round(core_temp_avg_rr, 1) AS core_rr,
               round(thermal_window_residence_pct, 1) AS thermal_pct,
               round(wear_delta_fl, 3) AS wear_delta_fl, round(gg_envelope_max, 2) AS gg_max,
               round(fuel_used_kg, 2) AS fuel_used_kg, is_dirty
        FROM lap_features
        ORDER BY car_id, track_id, laps_on_set
    """,
    # Part D — static setup ⟷ dynamic response ⟷ outcome: does a setup value move the car's dynamic
    # tyre/energy response AND the laptime? (Extends setup-effect with the new dynamic channels.)
    "setup-vs-dynamic": """
        SELECT sp.key AS setup_param, sp.value AS setup_value, lf.car_id, lf.track_id,
               count(*) AS laps,
               round(avg(lf.core_temp_avg_fl), 1) AS avg_core_fl,
               round(avg(lf.tyre_energy_fl), 1) AS avg_energy_fl,
               round(avg(lf.thermal_window_residence_pct), 1) AS avg_thermal_pct,
               round(avg(lf.lap_ms), 0) AS avg_lap_ms
        FROM setup_params sp JOIN lap_features lf USING (lap_uuid)
        WHERE sp.value IS NOT NULL
        GROUP BY sp.key, sp.value, lf.car_id, lf.track_id
        HAVING count(*) >= 1
        ORDER BY sp.key, sp.value, lf.car_id, lf.track_id
    """,
    # Part D — dynamic-vs-static deltas: running camber vs set value; hot running pressure vs cold
    # set pressure. The gap between what you dialled in and what the car actually did.
    "dynamic-static-delta": """
        WITH set_camber AS (
            SELECT lap_uuid,
                   max(value) FILTER (WHERE key = 'CAMBER_LF') AS set_camber_fl,
                   max(value) FILTER (WHERE key = 'CAMBER_RF') AS set_camber_fr,
                   max(value) FILTER (WHERE key = 'CAMBER_LR') AS set_camber_rl,
                   max(value) FILTER (WHERE key = 'CAMBER_RR') AS set_camber_rr
            FROM setup_params GROUP BY lap_uuid
        )
        SELECT lf.car_id, lf.track_id, lf.lap_n, lf.laps_on_set,
               round(lf.camber_avg_fl, 2) AS run_camber_fl,
               round(sc.set_camber_fl, 2) AS set_camber_fl,
               round(lf.camber_avg_fl - sc.set_camber_fl, 2) AS camber_delta_fl,
               round(lf.pressure_avg_fl, 2) AS hot_press_fl,
               round(lf.cold_pressure_fl, 2) AS cold_press_fl,
               round(lf.pressure_avg_fl - lf.cold_pressure_fl, 2) AS press_rise_fl
        FROM lap_features lf LEFT JOIN set_camber sc USING (lap_uuid)
        ORDER BY lf.car_id, lf.track_id, lf.laps_on_set
    """,
    # Part D — setup-snapshot reliability: fraction of laps that actually captured setup params
    # (the historical setup_params=0 data-quality point — verify it holds now).
    "setup-coverage": """
        SELECT car_id, track_id, count(*) AS laps,
               count(*) FILTER (WHERE n_setup_params > 0) AS laps_with_setup,
               round(100.0 * count(*) FILTER (WHERE n_setup_params > 0) / nullif(count(*), 0), 1)
                   AS setup_coverage_pct
        FROM laps
        GROUP BY car_id, track_id
        ORDER BY setup_coverage_pct, car_id, track_id
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


# ---------------------------------------------------------------------------
# Columnar ML surface — Parquet emit + SchemaVer (issue #488 Part C).
# ---------------------------------------------------------------------------
# The immutable per-lap JSON stays the raw landing; DuckDB stays the interactive engine; Parquet
# is the additive, columnar train/query surface. ``samples`` (the big grain) is hive-partitioned;
# the small grains are single files. ``read_parquet_surface`` reads back with ``union_by_name``
# so an older Parquet generation (fewer columns) still loads after the schema grows additively.
_PARQUET_FILE_GRAINS: tuple[str, ...] = (
    "laps",
    "sessions",
    "stints",
    "corners",
    "setup_params",
    "lap_features",
    "stint_deg",
    "lake_meta",
)
_PARQUET_PARTITIONED: dict[str, tuple[str, ...]] = {"samples": ("track_id", "car_id")}


def _resolve_parquet_dir(out_dir: str | Path) -> Path:
    """Resolve ``out_dir`` under ``journal/`` (the approved derived-artifact write root)."""
    raw = Path(out_dir)
    base_dir = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"{raw}: parquet dir must stay within {base_dir}") from exc
    journal_root = (base_dir / "journal").resolve()
    try:
        resolved.relative_to(journal_root)
    except ValueError as exc:
        raise ValueError(f"{raw}: parquet dir must stay under journal/") from exc
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"{raw}: parquet path must be a directory")
    # Data-immutability guard: never emit derived Parquet INTO a raw lap-archive corpus dir. An
    # errant ``--parquet journal/laps`` would otherwise pollute the immutable JSON system of record,
    # and the samples-subdir cleanup (rmtree) could delete raw evidence.
    if resolved.is_dir() and any(resolved.glob("lap_*.json")):
        raise ValueError(f"{raw}: refusing to write parquet into a raw lap-archive dir")
    return resolved


def export_parquet(
    db_path: str | Path = "journal/analytics.duckdb",
    out_dir: str | Path = "journal/parquet",
) -> dict[str, Any]:
    """Emit every lake grain to Parquet under ``out_dir`` + a ``_schema.json`` SchemaVer sidecar.

    Idempotent: single-file grains overwrite; the partitioned ``samples`` tree is cleared first so a
    rebuild never leaves stale partitions. Returns the sidecar metadata (SchemaVer + grain counts).
    """
    out = _resolve_parquet_dir(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    con = _connect(db_path)
    try:
        for grain in _PARQUET_FILE_GRAINS:
            target = (out / f"{grain}.parquet").as_posix()
            con.execute(f"COPY (SELECT * FROM {grain}) TO '{target}' (FORMAT PARQUET)")
            counts[grain] = con.execute(f"SELECT count(*) FROM {grain}").fetchone()[0]
        for grain, parts in _PARQUET_PARTITIONED.items():
            part_dir = out / grain
            if part_dir.exists():
                shutil.rmtree(part_dir)
            target = part_dir.as_posix()
            part_cols = ", ".join(parts)
            con.execute(
                f"COPY (SELECT * FROM {grain}) TO '{target}' "
                f"(FORMAT PARQUET, PARTITION_BY ({part_cols}), OVERWRITE_OR_IGNORE)"
            )
            counts[grain] = con.execute(f"SELECT count(*) FROM {grain}").fetchone()[0]
    finally:
        con.close()
    meta = {
        "schema_version": LAKE_SCHEMA_VERSION,
        "trace_field_count": len(TRACE_FIELDS),
        "partitioned": {g: list(p) for g, p in _PARQUET_PARTITIONED.items()},
        "grains": counts,
        "written_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (out / "_schema.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def read_parquet_surface(
    out_dir: str | Path,
    grain: str,
    *,
    columns: str = "*",
    where: str | None = None,
) -> tuple[list[str], list[tuple]]:
    """Read a Parquet grain back with ``union_by_name`` (additive-evolution tolerant).

    ``samples`` is read as a hive-partitioned tree; the other grains as single files. Uses an
    in-memory DuckDB — no lake db handle needed — so downstream ML tooling can read the surface
    without the journal-path write guard.
    """
    import duckdb

    out = _resolve_parquet_dir(out_dir)
    part_dir = out / grain
    if part_dir.is_dir():
        glob = (part_dir / "**" / "*.parquet").as_posix()
        src = f"read_parquet('{glob}', union_by_name=true, hive_partitioning=true)"
    else:
        src = f"read_parquet('{(out / f'{grain}.parquet').as_posix()}', union_by_name=true)"
    sql = f"SELECT {columns} FROM {src}"
    if where:
        sql += f" WHERE {where}"
    con = duckdb.connect()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, cur.fetchall()
    finally:
        con.close()


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
    p.add_argument(
        "--fuel-effect",
        type=float,
        default=DEFAULT_FUEL_EFFECT_S_PER_KG,
        help="fuel-correction prior in s/kg for fuel-corrected laptime (default %(default)s)",
    )
    p.add_argument(
        "--parquet",
        nargs="?",
        const="journal/parquet",
        default=None,
        help="emit the lake grains to Parquet under this dir (default journal/parquet)",
    )
    p.add_argument("--report", choices=list_reports(), help="run a named flagship report")
    p.add_argument("--query", help="run an arbitrary SQL query against the lake")
    p.add_argument("--limit", type=int, default=50, help="max rows to print")
    args = p.parse_args(argv)

    if args.lap_dir is not None:
        print(
            build_lake(
                args.lap_dir,
                args.db,
                include_samples=not args.no_samples,
                fuel_effect_s_per_kg=args.fuel_effect,
            ).as_text()
        )
    if args.parquet is not None:
        meta = export_parquet(args.db, args.parquet)
        print(
            f"parquet surface: {args.parquet}  schema={meta['schema_version']}  "
            f"grains={ {k: meta['grains'][k] for k in sorted(meta['grains'])} }"
        )
    if args.report:
        cols, rows = run_report(args.db, args.report)
        _print_table(cols, rows, args.limit)
    if args.query:
        cols, rows = run_query(args.db, args.query)
        _print_table(cols, rows, args.limit)
    if args.lap_dir is None and args.parquet is None and not args.report and not args.query:
        p.error("nothing to do: pass --lap-dir (build), --parquet, --report, and/or --query")
    return 0


if __name__ == "__main__":
    import sys

    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
