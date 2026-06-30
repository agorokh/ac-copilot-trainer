"""Persistent driver profile roll-up over immutable lap archives (issue #403).

The profile is compacted state under ``journal/driver/profile.json``. It is
rebuilt from ``journal/laps/lap_*.json`` without mutating those raw archives and
preserves operator-owned preferences/focus metadata across updates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from tools.lap_archive_export import iter_lap_archive_paths, lap_is_valid, load_lap_archive

PROFILE_SCHEMA_VERSION = 1
DEFAULT_DRIVER_ID = "local-driver"
DEFAULT_PROFILE_PATH = Path("journal/driver/profile.json")
NON_DRIVER_LAP_SOURCES = frozenset({"imported", "reference", "reference_archive"})


@dataclass(frozen=True)
class ProfileSummary:
    """Summary of one profile update."""

    path: Path
    driver_id: str
    sessions: int
    personal_bests: int
    corners: int
    source_laps: int

    def render(self) -> str:
        return (
            f"driver profile updated: {self.path} "
            f"(driver={self.driver_id}, sessions={self.sessions}, "
            f"personal_bests={self.personal_bests}, corners={self.corners}, "
            f"source_laps={self.source_laps})"
        )


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if positive and parsed <= 0:
        return None
    return parsed


def _num_ms(value: Any) -> int | None:
    parsed = _num(value, positive=True)
    if parsed is None:
        return None
    return int(round(parsed))


def _avg(values: Iterable[float | None]) -> float | None:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return None
    return float(sum(finite) / len(finite))


def _median_float(values: Iterable[float | None]) -> float | None:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return None
    return float(median(finite))


def _safe_population_stdev(values: list[int]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _combo_key(car_id: Any, track_id: Any, track_layout: Any = None) -> str:
    car = str(car_id or "unknown_car")
    track = str(track_id or "unknown_track")
    layout = str(track_layout or "")
    return f"{car}|{track}|{layout}"


def _session_key(session_uuid: Any, car_id: Any, track_id: Any, track_layout: Any = None) -> str:
    session = str(session_uuid or "unknown_session")
    return f"{session}|{_combo_key(car_id, track_id, track_layout)}"


def _corner_key(car_id: Any, track_id: Any, track_layout: Any, corner_index: Any) -> str:
    return f"{_combo_key(car_id, track_id, track_layout)}|corner:{int(corner_index)}"


def _default_profile(driver_id: str) -> dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "driver_id": driver_id,
        "updated_at": None,
        "preferences": {},
        "focus_corners": {},
        "session_rollups": {},
        "personal_bests": {},
        "consistency": {},
        "corner_history": {},
        "source": {"lap_count": 0, "valid_laps": 0, "skipped": []},
    }


def _rollups_from_existing_bests(existing: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rollups: dict[str, dict[str, Any]] = {}
    personal_bests = existing.get("personal_bests")
    if not isinstance(personal_bests, Mapping):
        return rollups
    for combo, row in personal_bests.items():
        if not isinstance(row, Mapping):
            continue
        lap_ms = _num_ms(row.get("lap_ms"))
        if lap_ms is None:
            continue
        car_id = row.get("car_id")
        track_id = row.get("track_id")
        track_layout = row.get("track_layout")
        if not car_id or not track_id:
            parts = str(combo).split("|")
            car_id = car_id or (parts[0] if len(parts) > 0 else None)
            track_id = track_id or (parts[1] if len(parts) > 1 else None)
            track_layout = (
                track_layout if track_layout is not None else (parts[2] if len(parts) > 2 else None)
            )
        session_uuid = row.get("session_uuid") or f"pb-{row.get('lap_uuid') or combo}"
        key = _session_key(session_uuid, car_id, track_id, track_layout)
        rollups[key] = {
            "session_uuid": session_uuid,
            "car_id": car_id,
            "track_id": track_id,
            "track_layout": track_layout,
            "first_exported_at": row.get("exported_at"),
            "last_exported_at": row.get("exported_at"),
            "first_lap_n": None,
            "last_lap_n": None,
            "lap_count": 1,
            "valid_laps": 1,
            "best_lap_ms": lap_ms,
            "median_lap_ms": float(lap_ms),
            "consistency_ms": None,
            "best_lap_uuid": row.get("lap_uuid"),
            "best_source_file": row.get("source_file"),
        }
    return rollups


def load_profile(
    path: str | Path = DEFAULT_PROFILE_PATH, *, driver_id: str = DEFAULT_DRIVER_ID
) -> dict[str, Any]:
    """Load an existing profile, returning a default shell when the file is absent."""
    profile_path = Path(path)
    if not profile_path.exists():
        return _default_profile(driver_id)
    try:
        loaded = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_profile(driver_id)
    if not isinstance(loaded, dict) or loaded.get("schema_version") != PROFILE_SCHEMA_VERSION:
        return _default_profile(driver_id)
    loaded.setdefault("driver_id", driver_id)
    loaded["preferences"] = _mapping_or_empty(loaded.get("preferences"))
    loaded["focus_corners"] = _mapping_or_empty(loaded.get("focus_corners"))
    loaded["session_rollups"] = _mapping_or_empty(loaded.get("session_rollups"))
    loaded["personal_bests"] = _mapping_or_empty(loaded.get("personal_bests"))
    loaded["consistency"] = _mapping_or_empty(loaded.get("consistency"))
    loaded["corner_history"] = _mapping_or_empty(loaded.get("corner_history"))
    loaded["source"] = _mapping_or_empty(loaded.get("source")) or {
        "lap_count": 0,
        "valid_laps": 0,
        "skipped": [],
    }
    return loaded


def _is_driver_lap(record: Mapping[str, Any]) -> bool:
    source = str(record.get("source") or "").strip().lower()
    return source not in NON_DRIVER_LAP_SOURCES


def _corner_rows_from_record(path: Path, record: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not lap_is_valid(dict(record)):
        return []
    car = record.get("car") if isinstance(record.get("car"), Mapping) else {}
    track = record.get("track") if isinstance(record.get("track"), Mapping) else {}
    lap = record.get("lap") if isinstance(record.get("lap"), Mapping) else {}
    corners = record.get("corners")
    if not isinstance(corners, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, corner in enumerate(corners):
        if not isinstance(corner, Mapping):
            continue
        out.append(
            {
                "source_file": path.name,
                "lap_uuid": record.get("lap_uuid"),
                "session_uuid": record.get("session_uuid"),
                "car_id": car.get("id"),
                "track_id": track.get("id"),
                "track_layout": track.get("layout"),
                "exported_at": record.get("exported_at"),
                "lap_n": lap.get("lap_n"),
                "corner_index": idx,
                "label": corner.get("label") or f"T{idx + 1}",
                "entry_speed_kmh": _num(corner.get("entrySpeed")),
                "min_speed_kmh": _num(corner.get("minSpeed")),
                "exit_speed_kmh": _num(corner.get("exitSpeed")),
                "brake_point_spline": _num(corner.get("brakePointSpline")),
                "trail_brake_ratio": _num(corner.get("trailBrakeRatio")),
                "throttle_avg": _num(corner.get("throttleAvg")),
                "steer_reversals": _num(corner.get("steerReversals")),
                "traction_circle_proxy": _num(corner.get("tractionCircleProxy")),
            }
        )
    return out


def _corner_history(rows_by_key: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    history: dict[str, dict[str, Any]] = {}
    for key, rows in sorted(rows_by_key.items()):
        ordered = sorted(
            rows,
            key=lambda row: (
                str(row.get("exported_at") or ""),
                str(row.get("session_uuid") or ""),
                int(row.get("lap_n") or 0),
                str(row.get("source_file") or ""),
            ),
        )
        first = ordered[0]
        min_speeds = [row.get("min_speed_kmh") for row in ordered]
        first_min = next((speed for speed in min_speeds if speed is not None), None)
        last_min = next(
            (
                row.get("min_speed_kmh")
                for row in reversed(ordered)
                if row.get("min_speed_kmh") is not None
            ),
            None,
        )
        exported = [
            str(row.get("exported_at"))
            for row in ordered
            if isinstance(row.get("exported_at"), str)
        ]
        sessions = {str(row.get("session_uuid")) for row in ordered if row.get("session_uuid")}
        history[key] = {
            "car_id": first.get("car_id"),
            "track_id": first.get("track_id"),
            "track_layout": first.get("track_layout"),
            "corner_index": first.get("corner_index"),
            "label": first.get("label"),
            "session_count": len(sessions),
            "valid_laps": len(ordered),
            "first_exported_at": min(exported) if exported else None,
            "last_exported_at": max(exported) if exported else None,
            "first_min_speed_kmh": first_min,
            "last_min_speed_kmh": last_min,
            "best_min_speed_kmh": max((v for v in min_speeds if v is not None), default=None),
            "median_min_speed_kmh": _median_float(min_speeds),
            "delta_min_speed_kmh": (
                round(last_min - first_min, 3)
                if first_min is not None and last_min is not None
                else None
            ),
            "avg_entry_speed_kmh": _avg(row.get("entry_speed_kmh") for row in ordered),
            "avg_exit_speed_kmh": _avg(row.get("exit_speed_kmh") for row in ordered),
            "avg_trail_brake_ratio": _avg(row.get("trail_brake_ratio") for row in ordered),
            "avg_throttle": _avg(row.get("throttle_avg") for row in ordered),
            "avg_steer_reversals": _avg(row.get("steer_reversals") for row in ordered),
            "avg_traction_circle_proxy": _avg(row.get("traction_circle_proxy") for row in ordered),
            "latest_source_file": ordered[-1].get("source_file"),
        }
    return history


def _first_text(*values: Any) -> str | None:
    texts = [value for value in values if isinstance(value, str) and value]
    return min(texts) if texts else None


def _last_text(*values: Any) -> str | None:
    texts = [value for value in values if isinstance(value, str) and value]
    return max(texts) if texts else None


def _merge_session_rollup(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    old_laps = int(existing.get("lap_count") or 0)
    new_laps = int(incoming.get("lap_count") or 0)
    if new_laps > old_laps:
        return dict(incoming)

    old_best = _num_ms(existing.get("best_lap_ms"))
    new_best = _num_ms(incoming.get("best_lap_ms"))
    best_source = existing
    if new_best is not None and (old_best is None or new_best < old_best):
        best_source = incoming

    merged = dict(existing)
    merged.update(
        {
            "first_exported_at": _first_text(
                existing.get("first_exported_at"), incoming.get("first_exported_at")
            ),
            "last_exported_at": _last_text(
                existing.get("last_exported_at"), incoming.get("last_exported_at")
            ),
            "first_lap_n": min(
                [v for v in (existing.get("first_lap_n"), incoming.get("first_lap_n")) if v],
                default=None,
            ),
            "last_lap_n": max(
                [v for v in (existing.get("last_lap_n"), incoming.get("last_lap_n")) if v],
                default=None,
            ),
            "lap_count": old_laps + new_laps,
            "valid_laps": int(existing.get("valid_laps") or 0)
            + int(incoming.get("valid_laps") or 0),
            "best_lap_ms": best_source.get("best_lap_ms"),
            "best_lap_uuid": best_source.get("best_lap_uuid"),
            "best_source_file": best_source.get("best_source_file"),
            "consistency_ms": None,
        }
    )
    return merged


def _weighted_avg(old_value: Any, old_count: int, new_value: Any, new_count: int) -> float | None:
    old = _num(old_value)
    new = _num(new_value)
    if old is None:
        return new
    if new is None:
        return old
    total = old_count + new_count
    if total <= 0:
        return new
    return ((old * old_count) + (new * new_count)) / total


def _merge_corner_row(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    old_laps = int(existing.get("valid_laps") or 0)
    new_laps = int(incoming.get("valid_laps") or 0)
    if new_laps > old_laps:
        return dict(incoming)

    first_min = _num(existing.get("first_min_speed_kmh"))
    last_min = _num(incoming.get("last_min_speed_kmh"))
    if last_min is None:
        last_min = _num(existing.get("last_min_speed_kmh"))
    best_values = [
        value
        for value in (
            _num(existing.get("best_min_speed_kmh")),
            _num(incoming.get("best_min_speed_kmh")),
        )
        if value is not None
    ]
    merged = dict(existing)
    merged.update(
        {
            "session_count": max(
                int(existing.get("session_count") or 0),
                int(incoming.get("session_count") or 0),
            ),
            "valid_laps": old_laps + new_laps,
            "first_exported_at": _first_text(
                existing.get("first_exported_at"), incoming.get("first_exported_at")
            ),
            "last_exported_at": _last_text(
                existing.get("last_exported_at"), incoming.get("last_exported_at")
            ),
            "last_min_speed_kmh": last_min,
            "best_min_speed_kmh": max(best_values, default=None),
            "avg_entry_speed_kmh": _weighted_avg(
                existing.get("avg_entry_speed_kmh"),
                old_laps,
                incoming.get("avg_entry_speed_kmh"),
                new_laps,
            ),
            "avg_exit_speed_kmh": _weighted_avg(
                existing.get("avg_exit_speed_kmh"),
                old_laps,
                incoming.get("avg_exit_speed_kmh"),
                new_laps,
            ),
            "avg_trail_brake_ratio": _weighted_avg(
                existing.get("avg_trail_brake_ratio"),
                old_laps,
                incoming.get("avg_trail_brake_ratio"),
                new_laps,
            ),
            "avg_throttle": _weighted_avg(
                existing.get("avg_throttle"), old_laps, incoming.get("avg_throttle"), new_laps
            ),
            "avg_steer_reversals": _weighted_avg(
                existing.get("avg_steer_reversals"),
                old_laps,
                incoming.get("avg_steer_reversals"),
                new_laps,
            ),
            "latest_source_file": incoming.get("latest_source_file")
            or existing.get("latest_source_file"),
        }
    )
    if first_min is not None and last_min is not None:
        merged["delta_min_speed_kmh"] = round(last_min - first_min, 3)
    return merged


def _merge_rows(
    existing: Mapping[str, Any],
    incoming: Mapping[str, dict[str, Any]],
    *,
    row_merger: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {
        str(key): dict(value) for key, value in existing.items() if isinstance(value, Mapping)
    }
    for key, row in incoming.items():
        previous = merged.get(key)
        merged[key] = row_merger(previous, row) if isinstance(previous, Mapping) else dict(row)
    return merged


def _rollups_from_archives(
    inputs: Iterable[str | Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], int, int, list[str]]:
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    corners_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_laps = 0
    valid_laps = 0
    skipped: list[str] = []
    for path in iter_lap_archive_paths(inputs):
        try:
            record = load_lap_archive(path)
        except Exception as exc:  # noqa: BLE001 - one corrupt archive must not erase a profile
            skipped.append(f"{Path(path).name}: {type(exc).__name__}")
            continue
        source_laps += 1
        if not _is_driver_lap(record):
            skipped.append(f"{Path(path).name}: non_driver_source:{record.get('source')}")
            continue
        is_valid = lap_is_valid(record)
        if is_valid:
            valid_laps += 1
        car = record.get("car") if isinstance(record.get("car"), Mapping) else {}
        track = record.get("track") if isinstance(record.get("track"), Mapping) else {}
        grouped[
            _session_key(
                record.get("session_uuid"),
                car.get("id"),
                track.get("id"),
                track.get("layout"),
            )
        ].append((Path(path), record))
        if is_valid:
            for row in _corner_rows_from_record(Path(path), record):
                corners_by_key[
                    _corner_key(
                        row.get("car_id"),
                        row.get("track_id"),
                        row.get("track_layout"),
                        row.get("corner_index"),
                    )
                ].append(row)

    rollups: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        rows.sort(
            key=lambda item: (
                (item[1].get("lap") or {}).get("lap_n")
                if isinstance(item[1].get("lap"), dict)
                else 0,
                item[1].get("exported_at") or "",
                item[0].name,
            )
        )
        first = rows[0][1]
        car = first.get("car") if isinstance(first.get("car"), Mapping) else {}
        track = first.get("track") if isinstance(first.get("track"), Mapping) else {}
        valid_rows = [
            (path, record, _num_ms((record.get("lap") or {}).get("lap_ms")))
            for path, record in rows
            if isinstance(record.get("lap"), Mapping) and lap_is_valid(record)
        ]
        valid_rows = [(path, record, lap_ms) for path, record, lap_ms in valid_rows if lap_ms]
        lap_times = [lap_ms for _, _, lap_ms in valid_rows if lap_ms is not None]
        best_path: Path | None = None
        best_record: dict[str, Any] | None = None
        best_ms: int | None = None
        if valid_rows:
            best_path, best_record, best_ms = min(
                valid_rows,
                key=lambda item: (item[2] or 0, item[1].get("exported_at") or "", item[0].name),
            )
        exported = [r.get("exported_at") for _, r in rows if isinstance(r.get("exported_at"), str)]
        lap_ns = [
            (r.get("lap") or {}).get("lap_n")
            for _, r in rows
            if isinstance(r.get("lap"), Mapping)
            and isinstance((r.get("lap") or {}).get("lap_n"), int)
        ]
        rollups[key] = {
            "session_uuid": first.get("session_uuid"),
            "car_id": car.get("id"),
            "track_id": track.get("id"),
            "track_layout": track.get("layout"),
            "first_exported_at": min(exported) if exported else None,
            "last_exported_at": max(exported) if exported else None,
            "first_lap_n": min(lap_ns) if lap_ns else None,
            "last_lap_n": max(lap_ns) if lap_ns else None,
            "lap_count": len(rows),
            "valid_laps": len(lap_times),
            "best_lap_ms": best_ms,
            "median_lap_ms": float(median(lap_times)) if lap_times else None,
            "consistency_ms": _safe_population_stdev(lap_times),
            "best_lap_uuid": best_record.get("lap_uuid") if best_record else None,
            "best_source_file": best_path.name if best_path else None,
        }
    return rollups, _corner_history(corners_by_key), source_laps, valid_laps, skipped


def build_profile(
    inputs: Iterable[str | Path],
    *,
    driver_id: str = DEFAULT_DRIVER_ID,
    existing: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a compacted driver profile by merging archive-derived roll-ups."""
    effective_driver_id = str(driver_id or DEFAULT_DRIVER_ID)
    if driver_id == DEFAULT_DRIVER_ID and isinstance(existing, Mapping):
        prior_driver_id = existing.get("driver_id")
        if isinstance(prior_driver_id, str) and prior_driver_id:
            effective_driver_id = prior_driver_id
    base = _default_profile(effective_driver_id)
    if existing:
        base["preferences"] = _mapping_or_empty(existing.get("preferences"))
        base["focus_corners"] = _mapping_or_empty(existing.get("focus_corners"))
        base["session_rollups"] = {
            **_rollups_from_existing_bests(existing),
            **_mapping_or_empty(existing.get("session_rollups")),
        }
        base["corner_history"] = _mapping_or_empty(existing.get("corner_history"))

    new_rollups, new_corners, source_laps, valid_laps, skipped = _rollups_from_archives(inputs)
    base["session_rollups"] = _merge_rows(
        base["session_rollups"], new_rollups, row_merger=_merge_session_rollup
    )
    base["corner_history"] = _merge_rows(
        base["corner_history"], new_corners, row_merger=_merge_corner_row
    )
    rollups = base["session_rollups"]

    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rollup in rollups.values():
        if not isinstance(rollup, Mapping):
            continue
        combo = _combo_key(rollup.get("car_id"), rollup.get("track_id"), rollup.get("track_layout"))
        by_combo[combo].append(dict(rollup))

    personal_bests: dict[str, dict[str, Any]] = {}
    consistency: dict[str, dict[str, Any]] = {}
    for combo, combo_rollups in sorted(by_combo.items()):
        valid_combo = [r for r in combo_rollups if _num_ms(r.get("best_lap_ms")) is not None]
        if not valid_combo:
            continue
        best = min(
            valid_combo,
            key=lambda r: (
                int(r["best_lap_ms"]),
                r.get("last_exported_at") or "",
                r.get("best_source_file") or "",
            ),
        )
        personal_bests[combo] = {
            "car_id": best.get("car_id"),
            "track_id": best.get("track_id"),
            "track_layout": best.get("track_layout"),
            "lap_ms": int(best["best_lap_ms"]),
            "lap_uuid": best.get("best_lap_uuid"),
            "session_uuid": best.get("session_uuid"),
            "source_file": best.get("best_source_file"),
            "exported_at": best.get("last_exported_at"),
        }
        session_bests = [int(r["best_lap_ms"]) for r in valid_combo]
        consistency[combo] = {
            "car_id": best.get("car_id"),
            "track_id": best.get("track_id"),
            "track_layout": best.get("track_layout"),
            "session_count": len(valid_combo),
            "valid_laps": sum(int(r.get("valid_laps") or 0) for r in valid_combo),
            "best_lap_ms": min(session_bests),
            "median_session_best_ms": float(median(session_bests)),
            "consistency_ms": _safe_population_stdev(session_bests),
        }

    base.update(
        {
            "driver_id": effective_driver_id,
            "updated_at": generated_at or _iso_now(),
            "personal_bests": personal_bests,
            "consistency": consistency,
            "source": {
                "lap_count": source_laps,
                "valid_laps": valid_laps,
                "skipped": skipped,
            },
        }
    )
    return base


def _resolve_profile_path(path: str | Path) -> Path:
    raw = Path(path)
    base_dir = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    tail = tuple(part.lower() for part in resolved.parts[-3:])
    if tail != ("journal", "driver", "profile.json"):
        raise ValueError(f"{raw}: profile path must end with journal/driver/profile.json")
    return resolved


def write_profile(profile: Mapping[str, Any], path: str | Path = DEFAULT_PROFILE_PATH) -> Path:
    """Atomically write ``profile`` under ``journal/driver/profile.json``."""
    profile_path = _resolve_profile_path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(profile_path.parent), prefix=".profile.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp_name, profile_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return profile_path


def update_profile(
    inputs: Iterable[str | Path],
    *,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    driver_id: str = DEFAULT_DRIVER_ID,
    generated_at: str | None = None,
) -> ProfileSummary:
    """Load, merge, and persist the driver profile."""
    existing = load_profile(profile_path, driver_id=driver_id)
    profile = build_profile(
        inputs, driver_id=driver_id, existing=existing, generated_at=generated_at
    )
    path = write_profile(profile, profile_path)
    return ProfileSummary(
        path=path,
        driver_id=profile["driver_id"],
        sessions=len(profile.get("session_rollups") or {}),
        personal_bests=len(profile.get("personal_bests") or {}),
        corners=len(profile.get("corner_history") or {}),
        source_laps=int((profile.get("source") or {}).get("lap_count") or 0),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lap-dir",
        action="append",
        type=Path,
        default=[],
        help="Directory of lap_*.json archives; repeat for multiple corpora.",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--driver-id", default=DEFAULT_DRIVER_ID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.lap_dir:
        parser.error("pass at least one --lap-dir")
    summary = update_profile(args.lap_dir, profile_path=args.profile, driver_id=args.driver_id)
    print(summary.render())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
