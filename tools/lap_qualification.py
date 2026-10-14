"""Archive-bound qualification and append-only control attribution (#815).

This is a boundary policy, never a telemetry-tick operation. A missing default
ledger preserves legacy behavior without certifying a human driver. An explicitly
configured unavailable ledger fails closed. Evidence can restrict an immutable
native archive; registration cannot certify human control or promote it live.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.lap_trace_validity import completed_trace_reason, finish_wrap_cut

SCHEMA_VERSION = 1
ATTRIBUTIONS_ENV = "AC_COPILOT_LAP_ATTRIBUTIONS"
USES = frozenset(
    {"analysis", "map", "live_reference", "reference_comparison", "human_progression", "plant_fit"}
)
AUTHORITIES = frozenset({"human", "ai", "shared", "unknown"})
# Native archive acceleration channels use G; importing a channel still requires
# bound measured-unit evidence and does not inherit eligibility from this constant.
NATIVE_ACCELERATION_UNIT = "G"
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
        if not isinstance(authority, str) or authority not in {"ai", "shared", "unknown"}:
            raise AttributionError("attribution_store_invalid")
        uses = envelope.get("supported_uses")
        if (
            not isinstance(uses, dict)
            or set(uses) - USES
            or any(type(v) is not bool for v in uses.values())
            or any(v for key, v in uses.items() if key != "analysis")
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


def _binding_reason(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> str | None:
    if type(envelope.get("schema_version")) is not int or envelope.get("schema_version") != 1:
        return "qualification_schema_unsupported"
    binding = _map(envelope.get("binding"))
    if any(
        key not in binding or binding[key] != value
        for key, value in archive_identity(record).items()
    ):
        return "qualification_identity_mismatch"
    try:
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
    result = dict(record)
    # A byte-hash failure from a path reader cannot disappear on the subsequent
    # direct-dict boundary, where those original bytes are no longer available.
    if _map(record.get("qualification")).get("resolution_error"):
        return result
    try:
        entries = _read_ledger(default_attribution_path(), required=ATTRIBUTIONS_ENV in os.environ)
        identity = archive_identity(record)
        selected = [item for item in entries if _same_selected_identity(item["identity"], identity)]
        if len(selected) > 1:
            raise AttributionError("duplicate_attribution_identity")
        if not selected:
            return result
        entry = selected[0]
        if entry["identity"] != identity:
            raise AttributionError("attribution_identity_mismatch")
        if entry["payload_sha256"] != payload_sha256(record):
            raise AttributionError("attribution_payload_mismatch")
        if source_sha256 is None and source_path is not None:
            source_sha256 = hashlib.sha256(_stable_bytes(Path(source_path))).hexdigest()
        if source_sha256 is not None and entry["source_sha256"] != source_sha256:
            raise AttributionError("attribution_source_hash_mismatch")
        envelope = entry["qualification"]
        reason = _binding_reason(record, envelope)
        if reason:
            raise AttributionError(reason)
        result["qualification"] = dict(envelope)
    except (AttributionError, OSError) as exc:
        result["qualification"] = {"schema_version": 1, "resolution_error": str(exc)}
    return result


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


def _trace_reasons(record: Mapping[str, Any], envelope: Mapping[str, Any], use: str) -> list[str]:
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


def qualify_archive(
    record: Mapping[str, Any],
    *,
    use: str,
    expected_combo: tuple[str, str, str | None] | None = None,
) -> Qualification:
    """One policy for path-loaded archives and direct dictionary constructors."""
    if not isinstance(record, Mapping):
        return _decision(False, ["archive_root_invalid"], managed=True, authority="unknown")
    if use not in USES:
        return _decision(False, ["unsupported_use"], managed=True, authority="unknown")
    if "schema_version" in record and (
        type(record["schema_version"]) is not int or record["schema_version"] != 1
    ):
        return _decision(False, ["archive_schema_unsupported"], managed=True, authority="unknown")
    if _map(_map(record.get("generator")).get("tt_reference")).get("partial") is True:
        return _decision(False, ["partial_tt_reference"], managed=False, authority="legacy_unknown")
    resolved = resolve_archive_provenance(record)
    envelope = resolved.get("qualification")
    managed = "qualification" in resolved or str(resolved.get("import_format", "")).startswith(
        "moza_"
    )
    source = record.get("source")
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
        return _decision(True, ["legacy_unknown"], managed=False, authority="legacy_unknown")
    if not isinstance(envelope, Mapping):
        return _decision(False, ["qualification_missing"], managed=True, authority="unknown")
    if envelope.get("resolution_error"):
        return _decision(
            False, [str(envelope["resolution_error"])], managed=True, authority="unknown"
        )
    authority = str(envelope.get("authority") or "unknown")
    reasons = []
    binding_error = _binding_reason(resolved, envelope)
    if binding_error:
        reasons.append(binding_error)
    if authority not in AUTHORITIES:
        reasons.append("unknown_control_authority")
    if authority != "human" and use != "analysis":
        reasons.append(f"control_authority_not_human:{authority}")
    evidence = envelope.get("evidence")
    if authority == "human" and not any(
        isinstance(item, Mapping)
        and item.get("kind") == "verified_human_control"
        and _is_hash(item.get("sha256"))
        for item in (evidence if isinstance(evidence, list) else [])
    ):
        reasons.append("human_control_evidence_missing")
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
    reasons.extend(_trace_reasons(resolved, envelope, use))
    return _decision(not reasons, reasons, managed=True, authority=authority)


def duplicate_identity_reasons(records: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """Reject all managed identity collisions, including exact copies, before selection.

    A lone archive has no collection context. Legacy-only corpora keep existing
    behavior; any collision involving a selected/managed artifact fails closed.
    """
    groups: dict[tuple[Any, ...], list[int]] = {}
    managed: set[int] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        resolved = resolve_archive_provenance(record)
        if "qualification" in resolved or str(resolved.get("import_format", "")).startswith(
            "moza_"
        ):
            managed.add(index)
        identity = archive_identity(record)
        lap_id, session, lap_n = (identity[key] for key in ("lap_uuid", "session_uuid", "lap_n"))
        if isinstance(lap_id, str) and lap_id:
            groups.setdefault(("lap", lap_id), []).append(index)
        if isinstance(session, str) and session and type(lap_n) is int:
            groups.setdefault(("session_lap", session, lap_n), []).append(index)
    return {
        index: "duplicate_archive_identity"
        for group in groups.values()
        if len(group) > 1 and managed.intersection(group)
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
            _map(entry["qualification"]).get("authority") != "human"
            or _map(_map(entry["qualification"]).get("supported_uses")).get(use) is not True
        )
    ]


def register_attribution(
    archive_path: str | Path,
    qualification: Mapping[str, Any],
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one restrictive fact atomically, rejecting conflicts/concurrent writers."""
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
    if any(value is True for key, value in uses.items() if key != "analysis"):
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
        if selected:
            if len(selected) == 1 and selected[0] == entry:
                return {
                    "registered": False,
                    "reason": "already_registered",
                    "source_sha256": entry["source_sha256"],
                }
            raise AttributionError("conflicting_attribution_identity")
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
        return {"registered": True, "reason": "registered", "source_sha256": entry["source_sha256"]}
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
