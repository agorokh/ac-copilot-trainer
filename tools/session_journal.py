"""Session journal JSON schema (issue #47) — validate exports from AC Copilot Trainer."""

from __future__ import annotations

from typing import Any

JOURNAL_SCHEMA_VERSION = 1

REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "exported_at",
        "app_version_ui",
        "session_key",
        "car",
        "track",
        "conditions",
        "summary",
        "lap_history",
        "corners_last_lap",
        "coaching_hints_last",
        "llm_debrief",
    }
)


def validate_session_journal(obj: Any) -> list[str]:
    """Return a list of human-readable validation errors; empty means OK."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["root must be a JSON object"]
    missing = REQUIRED_TOP_LEVEL_KEYS - obj.keys()
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
    extra = obj.keys() - REQUIRED_TOP_LEVEL_KEYS
    if extra:
        errors.append(f"unknown keys: {sorted(extra)}")

    sv = obj.get("schema_version")
    if sv is not None and sv != JOURNAL_SCHEMA_VERSION:
        errors.append(f"schema_version must be {JOURNAL_SCHEMA_VERSION}, got {sv!r}")

    exported = obj.get("exported_at")
    if exported is not None:
        if not isinstance(exported, str) or "T" not in exported or not exported.endswith("Z"):
            errors.append("exported_at must be an ISO-8601 UTC string ending with Z")

    sk = obj.get("session_key")
    if sk is not None and (not isinstance(sk, str) or not sk):
        errors.append("session_key must be a non-empty string")

    for label, key in (("car", "car"), ("track", "track")):
        sub = obj.get(key)
        if sub is not None:
            if not isinstance(sub, dict):
                errors.append(f"{label} must be an object")
            elif "id" not in sub:
                errors.append(f"{label} must contain id")

    cond = obj.get("conditions")
    if cond is not None:
        if not isinstance(cond, dict):
            errors.append("conditions must be an object")
        elif "track_grip" in cond and cond["track_grip"] is not None:
            if not isinstance(cond["track_grip"], (int, float)):
                errors.append("conditions.track_grip must be a number or null")

    summary = obj.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("summary must be an object")
        else:
            for k in ("laps_completed", "best_lap_ms", "last_lap_ms", "avg_lap_ms"):
                if (
                    k in summary
                    and summary[k] is not None
                    and not isinstance(summary[k], (int, float))
                ):
                    errors.append(f"summary.{k} must be a number or null")

    lap_hist = obj.get("lap_history")
    if lap_hist is not None:
        if not isinstance(lap_hist, list):
            errors.append("lap_history must be an array")
        else:
            for i, row in enumerate(lap_hist):
                if not isinstance(row, dict):
                    errors.append(f"lap_history[{i}] must be an object")
                    break
                if "lap_ms" in row and row["lap_ms"] is not None:
                    if not isinstance(row["lap_ms"], (int, float)):
                        errors.append(f"lap_history[{i}].lap_ms must be a number")

    corners = obj.get("corners_last_lap")
    if corners is not None and not isinstance(corners, list):
        errors.append("corners_last_lap must be an array")

    hints = obj.get("coaching_hints_last")
    if hints is not None:
        if not isinstance(hints, list):
            errors.append("coaching_hints_last must be an array")
        else:
            for i, h in enumerate(hints):
                if isinstance(h, dict):
                    if "text" not in h:
                        errors.append(f"coaching_hints_last[{i}] missing text")
                elif not isinstance(h, str):
                    errors.append(f"coaching_hints_last[{i}] must be object or string")

    return errors


def sample_valid_session_journal() -> dict[str, Any]:
    """Fixture aligned with Lua `session_journal.buildRecord` output."""
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "exported_at": "2026-04-03T12:00:00Z",
        "app_version_ui": "v0.4.2",
        "session_key": "ks_lamborghini_huracan_gt3__ks_nordschleife",
        "car": {"id": "ks_lamborghini_huracan_gt3"},
        "track": {"id": "ks_nordschleife"},
        "conditions": {"track_grip": 1.0},
        "summary": {
            "laps_completed": 3,
            "best_lap_ms": 420000,
            "last_lap_ms": 425000,
            "avg_lap_ms": 428000,
        },
        "lap_history": [
            {"lap_ms": 430000, "corner_count": 12},
            {"lap_ms": 425000, "corner_count": 12},
            {"lap_ms": 420000, "corner_count": 12},
        ],
        "corners_last_lap": [
            {
                "label": "T1",
                "entrySpeed": 180.0,
                "minSpeed": 95.0,
                "exitSpeed": 140.0,
                "brakePointSpline": 0.12,
                "trailBrakeRatio": 0.4,
            }
        ],
        "coaching_hints_last": [
            {"kind": "brake", "text": "T1: try braking slightly earlier"},
        ],
        "llm_debrief": None,
    }
