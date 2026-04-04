"""Per-lap feature extraction from JSON payloads (issue #49).

Pure Python + ``typing`` only so tests and non-ML installs stay lightweight.
Optional telemetry lives under ``telemetry.corners`` on ``lap_complete``-shaped dicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SPEED_METRICS = frozenset({"min_speed_kmh", "apex_speed_kmh"})


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_metric_key(name: str) -> str | None:
    """Map JSON camelCase or snake_case to internal keys."""
    if not name:
        return None
    key = str(name).strip()
    aliases = {
        "minspeedkmh": "min_speed_kmh",
        "apexspeedkmh": "apex_speed_kmh",
        "brakedistancem": "brake_distance_m",
        "min_speed_kmh": "min_speed_kmh",
        "apex_speed_kmh": "apex_speed_kmh",
        "brake_distance_m": "brake_distance_m",
    }
    compact = key.replace("_", "").lower()
    return aliases.get(compact) or aliases.get(key.lower())


def extract_corner_table(lap: Mapping[str, Any]) -> dict[int, dict[str, float]]:
    """Parse ``telemetry.corners`` into ``corner_id -> {metric: value}``.

    Each corner object should include ``id`` (int) and numeric telemetry fields.
    Unknown keys are ignored; speeds are the primary ranking signals (issue #49).
    """
    tel = lap.get("telemetry")
    if not isinstance(tel, dict):
        return {}
    raw_corners = tel.get("corners")
    if not isinstance(raw_corners, list):
        return {}
    out: dict[int, dict[str, float]] = {}
    for item in raw_corners:
        if not isinstance(item, dict):
            continue
        cid_raw = item.get("id")
        try:
            cid = int(cid_raw)
        except (TypeError, ValueError):
            continue
        bucket: dict[str, float] = {}
        for k, v in item.items():
            if k == "id":
                continue
            nk = _normalize_metric_key(str(k))
            if nk is None or nk not in _SPEED_METRICS:
                continue
            fv = _as_float(v)
            if fv is not None:
                bucket[nk] = fv
        if bucket:
            out[cid] = bucket
    return out
