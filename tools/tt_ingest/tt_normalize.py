"""Normalize raw Track Titan exports into stable local trainer data (issue #353).

The raw session JSON is retained immutably in the lake (``tt_export``); this layer
projects each session into a flat, lossless-for-indexing row keyed by
car + track + setup + conditions — the join key the autonomous harness and the
coaching lake consume.

M-TT2 adds the reference-lap → ``lap_archive`` schema bridge that feeds M0
``--reference-archive``. It intentionally refuses to turn a single Track Titan
``/last-session`` segment window into a fake full-lap reference: callers must
provide enough retained windows to cover the lap, or opt into an explicitly
partial debug artifact.

Pure functions only — fixture-tested, no network.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tools.ac_harness.reference_lap import DEFAULT_TRACK_LENGTH_M, build_archive_record

INDEX_SCHEMA_VERSION = 1
TT_REFERENCE_IMPORT_FORMAT = "track_titan_reference_v1"
DEFAULT_REFERENCE_COVERAGE_THRESHOLD = 0.9
DEFAULT_REFERENCE_MAX_SPLINE_GAP = 0.08

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


class TTNormalizeError(ValueError):
    """A raw Track Titan payload cannot be safely normalized."""


@dataclass(frozen=True)
class ReferenceCoverage:
    """Coverage diagnostics for stitched Track Titan reference telemetry."""

    samples: int
    coverage: float
    min_spline: float
    max_spline: float
    max_gap: float
    partial: bool


def _finite_float(raw: Any, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise TTNormalizeError(f"{field} must be numeric, got {raw!r}") from exc
    if not math.isfinite(value):
        raise TTNormalizeError(f"{field} must be finite, got {raw!r}")
    return value


def _bounded01(raw: Any, field: str) -> float:
    value = _finite_float(raw, field)
    if value < 0.0 or value > 1.0:
        raise TTNormalizeError(f"{field} must be in [0, 1], got {raw!r}")
    return value


def _clamped01(raw: Any, field: str) -> float:
    value = _finite_float(raw, field)
    return max(0.0, min(1.0, value))


def _services_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the services ``data`` object from an enveloped or already-unwrapped payload."""
    if not isinstance(payload, Mapping):
        raise TTNormalizeError("Track Titan payload must be a JSON object")
    data = payload.get("data") if "data" in payload and "success" in payload else payload
    if not isinstance(data, Mapping):
        raise TTNormalizeError("Track Titan services payload missing data object")
    return data


def _payload_session(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _services_data(payload)
    session = data.get("session")
    return session if isinstance(session, Mapping) else {}


def _session_from_payload(payloads: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    for payload in payloads:
        session = _payload_session(payload)
        if session:
            return session
    return {}


def _reference_lap_from_payload(payloads: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    for payload in payloads:
        data = _services_data(payload)
        ref = data.get("referenceLap")
        if isinstance(ref, Mapping):
            return ref
    return {}


def _resolve_car_id(session: Mapping[str, Any]) -> str | None:
    for value in (session.get("car_id"), session.get("car")):
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            inner = value.get("car_id") or value.get("id")
            if isinstance(inner, str) and inner:
                return inner
    return None


def _session_key(session: Mapping[str, Any]) -> str | None:
    raw_id = session.get("session_id") or session.get("id")
    if isinstance(raw_id, str):
        _, key = split_session_id(raw_id)
        if key:
            return key
    key = session.get("session_key")
    return key if isinstance(key, str) and key else None


def _identity_value(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _session_identity(session: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "game_id": _identity_value(session.get("game_id")),
        "car_id": _resolve_car_id(session),
        "track_id": _identity_value(session.get("track_id")),
        "session_key": _session_key(session),
        "lap_number": _identity_value(session.get("lap_number")),
    }


def _validated_session_identity(payloads: list[Mapping[str, Any]]) -> dict[str, str | None]:
    identities = [_session_identity(_payload_session(payload)) for payload in payloads]
    if not identities:
        return _session_identity({})
    first = identities[0]
    for index, identity in enumerate(identities[1:], start=1):
        if identity != first:
            raise TTNormalizeError(
                "Track Titan reference payloads must come from one session/lap "
                f"(payload 0={first}, payload {index}={identity})"
            )
    return first


def _raw_trace(payload: Mapping[str, Any], *, channel: str) -> list[Mapping[str, Any]]:
    data = _services_data(payload)
    telemetry = data.get("telemetry")
    if not isinstance(telemetry, Mapping):
        raise TTNormalizeError("Track Titan payload missing telemetry object")
    trace_root = telemetry.get("telemetry")
    if not isinstance(trace_root, Mapping):
        raise TTNormalizeError("Track Titan payload missing telemetry.telemetry object")
    frames = trace_root.get(channel)
    if not isinstance(frames, list) or not frames:
        raise TTNormalizeError(f"Track Titan payload missing telemetry.telemetry.{channel} frames")
    out: list[Mapping[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise TTNormalizeError(f"telemetry.telemetry.{channel} contains a non-object frame")
        out.append(frame)
    return out


def _tt_frame_to_archive_frame(frame: Mapping[str, Any], index: int) -> dict[str, float]:
    spline = _bounded01(frame.get("dist"), f"tt_frame[{index}].dist")
    speed = _finite_float(frame.get("Kmh"), f"tt_frame[{index}].Kmh")
    if speed < 0.0:
        raise TTNormalizeError(f"tt_frame[{index}].Kmh must be non-negative")
    x_raw = frame.get("X")
    y_raw = frame.get("Y")
    px = _finite_float(x_raw, f"tt_frame[{index}].X") if x_raw is not None else spline
    pz = _finite_float(y_raw, f"tt_frame[{index}].Y") if y_raw is not None else 0.0
    return {
        "spline": spline,
        "speed": speed,
        "eMs": _finite_float(frame.get("lTime"), f"tt_frame[{index}].lTime"),
        "throttle": _clamped01(frame.get("throt"), f"tt_frame[{index}].throt"),
        "brake": _clamped01(frame.get("brak"), f"tt_frame[{index}].brak"),
        "steer": _finite_float(frame.get("steer"), f"tt_frame[{index}].steer"),
        "gear": _finite_float(frame.get("gear"), f"tt_frame[{index}].gear"),
        # TT exposes a 2-D path projection. AC's schema wants px/py/pz; keep the
        # path in px/pz and make the absent elevation explicit instead of inventing it.
        "px": px,
        "py": 0.0,
        "pz": pz,
    }


def reference_frames_from_payload(
    payload: Mapping[str, Any],
    *,
    channel: str = "reference",
) -> list[dict[str, float]]:
    """Extract one Track Titan telemetry channel as object-style lap-archive frames."""
    return [
        _tt_frame_to_archive_frame(frame, i)
        for i, frame in enumerate(_raw_trace(payload, channel=channel))
    ]


def merge_reference_frames(
    payloads: list[Mapping[str, Any]],
    *,
    channel: str = "reference",
) -> list[dict[str, float]]:
    """Merge one or more retained TT telemetry windows deterministically.

    ``lTime`` is the primary ordering key because it is lap-time absolute in the
    live captures. ``dist`` remains the spatial integrity check performed by
    :func:`reference_coverage`.
    """
    keyed: OrderedDict[tuple[float, float], dict[str, float]] = OrderedDict()
    for payload_index, payload in enumerate(payloads):
        frames = reference_frames_from_payload(payload, channel=channel)
        last_time = -math.inf
        for frame_index, frame in enumerate(frames):
            if frame["eMs"] < last_time:
                raise TTNormalizeError(
                    f"payload {payload_index} telemetry time moves backward at frame {frame_index}"
                )
            last_time = frame["eMs"]
            key = (round(frame["eMs"], 3), round(frame["spline"], 6))
            keyed.setdefault(key, frame)
    merged = sorted(keyed.values(), key=lambda f: (f["eMs"], f["spline"]))
    if len(merged) < 2:
        raise TTNormalizeError("Track Titan reference telemetry needs at least two samples")
    return merged


def reference_coverage(
    frames: list[Mapping[str, Any]],
    *,
    max_spline_gap: float = DEFAULT_REFERENCE_MAX_SPLINE_GAP,
    threshold: float = DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
) -> ReferenceCoverage:
    """Measure contiguous spline coverage for merged reference frames."""
    if not frames:
        raise TTNormalizeError("reference telemetry is empty")
    splines = sorted(
        {
            _bounded01(frame.get("spline"), f"reference[{i}].spline")
            for i, frame in enumerate(frames)
        }
    )
    if len(splines) < 2:
        raise TTNormalizeError("reference telemetry needs at least two distinct spline samples")
    gaps = [b - a for a, b in zip(splines, splines[1:], strict=False)]
    gaps.append((1.0 - splines[-1]) + splines[0])
    max_gap = max(gaps, default=1.0)
    coverage = min(1.0, sum(gap for gap in gaps if gap <= max_spline_gap))
    partial = coverage < threshold or max_gap > max_spline_gap
    return ReferenceCoverage(
        samples=len(frames),
        coverage=coverage,
        min_spline=splines[0],
        max_spline=splines[-1],
        max_gap=max_gap,
        partial=partial,
    )


def build_reference_archive(
    payloads: list[Mapping[str, Any]],
    *,
    channel: str = "reference",
    coverage_threshold: float = DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
    max_spline_gap: float = DEFAULT_REFERENCE_MAX_SPLINE_GAP,
    allow_partial: bool = False,
    track_length_m: float = DEFAULT_TRACK_LENGTH_M,
    exported_at: str | None = None,
) -> dict[str, Any]:
    """Build a schema-v1 lap archive from retained Track Titan reference telemetry.

    By default this refuses partial stitched windows. ``allow_partial`` exists for
    debugging capture coverage only; the emitted archive carries
    ``generator.tt_reference.partial = true`` so runtime consumers can reject it.
    """
    if not payloads:
        raise TTNormalizeError("no Track Titan payloads supplied")
    frames = merge_reference_frames(payloads, channel=channel)
    coverage = reference_coverage(
        frames, max_spline_gap=max_spline_gap, threshold=coverage_threshold
    )
    if coverage.partial and not allow_partial:
        raise TTNormalizeError(
            "Track Titan reference telemetry is partial "
            f"(coverage={coverage.coverage:.3f}, threshold={coverage_threshold:.3f}, "
            f"min={coverage.min_spline:.3f}, max={coverage.max_spline:.3f}, "
            f"max_gap={coverage.max_gap:.3f}); capture/stitch more segment windows "
            "or pass --allow-partial for a debug-only archive"
        )

    identity = _validated_session_identity(payloads)
    session = _session_from_payload(payloads)
    ref = _reference_lap_from_payload(payloads)
    car_id = identity["car_id"] or "track_titan_car"
    track_id = identity["track_id"] or "track_titan_track"
    lap_n = identity["lap_number"] or ref.get("lap_number") or session.get("lap_number") or 1
    record = build_archive_record(
        frames,
        car_id=str(car_id),
        track_id=str(track_id),
        track_length_m=track_length_m,
        lap_n=int(lap_n),
        exported_at=exported_at,
        generator_name="tools.tt_ingest.tt_normalize",
    )
    record["import_format"] = TT_REFERENCE_IMPORT_FORMAT
    record["coaching"]["rules_hints"] = [
        "Track Titan imported reference; provenance is personal own-account services export.",
        "TT X/Y are preserved as a 2-D px/pz path projection; py is set to 0.0.",
    ]
    record["generator"]["decision_issue"] = 353
    record["generator"]["tt_reference"] = {
        "schema_version": 1,
        "channel": channel,
        "payload_count": len(payloads),
        "partial": coverage.partial,
        "coverage": coverage.coverage,
        "coverage_threshold": coverage_threshold,
        "min_spline": coverage.min_spline,
        "max_spline": coverage.max_spline,
        "max_spline_gap": max_spline_gap,
        "observed_max_spline_gap": coverage.max_gap,
        "samples": coverage.samples,
        "format": TT_REFERENCE_IMPORT_FORMAT,
    }
    return record
