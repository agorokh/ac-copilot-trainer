"""Archive-bound qualification and append-only control attribution (#815).

This is a boundary policy, never a telemetry-tick operation. A missing default
ledger preserves legacy behavior without certifying a human driver. An explicitly
configured unavailable ledger fails closed. Evidence can restrict an immutable
native archive; registration cannot certify human control or promote it live.
The explicit #529 native-control witness may permit plant fitting only.
Prospective operator attestations authorize only explicit live practice context;
they never become verified-human, PB or general reference evidence.
The default-off #988 capture-time attestation is the sole verified-human writer:
it needs every process-level signal positively read and bound to the payload hash,
and it never relabels a lap that already has a ledger entry, including an
operator-attested practice lap. The one replacement the ledger allows is
revocation: a restrictive fact supersedes a #988 human attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from tools.ai_sidecar.traffic_eligibility import CLEAN_USES, archive_traffic_eligibility
from tools.lap_trace_validity import completed_trace_reason, finish_wrap_cut

SCHEMA_VERSION = 1
ATTRIBUTIONS_ENV = "AC_COPILOT_LAP_ATTRIBUTIONS"
USES = frozenset(
    {
        "analysis",
        "map",
        "live_reference",
        "reference_comparison",
        "human_progression",
        "plant_fit",
        "practice_reference",
        "practice_trial",
    }
)
SCOPED_USES = frozenset({"practice_reference", "practice_trial"})
AUTHORITIES = frozenset({"human", "attested_human", "ai", "shared", "unknown"})
PRACTICE_ORIGIN = "operator_attested_human_control_v1"
# Native archive acceleration channels use G; importing a channel still requires
# bound measured-unit evidence and does not inherit eligibility from this constant.
NATIVE_ACCELERATION_UNIT = "G"
NATIVE_HARNESS_ORIGIN = "ac_harness_native_control_v1"
# Capture-time human-control attestation (#988). Default off: unset means no producer
# output is written and no attested envelope is honoured for a human-only use.
HUMAN_ATTESTATION_ORIGIN = "human_control_attestation_v1"
HUMAN_ATTESTATION_ENV = "AC_COPILOT_HUMAN_CONTROL_ATTESTATION"
HUMAN_ATTESTATION_USES = frozenset({"analysis", "human_progression"})
# The project autonomous driver's CSP Custom-AI sections for the player car. Both the
# bare and the explicit session-local name are probed; tests pin them to custom_ai.py.
HUMAN_ATTESTATION_SECTIONS = (
    "AcTools.CSP.NewBehaviour.CustomAI.Car0.v0",
    "AcTools.CSP.NewBehaviour.CustomAI.CarControls0.v0",
    "Local\\AcTools.CSP.NewBehaviour.CustomAI.Car0.v0",
    "Local\\AcTools.CSP.NewBehaviour.CustomAI.CarControls0.v0",
)
# Positive control: AC's own section must open through the same opener, otherwise an
# "absent" answer may only mean the probe ran in another Windows session namespace.
HUMAN_ATTESTATION_REFERENCE_SECTION = "acpmf_physics"
HUMAN_ATTESTATION_MAX_PROBE_GAP_MS = 500
HUMAN_ATTESTATION_WINDOW_MARGIN_MS = 5000
HUMAN_ATTESTATION_DECLARATION_TTL_MS = 20 * 60 * 1000
HUMAN_ATTESTATION_VENDOR_LAP_TOLERANCE_MS = 1
HUMAN_ATTESTATION_NATIVE_SOURCE = "car.isAIControlled"
HUMAN_ATTESTATION_DECLARE_ACTION = "human_control.declare"
# AC lap time excludes paused time; wall-clock elapsed (1 s resolution at both ends)
# must agree with it or the capture window no longer brackets the lap.
HUMAN_ATTESTATION_WALL_CLOCK_TOLERANCE_MS = 2500
HUMAN_ATTESTATION_MIN_FRAME_HZ = 10
HUMAN_ATTESTATION_VENDOR_ELIGIBILITY = "eligible"
_EXPORTED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_IMPORT_FORMATS = frozenset({"motec_csv", "track_titan_reference_v1", "moza_tracecore_view_v1"})
_CONTEXT_USES = frozenset({"map", "live_reference", "reference_comparison"})
_UNITS = {
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


@dataclass(frozen=True)
class Qualification:
    allowed: bool
    reason: str
    reasons: tuple[str, ...]
    managed: bool
    authority: str


class AttributionError(ValueError):
    """An attribution could not be established without ambiguity."""


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def archive_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    lap, car, track = _map(record.get("lap")), _map(record.get("car")), _map(record.get("track"))
    return {
        "session_uuid": record.get("session_uuid"),
        "lap_uuid": record.get("lap_uuid"),
        "lap_n": lap.get("lap_n"),
        "lap_ms": lap.get("lap_ms"),
        "car_id": car.get("id"),
        "track_id": track.get("id"),
        "layout": track.get("layout"),
    }


def archive_combo(record: Mapping[str, Any]) -> tuple[str, str, str | None] | None:
    """Exact combo, including CSP's explicitly unavailable layout and ID suffixes."""
    car, track = _map(record.get("car")), _map(record.get("track"))
    car_id, track_id, layout = car.get("id"), track.get("id"), track.get("layout")
    if not isinstance(car_id, str) or not car_id or not isinstance(track_id, str) or not track_id:
        return None
    if (
        track.get("identity_source") == "csp_content_ids"
        and track.get("layout_available") is not True
    ):
        return None
    if layout is not None and not isinstance(layout, str):
        return None
    if "/" in track_id:
        track_id, suffix = track_id.split("/", 1)
        if not track_id or not suffix or (layout and layout != suffix):
            return None
        layout = suffix
    return car_id, track_id, layout or None


def payload_sha256(record: Mapping[str, Any]) -> str:
    """Bind values (including source/PB flags), excluding only our attached envelope."""
    payload = {key: value for key, value in record.items() if key != "qualification"}
    try:
        data = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise AttributionError("nonfinite_or_unserializable_payload") from exc
    return hashlib.sha256(data).hexdigest()


def build_qualification(
    record: Mapping[str, Any],
    *,
    authority: str,
    origin: str,
    supported_uses: Mapping[str, bool],
    channels: Mapping[str, Any] | None = None,
    reasons: Sequence[str] = (),
    evidence: Sequence[Mapping[str, Any]] = (),
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an explicit assessment; callers cannot gain eligibility from flags alone."""
    if authority not in AUTHORITIES:
        raise AttributionError("unknown_control_authority")
    if set(supported_uses) - USES or any(type(v) is not bool for v in supported_uses.values()):
        raise AttributionError("invalid_supported_uses")
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": authority,
        "origin": origin,
        "supported_uses": dict(supported_uses),
        "channels": dict(channels or {}),
        "reasons": list(reasons),
        "conditions": dict(conditions or {}),
        "evidence": [dict(item) for item in evidence],
        "binding": {"payload_sha256": payload_sha256(record), **archive_identity(record)},
    }


def default_attribution_path() -> Path:
    """One store, following the same Documents/OneDrive order as the AC harness."""
    override = os.environ.get(ATTRIBUTIONS_ENV)
    if override is not None:
        if not override.strip():
            raise AttributionError("attribution_store_unavailable")
        return Path(override).expanduser()
    laps_override = os.environ.get("AC_COPILOT_LAP_ARCHIVE_DIR")
    if laps_override:
        return Path(laps_override).expanduser().parent / "lap-attributions.json"
    csp_override = os.environ.get("AC_COPILOT_CSP_STATE_DIR")
    if csp_override:
        return (
            Path(csp_override).expanduser()
            / "ac_copilot_trainer"
            / "journal"
            / "lap-attributions.json"
        )
    explicit = os.environ.get("AC_COPILOT_AC_USER_DIR")
    if explicit:
        root = Path(explicit).expanduser()
    else:
        candidates = (
            Path.home() / "Documents" / "Assetto Corsa",
            Path.home() / "OneDrive" / "Documents" / "Assetto Corsa",
        )
        root = next((path for path in candidates if path.is_dir()), candidates[0])
    if os.name != "nt" and not explicit:
        return Path.cwd() / "journal" / "lap-attributions.json"
    return (
        root
        / "cfg"
        / "extension"
        / "state"
        / "lua"
        / "app"
        / "AC_Copilot_Trainer"
        / "ac_copilot_trainer"
        / "journal"
        / "lap-attributions.json"
    )


def _stable_bytes(path: Path) -> bytes:
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    # Re-read catches replacement with unchanged metadata; this is per-file stability only.
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AttributionError("input_changed_during_read")
    if len(data) != after.st_size or data != path.read_bytes():
        raise AttributionError("input_changed_during_read")
    return data


def _read_ledger(path: Path, *, required: bool) -> list[dict[str, Any]]:
    try:
        raw = _stable_bytes(path)
    except FileNotFoundError as exc:
        if not required:
            return []
        raise AttributionError("attribution_store_unavailable") from exc
    except OSError as exc:
        raise AttributionError("attribution_store_unavailable") from exc
    try:
        ledger = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AttributionError("attribution_store_invalid") from exc
    if not isinstance(ledger, dict) or type(ledger.get("schema_version")) is not int:
        raise AttributionError("attribution_store_invalid")
    if ledger["schema_version"] != SCHEMA_VERSION:
        raise AttributionError("attribution_schema_unsupported")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise AttributionError("attribution_store_invalid")
    return _validate_entries(entries)


def _validate_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the identical ledger contract before both reading and publication."""
    for entry in entries:
        if not isinstance(entry.get("identity"), dict) or not isinstance(
            entry.get("qualification"), dict
        ):
            raise AttributionError("attribution_store_invalid")
        if not _is_hash(entry.get("source_sha256")) or not _is_hash(entry.get("payload_sha256")):
            raise AttributionError("attribution_store_invalid")
        identity, envelope = entry["identity"], entry["qualification"]
        if _identity_reasons(identity):
            raise AttributionError("attribution_store_invalid")
        binding = _map(envelope.get("binding"))
        if any(key not in binding or binding[key] != value for key, value in identity.items()):
            raise AttributionError("attribution_store_invalid")
        if binding.get("payload_sha256") != entry["payload_sha256"]:
            raise AttributionError("attribution_store_invalid")
        if type(envelope.get("schema_version")) is not int or envelope.get("schema_version") != 1:
            raise AttributionError("attribution_store_invalid")
        authority = envelope.get("authority")
        if authority == "attested_human":
            if not _practice_attribution_evidence(
                envelope,
                identity=identity,
                payload_digest=entry["payload_sha256"],
                source_digest=entry["source_sha256"],
            ):
                raise AttributionError("attribution_store_invalid")
            continue
        # Human authority exists in the ledger only as a full #988 attestation; its
        # structure is checked regardless of the opt-in so disabling never corrupts
        # the store. Eligibility is still decided at the qualification boundary.
        attested = authority == "human" and human_control_attestation_evidence(
            envelope,
            identity=identity,
            payload_digest=entry["payload_sha256"],
            source_digest=entry["source_sha256"],
        )
        if not isinstance(authority, str) or (
            authority not in {"ai", "shared", "unknown"} and not attested
        ):
            raise AttributionError("attribution_store_invalid")
        uses = envelope.get("supported_uses")
        if (
            not isinstance(uses, dict)
            or set(uses) - USES
            or any(type(v) is not bool for v in uses.values())
            or any(
                v
                for key, v in uses.items()
                if key not in {"analysis", "plant_fit"}
                and not (attested and key in HUMAN_ATTESTATION_USES)
            )
            or (
                uses.get("plant_fit") is True
                and not native_harness_fit_evidence(
                    envelope,
                    identity=identity,
                    payload_digest=entry["payload_sha256"],
                    source_digest=entry["source_sha256"],
                )
            )
        ):
            raise AttributionError("attribution_store_invalid")
        evidence = envelope.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("kind"), str)
                or not item["kind"].strip()
                or not _is_hash(item.get("sha256"))
                for item in evidence
            )
        ):
            raise AttributionError("attribution_store_invalid")
    return entries


def _is_hash(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _practice_attribution_evidence(
    envelope: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    payload_digest: str,
    source_digest: str,
) -> bool:
    uses = envelope.get("supported_uses")
    evidence = envelope.get("evidence")
    if (
        envelope.get("authority") != "attested_human"
        or envelope.get("origin") != PRACTICE_ORIGIN
        or not isinstance(uses, dict)
        or set(uses) - USES
        or any(type(value) is not bool for value in uses.values())
        or any(value for use, value in uses.items() if use not in SCOPED_USES | {"analysis"})
        or not all(uses.get(use) is True for use in SCOPED_USES)
        or not isinstance(evidence, list)
        or len(evidence) != 1
    ):
        return False
    item = evidence[0]
    if not isinstance(item, Mapping) or item.get("kind") != "operator_attested_human_control":
        return False
    witness = item.get("witness")
    if not isinstance(witness, Mapping):
        return False
    try:
        digest = hashlib.sha256(
            json.dumps(witness, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()
    except (ValueError, TypeError):
        return False
    return (
        item.get("sha256") == digest
        and witness.get("identity") == dict(identity)
        and witness.get("payload_sha256") == payload_digest
        and witness.get("source_sha256") == source_digest
        and isinstance(witness.get("permit_id"), str)
        and bool(witness["permit_id"])
        and _is_hash(witness.get("declaration_sha256"))
        and _is_hash(witness.get("native_window_sha256"))
        and type(witness.get("reference_eligible")) is bool
    )


def native_harness_fit_evidence(
    envelope: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    payload_digest: str,
    source_digest: str | None = None,
) -> bool:
    """The sole AI plant-fit exception: an exact, clean native-control witness.

    This never grants a human/reference use or broadens an older ledger entry.
    The producer's witness is embedded so downstream readers verify its hash and
    identity without depending on a mutable report or another state store.
    """
    uses = _map(envelope.get("supported_uses"))
    if (
        envelope.get("authority") != "ai"
        or envelope.get("origin") != NATIVE_HARNESS_ORIGIN
        or set(uses) - USES
        or any(type(value) is not bool for value in uses.values())
        or uses.get("plant_fit") is not True
        or any(value is True for key, value in uses.items() if key not in {"analysis", "plant_fit"})
    ):
        return False
    evidence = envelope.get("evidence")
    if not isinstance(evidence, list):
        return False
    for item in evidence:
        if not isinstance(item, Mapping) or item.get("kind") != "native_harness_plant_fit":
            continue
        witness = _map(item.get("witness"))
        try:
            encoded = json.dumps(
                witness, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (ValueError, TypeError):
            continue
        if item.get("sha256") != hashlib.sha256(encoded).hexdigest():
            continue
        app = _map(witness.get("app_install"))
        report = _map(witness.get("report"))
        if (
            type(witness.get("schema_version")) is not int
            or witness.get("schema_version") != 1
            or witness.get("driver") not in {"handshake", "alien", "ggv"}
            or witness.get("clean_run") is not True
            or not native_harness_report_clean(report, driver=witness.get("driver"))
            or witness.get("session_uuid") != identity.get("session_uuid")
            or report.get("session_uuid") != identity.get("session_uuid")
            or report.get("car_id") != identity.get("car_id")
            or report.get("track_id") != identity.get("track_id")
            or app.get("status") != "match"
            or not _is_hash(app.get("harness_digest"))
            or app.get("installed_digest") != app.get("harness_digest")
        ):
            continue
        archives = witness.get("archives")
        timed = witness.get("timed_laps")
        if not isinstance(archives, list) or not archives or not isinstance(timed, list):
            continue
        if any(
            not isinstance(row, dict)
            or type(row.get("lap_n")) is not int
            or type(row.get("lap_ms")) is not int
            or row["lap_n"] <= 0
            or row["lap_ms"] <= 0
            for row in timed
        ):
            continue
        observed = [_map(_map(row).get("identity")) for row in archives]
        if any(
            _identity_reasons(row) or row.get("session_uuid") != witness["session_uuid"]
            for row in observed
        ):
            continue
        if len({row["lap_n"] for row in observed}) != len(observed) or len(
            {row["lap_uuid"] for row in observed}
        ) != len(observed):
            continue
        if sorted((row["lap_n"], row["lap_ms"]) for row in observed) != sorted(
            (row["lap_n"], row["lap_ms"]) for row in timed
        ):
            continue
        selected = [row for row in archives if _map(row).get("identity") == dict(identity)]
        if len(selected) != 1:
            continue
        selected = selected[0]
        if (
            selected.get("source") == "in_game"
            and selected.get("import_format") is None
            and selected.get("payload_sha256") == payload_digest
            and _is_hash(selected.get("source_sha256"))
            and (source_digest is None or selected["source_sha256"] == source_digest)
        ):
            return True
    return False


def native_harness_report_clean(report: Mapping[str, Any], *, driver: str) -> bool:
    """Recheck explicit run facts rather than trusting a stored clean-run flag."""
    drive = _map(report.get("drive"))
    clean = (
        report.get("ok") is True
        and drive.get("drove") is True
        and drive.get("sim_dead") is False
        and drive.get("session_replaced") is False
        and type(drive.get("recoveries")) is int
        and drive["recoveries"] == 0
        and drive.get("recovery_capped") is False
        and isinstance(drive.get("unexpected_sim_pids"), list)
        and not drive["unexpected_sim_pids"]
    )
    return clean and (driver != "handshake" or _map(drive.get("payload")).get("ok") is True)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def human_attestation_enabled() -> bool:
    """Default off; only the exact value ``1`` opts in (#988)."""
    return os.environ.get(HUMAN_ATTESTATION_ENV) == "1"


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _utc_ms(value: Any) -> int | None:
    """Parse the archive writer's second-resolution ``exported_at`` only."""
    if not isinstance(value, str) or not _EXPORTED_AT.fullmatch(value):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return int(parsed.timestamp()) * 1000


def human_witness_reasons(
    witness: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    payload_digest: str,
    source_digest: str | None = None,
    record: Mapping[str, Any] | None = None,
) -> list[str]:
    """Every reason a capture-time witness cannot certify human control (#988).

    Empty means certified. This is the single decision used by both the producer
    and every later reader, and it rechecks recorded facts instead of a stored
    verdict. A signal that is missing, unread, stale or ambiguous is a reason; an
    unreadable probe is never treated as "controller not present".
    """
    if not isinstance(witness, Mapping):
        return ["attestation_witness_missing"]
    if type(witness.get("schema_version")) is not int or witness.get("schema_version") != 1:
        return ["attestation_schema_unsupported"]
    reasons: list[str] = []
    if witness.get("producer") != HUMAN_ATTESTATION_ORIGIN:
        reasons.append("attestation_producer_mismatch")
    archive = _map(witness.get("archive"))
    if _identity_reasons(identity) or archive.get("identity") != dict(identity):
        reasons.append("attestation_identity_mismatch")
    if archive.get("source") != "in_game" or archive.get("import_format") is not None:
        reasons.append("attestation_source_unsupported")
    if not _is_hash(payload_digest) or archive.get("payload_sha256") != payload_digest:
        reasons.append("attestation_payload_mismatch")
    if not _is_hash(archive.get("source_sha256")) or (
        source_digest is not None and archive.get("source_sha256") != source_digest
    ):
        reasons.append("attestation_source_hash_mismatch")
    exported_ms = _utc_ms(archive.get("exported_at"))
    lap_ms = identity.get("lap_ms")
    window = _map(witness.get("window"))
    start_ms, end_ms = window.get("start_ms"), window.get("end_ms")
    if exported_ms is None or type(lap_ms) is not int or lap_ms <= 0:
        return [*reasons, "attestation_lap_window_unavailable"]
    # exported_at is truncated to the second and written at the finish boundary.
    lap_start, lap_end = exported_ms - lap_ms, exported_ms + 1000
    if (
        (record is not None and record.get("exported_at") != archive.get("exported_at"))
        or type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms > lap_start - HUMAN_ATTESTATION_WINDOW_MARGIN_MS
        or end_ms < lap_end + HUMAN_ATTESTATION_WINDOW_MARGIN_MS
    ):
        return [*reasons, "attestation_lap_window_mismatch"]

    # Operator declaration: necessary, never sufficient. It must precede the lap,
    # still be fresh at its end and not have been cleared in between.
    declaration = _map(witness.get("declaration"))
    declared_ms = declaration.get("declared_ms")
    coverage_start = start_ms
    if (
        declaration.get("surface") != "rig_controls"
        or declaration.get("action") != HUMAN_ATTESTATION_DECLARE_ACTION
        or not _is_hash(declaration.get("journal_sha256"))
        or type(declared_ms) is not int
        or not _count(declaration.get("cleared_count"))
    ):
        reasons.append("declaration_missing")
    else:
        coverage_start = min(start_ms, declared_ms)
        if declared_ms > lap_start:
            reasons.append("declaration_after_lap_start")
        if lap_end - declared_ms > HUMAN_ATTESTATION_DECLARATION_TTL_MS:
            reasons.append("declaration_stale")
        if declaration["cleared_count"]:
            reasons.append("declaration_cleared")

    # Project autonomous driver: the control map must be read absent continuously
    # from the declaration through the lap, with the positive control readable.
    control = _map(witness.get("control_map"))
    counts = [
        control.get(key)
        for key in (
            "sample_count",
            "present_count",
            "error_count",
            "reference_unavailable_count",
            "max_gap_ms",
        )
    ]
    if (
        control.get("sections") != list(HUMAN_ATTESTATION_SECTIONS)
        or control.get("reference_section") != HUMAN_ATTESTATION_REFERENCE_SECTION
        or not _is_hash(control.get("journal_sha256"))
        or any(not _count(value) for value in counts)
        or type(control.get("first_ms")) is not int
        or type(control.get("last_ms")) is not int
    ):
        reasons.append("control_map_probe_missing")
    else:
        if control["present_count"]:
            reasons.append("control_map_present")
        if control["error_count"]:
            reasons.append("control_map_probe_error")
        if control["reference_unavailable_count"]:
            reasons.append("control_map_reference_unavailable")
        if (
            control["sample_count"] < 2
            or control["first_ms"] > coverage_start
            or control["last_ms"] < end_ms
            or control["max_gap_ms"] > HUMAN_ATTESTATION_MAX_PROBE_GAP_MS
            # The recorded span cannot exceed what that many samples can bridge.
            or control["max_gap_ms"] * (control["sample_count"] - 1)
            < control["last_ms"] - control["first_ms"]
        ):
            reasons.append("control_map_probe_gap")

    # Native game AI, pause and replay: CSP's per-frame state, summarized before trace
    # downsampling inside the hash-bound archive itself, plus wall-clock elapsed time.
    native = _map(witness.get("native_ai"))
    native_counts = [
        native.get(key)
        for key in (
            "sample_count",
            "unknown_count",
            "ai_controlled_count",
            "user_controlled_count",
            "not_live_count",
            "wall_elapsed_s",
        )
    ]
    if (
        type(native.get("schema_version")) is not int
        or native.get("schema_version") != 1
        or native.get("source") != HUMAN_ATTESTATION_NATIVE_SOURCE
        or type(native.get("complete")) is not bool
        or any(not _count(value) for value in native_counts)
    ):
        reasons.append("native_ai_observation_missing")
    else:
        if record is not None and _map(record.get("trace")).get("control_observation") != dict(
            native
        ):
            reasons.append("native_ai_observation_mismatch")
        if native["complete"] is not True:
            reasons.append("native_ai_observation_incomplete")
        if native["sample_count"] * 1000 < lap_ms * HUMAN_ATTESTATION_MIN_FRAME_HZ:
            reasons.append("native_ai_observation_sparse")
        if native["unknown_count"]:
            reasons.append("native_ai_state_unknown")
        if native["ai_controlled_count"]:
            reasons.append("native_ai_controlled")
        if native["user_controlled_count"] != native["sample_count"]:
            reasons.append("native_user_control_absent")
        if native["not_live_count"]:
            reasons.append("native_lap_not_live")
        if (
            abs(native["wall_elapsed_s"] * 1000 - lap_ms)
            > HUMAN_ATTESTATION_WALL_CLOCK_TOLERANCE_MS
        ):
            reasons.append("native_lap_wall_clock_mismatch")

    # Vendor AI driving: only the vendor's own practice record labels it, and it
    # shares no session identifier, so the join is session window + combo + lap
    # number + duration, decided from the latest read of a record saved after the
    # finish. A record saved earlier cannot contain this lap.
    vendor = _map(witness.get("vendor_practice"))
    vendor_times = [vendor.get(key) for key in ("read_ms", "session_started_ms", "saved_ms")]
    if not _is_hash(vendor.get("record_sha256")) or any(type(v) is not int for v in vendor_times):
        reasons.append("vendor_record_missing")
    else:
        if vendor["read_ms"] < lap_end:
            reasons.append("vendor_record_stale")
        # Saved no earlier than the latest possible finish, so it can hold this lap.
        if vendor["session_started_ms"] > lap_start + 1000 or vendor["saved_ms"] < lap_end:
            reasons.append("vendor_record_not_covering_lap")
        if (
            not _count(vendor.get("covering_reads"))
            or vendor["covering_reads"] < 1
            or not _count(vendor.get("disagreeing_reads"))
            or vendor["disagreeing_reads"]
        ):
            reasons.append("vendor_join_ambiguous")
        key = vendor.get("reference_key")
        parts = key.split("|") if isinstance(key, str) else []
        track = identity.get("track_id")
        track = track.split("/", 1)[0] if isinstance(track, str) else None
        if len(parts) < 3 or parts[0] != "AC" or not parts[1] or not parts[2]:
            reasons.append("vendor_combo_unreadable")
        elif parts[1] != track or parts[2] != identity.get("car_id"):
            reasons.append("vendor_combo_mismatch")
        matched = vendor.get("matched_laps")
        lap = _map(vendor.get("lap"))
        if not _count(matched) or matched == 0:
            reasons.append("vendor_lap_unmatched")
        elif matched > 1:
            reasons.append("vendor_join_ambiguous")
        elif (
            type(lap.get("lap_time_ms")) is not int
            or abs(lap["lap_time_ms"] - lap_ms) > HUMAN_ATTESTATION_VENDOR_LAP_TOLERANCE_MS
            or type(lap.get("lap_number")) is not int
            or lap["lap_number"] != identity.get("lap_n")
        ):
            reasons.append("vendor_lap_unmatched")
        else:
            if lap.get("ai_intervened") is True or lap.get("eligibility") == "ai-debug-only":
                reasons.append("vendor_ai_intervened")
            elif lap.get("ai_intervened") is not False:
                reasons.append("vendor_ai_label_unreadable")
            elif lap.get("eligibility") != HUMAN_ATTESTATION_VENDOR_ELIGIBILITY:
                reasons.append("vendor_lap_not_eligible")
            if lap.get("complete") is not True or lap.get("finalized") is not True:
                reasons.append("vendor_lap_incomplete")
    return list(dict.fromkeys(reasons))


def human_control_attestation_evidence(
    envelope: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    payload_digest: str,
    source_digest: str | None = None,
    record: Mapping[str, Any] | None = None,
) -> bool:
    """The sole persisted human-authority path: one exact capture-time witness (#988).

    Grants human progression and analysis only. The embedded witness is hashed and
    rechecked here, so a reader never depends on a mutable capture directory.
    """
    uses = _map(envelope.get("supported_uses"))
    if (
        envelope.get("authority") != "human"
        or envelope.get("origin") != HUMAN_ATTESTATION_ORIGIN
        or set(uses) - USES
        or any(type(value) is not bool for value in uses.values())
        or any(value for key, value in uses.items() if key not in HUMAN_ATTESTATION_USES)
    ):
        return False
    evidence = envelope.get("evidence")
    if not isinstance(evidence, list):
        return False
    items = [
        item
        for item in evidence
        if isinstance(item, Mapping) and item.get("kind") == "verified_human_control"
    ]
    if len(items) != 1:
        return False
    witness = _map(items[0].get("witness"))
    try:
        encoded = json.dumps(
            witness, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError):
        return False
    return items[0].get("sha256") == hashlib.sha256(encoded).hexdigest() and not (
        human_witness_reasons(
            witness,
            identity=identity,
            payload_digest=payload_digest,
            source_digest=source_digest,
            record=record,
        )
    )


def _same_selected_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return bool(
        (left.get("lap_uuid") and left.get("lap_uuid") == right.get("lap_uuid"))
        or (
            left.get("session_uuid")
            and left.get("session_uuid") == right.get("session_uuid")
            and left.get("lap_n") is not None
            and left.get("lap_n") == right.get("lap_n")
        )
    )


def _binding_reason(
    record: Mapping[str, Any], envelope: Mapping[str, Any], *, digest: str | None = None
) -> str | None:
    if type(envelope.get("schema_version")) is not int or envelope.get("schema_version") != 1:
        return "qualification_schema_unsupported"
    binding = _map(envelope.get("binding"))
    if any(
        key not in binding or binding[key] != value
        for key, value in archive_identity(record).items()
    ):
        return "qualification_identity_mismatch"
    try:
        if digest is None:
            digest = payload_sha256(record)
    except AttributionError as exc:
        return str(exc)
    if binding.get("payload_sha256") != digest:
        return "qualification_payload_mismatch"
    return None


def resolve_archive_provenance(
    record: Mapping[str, Any],
    *,
    source_path: str | Path | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Overlay restrictive ledger facts in memory, never alter an archive on disk.

    A direct dict is bound by canonical values and full identity. A path loader also
    verifies original bytes. The ledger wins over permissive embedded assessments.
    Errors are carried to policy as a deny envelope, so callers cannot fall back to
    a permissive raw record after an attribution read error.
    """
    return _resolve_archive_provenance(
        record, source_path=source_path, source_sha256=source_sha256
    )[0]


def _resolve_archive_provenance(
    record: Mapping[str, Any],
    *,
    source_path: str | Path | None = None,
    source_sha256: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Return the digest actually checked in this call, never a caller-supplied claim."""
    result = dict(record)
    digest = None
    # A byte-hash failure from a path reader cannot disappear on the subsequent
    # direct-dict boundary, where those original bytes are no longer available.
    if _map(record.get("qualification")).get("resolution_error"):
        return result, digest
    try:
        entries = _read_ledger(default_attribution_path(), required=ATTRIBUTIONS_ENV in os.environ)
        identity = archive_identity(record)
        selected = [item for item in entries if _same_selected_identity(item["identity"], identity)]
        if len(selected) > 1:
            raise AttributionError("duplicate_attribution_identity")
        if not selected:
            return result, digest
        entry = selected[0]
        if entry["identity"] != identity:
            raise AttributionError("attribution_identity_mismatch")
        digest = payload_sha256(record)
        if entry["payload_sha256"] != digest:
            raise AttributionError("attribution_payload_mismatch")
        if source_sha256 is None and source_path is not None:
            source_sha256 = hashlib.sha256(_stable_bytes(Path(source_path))).hexdigest()
        if source_sha256 is not None and entry["source_sha256"] != source_sha256:
            raise AttributionError("attribution_source_hash_mismatch")
        envelope = entry["qualification"]
        reason = _binding_reason(record, envelope, digest=digest)
        if reason:
            raise AttributionError(reason)
        result["qualification"] = dict(envelope)
    except (AttributionError, OSError) as exc:
        result["qualification"] = {"schema_version": 1, "resolution_error": str(exc)}
    return result, digest


def _decision(
    allowed: bool, reasons: Sequence[str], *, managed: bool, authority: str
) -> Qualification:
    unique = tuple(dict.fromkeys(reasons))
    return Qualification(allowed, unique[0] if unique else "eligible", unique, managed, authority)


def _finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _identity_reasons(identity: Mapping[str, Any]) -> list[str]:
    reasons = []
    if any(
        not isinstance(identity.get(key), str) or not identity[key].strip()
        for key in ("session_uuid", "lap_uuid", "car_id", "track_id")
    ):
        reasons.append("archive_identity_unavailable")
    if any(
        type(identity.get(key)) is not int or not _finite(identity[key]) or identity[key] <= 0
        for key in ("lap_n", "lap_ms")
    ):
        reasons.append("archive_lap_identity_invalid")
    if "layout" not in identity or (
        identity["layout"] is not None and not isinstance(identity["layout"], str)
    ):
        reasons.append("archive_layout_identity_invalid")
    return reasons


def _trace_reasons(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    trace = _map(record.get("trace"))
    fields, samples = trace.get("fields"), trace.get("samples")
    if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
        return ["trace_fields_invalid"]
    if len(fields) != len(set(fields)):
        return ["duplicate_trace_channel"]
    if not isinstance(samples, list) or len(samples) < 2:
        return ["insufficient_trace_samples"]
    if any(
        not isinstance(row, list) or len(row) != len(fields) or any(not _finite(v) for v in row)
        for row in samples
    ):
        return ["nonfinite_or_missing_trace_value"]
    required = set(_UNITS)
    channels = _map(envelope.get("channels"))
    for name in sorted(required):
        if name not in fields:
            reasons.append(f"missing_channel:{name}")
            continue
        metadata = _map(channels.get(name))
        if metadata.get("unit") != _UNITS[name]:
            reasons.append(f"unsupported_channel_unit:{name}")
        if metadata.get("basis") != "measured":
            reasons.append(f"unmeasured_channel:{name}")
    if not {"spline", "speed", "eMs"}.issubset(fields):
        return reasons
    s_idx, t_idx, v_idx = (fields.index(name) for name in ("spline", "eMs", "speed"))
    if any(row[t_idx] < 0 for row in samples):
        reasons.append("negative_elapsed_time")
    cut = finish_wrap_cut([row[s_idx] for row in samples], [row[t_idx] for row in samples])
    if cut is None:
        return [*reasons, "nonmonotonic_trace"]
    effective = samples[:cut]
    lap_ms = _map(record.get("lap")).get("lap_ms")
    completion = completed_trace_reason(
        [row[s_idx] for row in effective],
        [row[t_idx] for row in effective],
        [row[v_idx] for row in effective],
        lap_ms if _finite(lap_ms) else None,
    )
    if completion:
        reasons.append(completion)
    if any(b[t_idx] - a[t_idx] > 1000 for a, b in zip(effective, effective[1:], strict=False)):
        reasons.append("trace_time_gap")
    for name in ("brake", "throttle"):
        if name in fields and any(not 0 <= row[fields.index(name)] <= 1 for row in samples):
            reasons.append(f"trace_value_out_of_range:{name}")
    return reasons


def _attribution_revision() -> tuple[str | None, str | None]:
    """Change detector only; canonical resolution still decides eligibility/errors."""
    try:
        path = default_attribution_path()
    except AttributionError as exc:
        return None, str(exc)
    try:
        raw = _stable_bytes(path)
    except FileNotFoundError:
        return str(path), None
    except (AttributionError, OSError) as exc:
        return str(path), f"unavailable:{type(exc).__name__}"
    return str(path), hashlib.sha256(raw).hexdigest()


class ArchiveQualificationSnapshot:
    """Request-owned, unmodified record; no result survives a new archive load.

    Callers own this private record for the duration of analysis. Common byte/value
    binding and trace validation run once; use/combo decisions still run the same
    policy below. Assert current inputs before publishing a derived report. The
    ordinary qualify_archive API always makes a fresh snapshot.
    """

    def __init__(
        self,
        record: Mapping[str, Any],
        *,
        source_path: str | Path | None = None,
        source_sha256: str | None = None,
    ) -> None:
        self._record = record
        self._source_path = source_path
        self._source_sha256 = source_sha256
        self._ledger_revision: tuple[str | None, str | None] | None = None

    @cached_property
    def _provenance(self) -> tuple[dict[str, Any], str | None]:
        before = _attribution_revision()
        resolved, digest = _resolve_archive_provenance(
            self._record, source_path=self._source_path, source_sha256=self._source_sha256
        )
        self._ledger_revision = before
        if before != _attribution_revision():
            resolved["qualification"] = {
                "schema_version": 1,
                "resolution_error": "attribution_changed_during_analysis",
            }
        return resolved, digest

    @property
    def record(self) -> dict[str, Any]:
        """The resolved record owned by this analysis, including fail-closed errors."""
        return self._provenance[0]

    def assert_current(self) -> None:
        """Refuse publication if a ledger revocation or raw-file edit raced analysis."""
        _ = self.record
        if self._ledger_revision != _attribution_revision():
            raise AttributionError("attribution_changed_during_analysis")
        if self._source_path is not None and self._source_sha256 is not None:
            try:
                current = hashlib.sha256(_stable_bytes(Path(self._source_path))).hexdigest()
            except (AttributionError, OSError) as exc:
                raise AttributionError("archive_changed_during_analysis") from exc
            if current != self._source_sha256:
                raise AttributionError("archive_changed_during_analysis")

    @cached_property
    def _binding_error(self) -> str | None:
        resolved, digest = self._provenance
        return _binding_reason(resolved, _map(resolved.get("qualification")), digest=digest)

    @cached_property
    def _trace_errors(self) -> list[str]:
        resolved = self._provenance[0]
        return _trace_reasons(resolved, _map(resolved.get("qualification")))

    def qualify(
        self, *, use: str, expected_combo: tuple[str, str, str | None] | None = None
    ) -> Qualification:
        record = self._record
        if not isinstance(record, Mapping):
            return _decision(False, ["archive_root_invalid"], managed=True, authority="unknown")
        if use not in USES:
            return _decision(False, ["unsupported_use"], managed=True, authority="unknown")
        if "schema_version" in record and (
            type(record["schema_version"]) is not int or record["schema_version"] != 1
        ):
            return _decision(
                False, ["archive_schema_unsupported"], managed=True, authority="unknown"
            )
        if _map(_map(record.get("generator")).get("tt_reference")).get("partial") is True:
            return _decision(
                False, ["partial_tt_reference"], managed=False, authority="legacy_unknown"
            )
        resolved = self._provenance[0]
        envelope = resolved.get("qualification")
        managed = "qualification" in resolved or str(resolved.get("import_format", "")).startswith(
            "moza_"
        )
        source = record.get("source")
        if use in CLEAN_USES:
            traffic = archive_traffic_eligibility(record)
            if traffic is not None and not traffic.eligible:
                return _decision(
                    False,
                    [traffic.reason],
                    # An explicit traffic restriction is managed policy even
                    # without a control-attribution envelope. Existing consumers
                    # check this flag before enforcing a denied use.
                    managed=True,
                    authority=str(_map(envelope).get("authority") or "legacy_unknown"),
                )
        if (
            use == "human_progression"
            and isinstance(source, str)
            and source in {"imported", "reference", "reference_archive"}
        ):
            return _decision(
                False,
                [f"non_driver_source:{source}"],
                managed=managed,
                authority=str(_map(envelope).get("authority") or "legacy_unknown"),
            )
        if not managed:
            if use in SCOPED_USES:
                return _decision(
                    False, ["practice_context_required"], managed=True, authority="legacy_unknown"
                )
            return _decision(True, ["legacy_unknown"], managed=False, authority="legacy_unknown")
        if not isinstance(envelope, Mapping):
            return _decision(False, ["qualification_missing"], managed=True, authority="unknown")
        if envelope.get("resolution_error"):
            return _decision(
                False, [str(envelope["resolution_error"])], managed=True, authority="unknown"
            )
        authority = str(envelope.get("authority") or "unknown")
        reasons = []
        binding_error = self._binding_error
        if binding_error:
            reasons.append(binding_error)
        if authority not in AUTHORITIES:
            reasons.append("unknown_control_authority")
        native_fit = (
            use == "plant_fit"
            and authority == "ai"
            and envelope.get("origin") == NATIVE_HARNESS_ORIGIN
            and binding_error is None
            and source == "in_game"
            and record.get("import_format") is None
            and native_harness_fit_evidence(
                envelope,
                identity=archive_identity(record),
                payload_digest=self._provenance[1] or payload_sha256(record),
            )
        )
        if authority != "human" and use != "analysis" and not native_fit:
            reasons.append(f"control_authority_not_human:{authority}")
        evidence = envelope.get("evidence")
        if authority == "human" and not any(
            isinstance(item, Mapping)
            and item.get("kind") == "verified_human_control"
            and _is_hash(item.get("sha256"))
            for item in (evidence if isinstance(evidence, list) else [])
        ):
            reasons.append("human_control_evidence_missing")
        if envelope.get("origin") == HUMAN_ATTESTATION_ORIGIN:
            # The #988 producer's envelope is honoured only as a complete, exact
            # witness, and only while the operator keeps the producer enabled.
            if authority != "human" or (
                binding_error is None
                and not human_control_attestation_evidence(
                    envelope,
                    identity=archive_identity(record),
                    payload_digest=self._provenance[1] or payload_sha256(record),
                    record=record,
                )
            ):
                reasons.append("human_control_evidence_invalid")
            if use != "analysis" and not human_attestation_enabled():
                reasons.append("human_control_attestation_disabled")
        if type(record.get("schema_version")) is not int or record.get("schema_version") != 1:
            reasons.append("archive_schema_unsupported")
        if not isinstance(source, str) or source not in {"in_game", "imported"}:
            reasons.append("archive_source_unsupported")
        if source == "imported" and (
            not isinstance(record.get("import_format"), str)
            or record.get("import_format") not in _IMPORT_FORMATS
        ):
            reasons.append("import_format_unsupported")
        if source == "in_game" and record.get("import_format") is not None:
            reasons.append("native_import_format_conflict")
        identity = archive_identity(record)
        reasons.extend(_identity_reasons(identity))
        if _map(record.get("lap")).get("is_valid") is not True:
            reasons.append("lap_validity_unproved")
        lap = _map(record.get("lap"))
        if lap.get("complete") is False or lap.get("partial") is True:
            reasons.append("lap_incomplete")
        if _map(envelope.get("supported_uses")).get(use) is not True:
            reasons.append(f"unsupported_use:{use}")
        actual = archive_combo(record)
        if actual is None:
            reasons.append("combo_identity_unavailable")
        if use in _CONTEXT_USES and expected_combo is None:
            reasons.append("expected_combo_unavailable")
        if expected_combo is not None:
            expected = None
            if isinstance(expected_combo, (tuple, list)) and len(expected_combo) == 3:
                expected = archive_combo(
                    {
                        "car": {"id": expected_combo[0]},
                        "track": {"id": expected_combo[1], "layout": expected_combo[2]},
                    }
                )
            if actual != expected:
                reasons.append("combo_mismatch")
            elif expected is None:
                reasons.append("expected_combo_unavailable")
        reasons.extend(self._trace_errors)
        if use in SCOPED_USES:
            reasons.append("practice_context_required")
        return _decision(not reasons, reasons, managed=True, authority=authority)


def qualify_archive(
    record: Mapping[str, Any],
    *,
    use: str,
    expected_combo: tuple[str, str, str | None] | None = None,
) -> Qualification:
    """One policy, with fresh provenance checks on every ordinary boundary call."""
    return ArchiveQualificationSnapshot(record).qualify(use=use, expected_combo=expected_combo)


def is_practice_human(qualification: Qualification) -> bool:
    """An explicit scoped consumer may accept attestation without calling it verified."""
    return qualification.allowed and qualification.authority in {"human", "attested_human"}


def qualify_practice_archive(
    record: Mapping[str, Any],
    *,
    use: str,
    permit: Any,
    expected_combo: tuple[str, str, str | None],
) -> Qualification:
    from tools.human_session import HumanSessionError, HumanSessionPermit

    if use not in SCOPED_USES:
        return _decision(False, ["unsupported_practice_use"], managed=True, authority="unknown")
    if not isinstance(permit, HumanSessionPermit):
        return _decision(False, ["practice_context_required"], managed=True, authority="unknown")
    if not isinstance(record, Mapping):
        return _decision(False, ["archive_root_invalid"], managed=True, authority="unknown")
    snapshot = ArchiveQualificationSnapshot(record)
    resolved = snapshot.record
    envelope = _map(resolved.get("qualification"))
    authority = str(envelope.get("authority") or "unknown")
    reasons = []
    if envelope.get("resolution_error"):
        reasons.append(str(envelope["resolution_error"]))
    if authority != "attested_human":
        reasons.append(f"practice_attribution_required:{authority}")
    try:
        selected = [
            item
            for item in _read_ledger(default_attribution_path(), required=True)
            if _same_selected_identity(item["identity"], archive_identity(resolved))
        ]
        if len(selected) != 1 or selected[0]["qualification"] != envelope:
            reasons.append("canonical_practice_attribution_required")
    except AttributionError as exc:
        reasons.append(str(exc))
    if resolved.get("source") != "in_game" or resolved.get("import_format") is not None:
        reasons.append("native_archive_required")
    if type(resolved.get("schema_version")) is not int or resolved.get("schema_version") != 1:
        reasons.append("archive_schema_unsupported")
    try:
        context = permit.qualification_context(resolved, expected_combo=expected_combo)
        witness = (
            _map((_map(envelope.get("evidence", [{}])[0])).get("witness"))
            if isinstance(envelope.get("evidence"), list) and envelope["evidence"]
            else {}
        )
        if context != witness or not _practice_attribution_evidence(
            envelope,
            identity=archive_identity(resolved),
            payload_digest=payload_sha256(resolved),
            source_digest=context["source_sha256"],
        ):
            reasons.append("practice_witness_mismatch")
        if use == "practice_reference" and context.get("reference_eligible") is not True:
            reasons.append("practice_reference_window_closed")
    except (HumanSessionError, AttributionError, OSError, KeyError, TypeError, ValueError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, (HumanSessionError, AttributionError))
            else "practice_context_unavailable"
        )
    binding_error = snapshot._binding_error
    if binding_error:
        reasons.append(binding_error)
    reasons.extend(_identity_reasons(archive_identity(resolved)))
    reasons.extend(snapshot._trace_errors)
    if _map(resolved.get("lap")).get("is_valid") is not True:
        reasons.append("lap_validity_unproved")
    if (
        _map(resolved.get("lap")).get("complete") is False
        or _map(resolved.get("lap")).get("partial") is True
    ):
        reasons.append("lap_incomplete")
    traffic = archive_traffic_eligibility(resolved)
    if traffic is not None and not traffic.eligible:
        reasons.append(traffic.reason)
    try:
        snapshot.assert_current()
    except AttributionError as exc:
        reasons.append(str(exc))
    return _decision(not reasons, reasons, managed=True, authority=authority)


def register_practice_attribution(
    archive_path: str | Path,
    *,
    permit: Any,
    expected_combo: tuple[str, str, str | None],
) -> dict[str, Any]:
    """Only a consumed live permit may append this fallible, experiment-only claim."""
    from tools.human_session import HumanSessionPermit

    if not isinstance(permit, HumanSessionPermit):
        raise AttributionError("practice_context_required")
    receipt = permit.accept_archive(archive_path, expected_combo=expected_combo)
    raw = _stable_bytes(Path(archive_path))
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise AttributionError("archive_root_invalid")
    resolved = resolve_archive_provenance(record, source_path=archive_path)
    old = _map(resolved.get("qualification"))
    if old.get("resolution_error"):
        raise AttributionError(str(old["resolution_error"]))
    if old and old.get("authority") != "attested_human":
        permit.revoke("restrictive_attribution_conflict")
        raise AttributionError("conflicting_attribution_identity")
    witness = permit.qualification_context(record, expected_combo=expected_combo)
    if receipt["source_sha256"] != hashlib.sha256(raw).hexdigest():
        raise AttributionError("input_changed_during_registration")
    evidence_digest = hashlib.sha256(
        json.dumps(witness, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    envelope = build_qualification(
        record,
        authority="attested_human",
        origin=PRACTICE_ORIGIN,
        supported_uses={use: use in SCOPED_USES | {"analysis"} for use in USES},
        channels={name: {"unit": unit, "basis": "measured"} for name, unit in _UNITS.items()},
        reasons=["operator_attestation_only", "no_generic_human_or_reference_promotion"],
        evidence=[
            {
                "kind": "operator_attested_human_control",
                "sha256": evidence_digest,
                "witness": witness,
            }
        ],
    )
    entry = {
        "identity": archive_identity(record),
        "payload_sha256": payload_sha256(record),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "qualification": envelope,
    }
    _validate_entries([entry])
    with permit._registration_guard(record, expected_combo=expected_combo):
        result = _append_attribution(archive_path, raw, entry, ledger_path=None)
    return {**result, "identity": entry["identity"], "qualification": envelope}


def duplicate_identity_reasons(records: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """Reject all managed identity collisions, including exact copies, before selection.

    A lone archive has no collection context. Legacy-only corpora keep existing
    behavior; any collision involving a selected/managed artifact fails closed.
    """
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        identity = archive_identity(record)
        lap_id, session, lap_n = (identity[key] for key in ("lap_uuid", "session_uuid", "lap_n"))
        if isinstance(lap_id, str) and lap_id:
            groups.setdefault(("lap", lap_id), []).append(index)
        if isinstance(session, str) and session and type(lap_n) is int:
            groups.setdefault(("session_lap", session, lap_n), []).append(index)
    collisions = [group for group in groups.values() if len(group) > 1]
    managed: set[int] = set()
    # Unique identities cannot collide. Resolve provenance only for contenders,
    # once per record even when both identity keys collide. Qualification itself
    # still validates every selected archive through its normal policy boundary.
    for index in sorted({index for group in collisions for index in group}):
        resolved = resolve_archive_provenance(records[index])
        if "qualification" in resolved or str(resolved.get("import_format", "")).startswith(
            "moza_"
        ):
            managed.add(index)
    return {
        index: "duplicate_archive_identity"
        for group in collisions
        if managed.intersection(group)
        for index in group
    }


def restricted_lap_identities(*, use: str) -> list[dict[str, Any]]:
    """Identify prior derived aggregates needing a rebuild even after raw retention.

    These are already registered restrictions, not fresh human-control claims.
    Consumers must not erase aggregates from this list: refuse unsafe merging or
    loading and require a deliberate rebuild with sufficient original evidence.
    """
    entries = _read_ledger(default_attribution_path(), required=ATTRIBUTIONS_ENV in os.environ)
    return [
        dict(entry["identity"])
        for entry in entries
        if (
            (
                _map(entry["qualification"]).get("authority") != "human"
                and not (
                    use == "plant_fit"
                    and native_harness_fit_evidence(
                        entry["qualification"],
                        identity=entry["identity"],
                        payload_digest=entry["payload_sha256"],
                        source_digest=entry["source_sha256"],
                    )
                )
            )
            or _map(_map(entry["qualification"]).get("supported_uses")).get(use) is not True
            or (
                _map(entry["qualification"]).get("authority") == "human"
                and use != "analysis"
                and not human_attestation_enabled()
            )
        )
    ]


def register_attribution(
    archive_path: str | Path,
    qualification: Mapping[str, Any],
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append AI facts atomically; only evidenced native control may grant plant use."""
    if not isinstance(qualification, Mapping):
        raise AttributionError("qualification_root_invalid")
    raw = _stable_bytes(Path(archive_path))
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise AttributionError("archive_root_invalid")
    reason = _binding_reason(record, qualification)
    if reason:
        raise AttributionError(reason)
    if qualification.get("authority") not in {"ai", "shared", "unknown"}:
        raise AttributionError("registration_cannot_certify_human_control")
    uses = _map(qualification.get("supported_uses"))
    native_fit = (
        record.get("source") == "in_game"
        and record.get("import_format") is None
        and native_harness_fit_evidence(
            qualification,
            identity=archive_identity(record),
            payload_digest=payload_sha256(record),
            source_digest=hashlib.sha256(raw).hexdigest(),
        )
    )
    if any(
        value is True
        for key, value in uses.items()
        if key != "analysis" and not (key == "plant_fit" and native_fit)
    ):
        raise AttributionError("registration_cannot_promote_production_use")
    evidence = qualification.get("evidence")
    if (
        not isinstance(evidence, list)
        or not evidence
        or any(
            not isinstance(item, dict) or not item.get("kind") or not _is_hash(item.get("sha256"))
            for item in evidence
        )
    ):
        raise AttributionError("attribution_evidence_missing")
    return _append_entry(archive_path, raw, record, qualification, ledger_path=ledger_path)


def register_human_attestation(
    archive_path: str | Path,
    qualification: Mapping[str, Any],
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one #988 capture-time attestation; the only human-authority writer.

    Default off. The envelope must be the producer's own, carry a witness that
    still certifies against the archive bytes read here, and target a native lap
    with no existing ledger entry: a registered AI, shared or unknown fact is
    never replaced or promoted. ``register_attribution`` still refuses human
    authority; its only new effect is that a restrictive fact for the exact same
    lap supersedes (revokes) an attestation written here.
    """
    if not human_attestation_enabled():
        raise AttributionError("human_control_attestation_disabled")
    if not isinstance(qualification, Mapping):
        raise AttributionError("qualification_root_invalid")
    raw = _stable_bytes(Path(archive_path))
    try:
        # Stricter than other readers: a duplicate key could shadow a capture fact.
        record = json.loads(raw, object_pairs_hook=_unique_keys)
    except (ValueError, RecursionError) as exc:
        raise AttributionError("archive_unreadable") from exc
    if not isinstance(record, dict):
        raise AttributionError("archive_root_invalid")
    reason = _binding_reason(record, qualification)
    if reason:
        raise AttributionError(reason)
    if record.get("source") != "in_game" or record.get("import_format") is not None:
        raise AttributionError("human_attestation_source_unsupported")
    if not human_control_attestation_evidence(
        qualification,
        identity=archive_identity(record),
        payload_digest=payload_sha256(record),
        source_digest=hashlib.sha256(raw).hexdigest(),
        record=record,
    ):
        raise AttributionError("human_control_evidence_invalid")
    return _append_entry(archive_path, raw, record, qualification, ledger_path=ledger_path)


def _append_entry(
    archive_path: str | Path,
    raw: bytes,
    record: Mapping[str, Any],
    qualification: Mapping[str, Any],
    *,
    ledger_path: str | Path | None,
) -> dict[str, Any]:
    """Shared atomic append; a restrictive entry is never replaced or broadened.

    The single replacement is revocation of a #988 human attestation by a
    restrictive fact for the exact same identity.
    """
    identity = archive_identity(record)
    if _identity_reasons(identity):
        raise AttributionError("attribution_identity_incomplete")
    entry = {
        "identity": identity,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_sha256": payload_sha256(record),
        "qualification": dict(qualification),
    }
    _validate_entries([entry])
    return _append_attribution(archive_path, raw, entry, ledger_path=ledger_path)


def _append_attribution(
    archive_path: str | Path,
    raw: bytes,
    entry: dict[str, Any],
    *,
    ledger_path: str | Path | None,
) -> dict[str, Any]:
    identity = entry["identity"]
    path = Path(ledger_path) if ledger_path is not None else default_attribution_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise AttributionError("attribution_writer_busy") from exc
    temp_name = None
    try:
        os.close(fd)
        entries = _read_ledger(path, required=False)
        selected = [item for item in entries if _same_selected_identity(item["identity"], identity)]
        superseded = False
        if selected:
            if len(selected) == 1 and selected[0] == entry:
                return {
                    "registered": False,
                    "reason": "already_registered",
                    "source_sha256": entry["source_sha256"],
                }
            # Revocation only: a restrictive fact replaces a #988 human attestation
            # of the same lap. Nothing ever replaces a restrictive fact.
            if (
                len(selected) != 1
                or selected[0]["identity"] != identity
                or _map(selected[0]["qualification"]).get("authority") != "human"
                or _map(entry["qualification"]).get("authority") not in {"ai", "shared", "unknown"}
            ):
                raise AttributionError("conflicting_attribution_identity")
            entries = [item for item in entries if item is not selected[0]]
            superseded = True
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temp_name = output.name
            json.dump(
                {"schema_version": 1, "entries": [*entries, entry]},
                output,
                indent=2,
                allow_nan=False,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if raw != _stable_bytes(Path(archive_path)):
            raise AttributionError("input_changed_during_registration")
        os.replace(temp_name, path)
        temp_name = None
        return {
            "registered": True,
            "reason": "superseded_human_attestation" if superseded else "registered",
            "source_sha256": entry["source_sha256"],
        }
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="append a restrictive native attribution")
    register.add_argument("--archive", required=True, type=Path)
    register.add_argument("--qualification", required=True, type=Path)
    register.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)
    try:
        envelope = json.loads(args.qualification.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise AttributionError("qualification_root_invalid")
        receipt = register_attribution(args.archive, envelope, ledger_path=args.ledger)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"registered": False, "reason": str(exc)}))
        return 1
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
