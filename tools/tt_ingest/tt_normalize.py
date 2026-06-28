"""Normalize raw Track Titan vulcan sessions into a stable, queryable index row
(issue #353, milestone M-TT0).

The raw session JSON is retained immutably in the lake (``tt_export``); this layer
projects each session into a flat, lossless-for-indexing row keyed by
car + track + setup + conditions — the join key the autonomous harness and the
coaching lake consume. The reference-lap → ``lap_archive`` schema bridge (the M0
``--reference-archive`` feed) is milestone M-TT2 and lands separately.

Pure functions only — fixture-tested, no network.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

INDEX_SCHEMA_VERSION = 1

#: ``lap_attributes`` keys we lift into the flat conditions block. Anything absent
#: degrades to ``None`` rather than raising — retention must never drop a session.
_CONDITION_KEYS = (
    "airTemp",
    "roadTemp",
    "fuelLevel",
    "tcEnabled",
    "absEnabled",
    "absSetting",
    "carSetupName",
    "isFixedSetup",
    "tyreCompound",
)


def split_session_id(session_id: str) -> tuple[str | None, str | None]:
    """Best-effort split of ``{uid}#{sessionKey}``; returns ``(None, None)`` if unusable."""
    if not isinstance(session_id, str) or "#" not in session_id:
        return None, None
    uid, _, session_key = session_id.partition("#")
    return (uid or None), (session_key or None)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def normalize_session(session: Mapping[str, Any]) -> dict[str, Any]:
    """Project one raw vulcan session into a flat index row.

    Tolerant by design: any missing field becomes ``None`` so the row is always
    writable. ``conditions`` lifts the per-lap ``lap_attributes`` block (grip, temps,
    tyre compound, setup name, driver aids) that makes the row a real join key.
    """
    if not isinstance(session, Mapping):
        raise TypeError("session must be a mapping")

    session_id = session.get("id")
    uid, session_key = split_session_id(session_id) if isinstance(session_id, str) else (None, None)
    if uid is None:
        uid = _first(session, "user_id")

    game = session.get("game")
    game_name = game.get("name") if isinstance(game, Mapping) else None

    lap_attrs = session.get("lap_attributes")
    lap_attrs = lap_attrs if isinstance(lap_attrs, Mapping) else {}
    conditions = {key: lap_attrs.get(key) for key in _CONDITION_KEYS}
    conditions["trackGrip"] = _first(session, "track_grip")

    return {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "session_id": session_id if isinstance(session_id, str) else None,
        "uid": uid,
        "session_key": session_key,
        "timestamp": session.get("timestamp"),
        "last_updated": session.get("last_updated"),
        "game_id": _first(session, "game_id"),
        "game_name": game_name or (game.get("gameId") if isinstance(game, Mapping) else None),
        "car_id": _first(session, "car_id"),
        "car_name": _first(session, "carName"),
        "car_class": _first(session, "car_class"),
        "car_performance_index": _first(session, "car_performance_index"),
        "track_id": _first(session, "track_id"),
        "track_name": _first(session, "trackName"),
        "weather_id": _first(session, "weather_id"),
        "session_type": _first(session, "session_type"),
        "ghost_version": _first(session, "ghost_version"),
        "best_lap_ms": _first(session, "bestLapTime"),
        "lap_count": _first(session, "lapCount"),
        "driver_name": _first(session, "driver_name"),
        "season_id": _first(session, "season_id"),
        "status": _first(session, "status"),
        "conditions": conditions,
    }


def normalize_sessions(sessions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a list of raw sessions, skipping any that are not mappings."""
    return [normalize_session(s) for s in sessions if isinstance(s, Mapping)]


def build_sessions_index(rows: list[Mapping[str, Any]], *, generated_at: str) -> dict[str, Any]:
    """Wrap normalized rows in a top-level index document for the lake."""
    return {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": generated_at,
        "session_count": len(rows),
        "sessions": [dict(r) for r in rows],
    }
