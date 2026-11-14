"""Synthetic capture inputs for the #988 human-control attestation tests.

Everything here is fabricated test data. No real lap, session or vendor record is
represented, and nothing built here is evidence about a real driver.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from tools.human_control_attestation import Attestation, attest_lap
from tools.lap_qualification import HUMAN_ATTESTATION_SECTIONS, _utc_ms

UNITS = {
    "spline": "normalized",
    "speed": "km/h",
    "eMs": "ms",
    "throttle": "ratio",
    "brake": "ratio",
    "steer": "steering_wheel_deg",
    "gear": "gear",
    "px": "m",
    "py": "m",
    "pz": "m",
}
EXPORTED_AT = "2026-11-14T12:00:00Z"
EXPORTED_MS = _utc_ms(EXPORTED_AT)
LAP_MS = 60_000
LAP_START = EXPORTED_MS - LAP_MS
LAP_END = EXPORTED_MS + 1000
DECLARED_MS = LAP_START - 30_000
CAPTURE_START = DECLARED_MS - 1000
CAPTURE_END = LAP_END + 8000
VENDOR_READ_MS = LAP_END + 3000


def native_record() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": "synthetic-lap",
        "session_uuid": "synthetic-session",
        "exported_at": EXPORTED_AT,
        "car": {"id": "synthetic-car"},
        "track": {"id": "synthetic-track", "layout": None},
        "lap": {"lap_n": 2, "lap_ms": LAP_MS, "is_valid": True, "is_pb": True},
        "trace": {
            "fields": list(UNITS),
            "samples": [[i / 100, 100, i * 600, 0.7, 0.1, 5, 3, i, 0, i] for i in range(101)],
            "control_observation": {
                "schema_version": 1,
                "source": "car.isAIControlled",
                "complete": True,
                "sample_count": 6000,
                "unknown_count": 0,
                "ai_controlled_count": 0,
                "user_controlled_count": 6000,
                "not_live_count": 0,
                "wall_elapsed_s": LAP_MS // 1000,
            },
        },
    }


def probe(t_ms: int, *, state: str = "absent", reference: str = "present") -> dict[str, Any]:
    return {
        "kind": "probe",
        "t_ms": t_ms,
        "sections": dict.fromkeys(HUMAN_ATTESTATION_SECTIONS, state),
        "reference": reference,
    }


def probes(start: int = CAPTURE_START, end: int = CAPTURE_END, step: int = 100) -> list[dict]:
    return [probe(t) for t in range(start, end + 1, step)]


def vendor_payload(**lap_changes: Any) -> dict[str, Any]:
    key = "AC|synthetic-track|synthetic-car|0|AC|synthetic-track"
    lap = {
        "id": "synthetic-vendor-lap",
        "recordUid": "synthetic-vendor-lap",
        "sessionId": "synthetic-vendor-session",
        "lapNumber": 2,
        "lapTimeSeconds": LAP_MS / 1000,
        "complete": True,
        "finalized": True,
        "isValidLap": True,
        "aiIntervened": False,
        "eligibility": "eligible",
        "referenceKey": key,
    }
    lap.update(lap_changes)
    return {
        "schemaVersion": 1,
        "sessionId": "synthetic-vendor-session",
        "sessionStartedAtMs": LAP_START - 60_000,
        "savedAtMs": LAP_END + 2000,
        "summary": {
            "observedLapCount": 1,
            "completeLapCount": 1,
            "evaluatedLapCount": 1,
            "referenceKey": key,
            "laps": [lap],
        },
    }


def encode(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def journal(events: list[dict[str, Any]]) -> bytes:
    ordered = sorted(events, key=lambda event: event["t_ms"])
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in ordered).encode("utf-8")


def declaration(t_ms: int = DECLARED_MS, action: str = "human_control.declare") -> dict[str, Any]:
    return {"kind": "declaration", "t_ms": t_ms, "surface": "rig_controls", "action": action}


def capture_inputs(
    *,
    probe_events: list[dict[str, Any]] | None = None,
    vendor: dict[str, Any] | None = None,
    vendor_read_ms: int = VENDOR_READ_MS,
    declarations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keyword arguments for ``attest_lap`` describing one clean human capture."""
    raw_vendor = encode(vendor_payload() if vendor is None else vendor)
    digest = hashlib.sha256(raw_vendor).hexdigest()
    events = list(probes() if probe_events is None else probe_events)
    events.append({"kind": "vendor_snapshot", "t_ms": vendor_read_ms, "sha256": digest})
    return {
        "capture_journal": journal(events),
        "declaration_journal": journal([declaration()] if declarations is None else declarations),
        "vendor": {digest: raw_vendor},
    }


def attest(record: dict[str, Any] | None = None, **inputs: Any) -> Attestation:
    record = native_record() if record is None else record
    raw = json.dumps(record).encode("utf-8")
    arguments = capture_inputs()
    arguments.update(inputs)
    return attest_lap(record, source_sha256=hashlib.sha256(raw).hexdigest(), **arguments)


def certified_envelope(record: dict[str, Any]) -> dict[str, Any]:
    """A real producer envelope for ``record`` as serialized by ``json.dumps``."""
    result = attest(record)
    assert result.verified, result.reasons
    return copy.deepcopy(result.qualification)
