"""Capture-time human-control attestation for native lap archives (#988).

Default off (``AC_COPILOT_HUMAN_CONTROL_ATTESTATION=1`` opts in). The producer turns
process-level capture signals into ``verified_human_control`` evidence bound to the
archive payload hash, or into ``unverified`` with every specific reason. It is never
a telemetry classifier and it never infers a human from the absence of a signal:

* project autonomous driver - the CSP Custom-AI sections must be *read absent*
  continuously from the operator declaration to the end of the lap, with AC's own
  section readable through the same opener as a positive control;
* native game AI - CSP's per-frame ``car.isAIControlled`` summary inside the archive;
* vendor AI driving - the vendor practice record's AI-intervened label, joined by
  session window, combo and lap duration (it shares no session identifier);
* operator declaration from Game Point or the rig controls; necessary, never sufficient.

The decision itself lives in ``tools.lap_qualification.human_witness_reasons`` so the
producer and every later reader apply one rule. A lap that already has a ledger
entry is never attested, relabelled or promoted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from tools.lap_qualification import (
    _UNITS,
    ATTRIBUTIONS_ENV,
    HUMAN_ATTESTATION_DECLARATION_SURFACES,
    HUMAN_ATTESTATION_DECLARE_ACTION,
    HUMAN_ATTESTATION_MAX_PROBE_GAP_MS,
    HUMAN_ATTESTATION_ORIGIN,
    HUMAN_ATTESTATION_REFERENCE_SECTION,
    HUMAN_ATTESTATION_SECTIONS,
    HUMAN_ATTESTATION_USES,
    HUMAN_ATTESTATION_VENDOR_LAP_TOLERANCE_MS,
    HUMAN_ATTESTATION_WINDOW_MARGIN_MS,
    USES,
    AttributionError,
    _identity_reasons,
    _is_hash,
    _map,
    _read_ledger,
    _stable_bytes,
    _utc_ms,
    archive_identity,
    build_qualification,
    human_attestation_enabled,
    human_control_attestation_evidence,
    human_witness_reasons,
    payload_sha256,
    register_human_attestation,
    resolve_archive_provenance,
)

CAPTURE_JOURNAL = "capture.jsonl"
DECLARATION_JOURNAL = "declarations.jsonl"
VENDOR_DIR = "vendor"
DECLARATION_JOURNAL_ENV = "AC_COPILOT_HUMAN_DECLARATION_JOURNAL"
CLEAR_ACTION = "human_control.clear"
DECLARATION_ACTIONS = (HUMAN_ATTESTATION_DECLARE_ACTION, CLEAR_ACTION)
_DECLARATION_WRITE_LOCK = Lock()
DISABLED = "human_control_attestation_disabled"
ERROR_FILE_NOT_FOUND = 2
MAX_VENDOR_BYTES = 1_000_000
BENCH_ARMS = frozenset(
    {
        "human",
        "project_autonomous",
        "vendor_ai",
        "vendor_ai_mid_lap",
        "vendor_ai_record_missing",
        "native_ai",
    }
)


@dataclass(frozen=True)
class Attestation:
    """``verified`` carries a registrable envelope; otherwise every abstention reason."""

    verified: bool
    reason: str
    reasons: tuple[str, ...]
    qualification: dict[str, Any] | None = None
    witness_sha256: str | None = None


class _InputError(ValueError):
    """A capture input exists but cannot be trusted as read."""


@contextmanager
def _ledger_scope(ledger_path: str | Path | None) -> Iterator[None]:
    """Make a named ledger the one store read and written, then restore the caller's."""
    if ledger_path is None:
        yield
        return
    previous = os.environ.get(ATTRIBUTIONS_ENV)
    os.environ[ATTRIBUTIONS_ENV] = str(ledger_path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ATTRIBUTIONS_ENV, None)
        else:
            os.environ[ATTRIBUTIONS_ENV] = previous


def unverified(*reasons: str) -> Attestation:
    unique = tuple(dict.fromkeys(reasons)) or ("attestation_unavailable",)
    return Attestation(False, unique[0], unique)


# --------------------------------------------------------------------------------------
# Capture inputs
# --------------------------------------------------------------------------------------
def classify_open_result(opened: bool, last_error: int) -> str:
    """Tri-state for one open-existing attempt.

    Only a failed open whose error is ``ERROR_FILE_NOT_FOUND`` is ``absent``. Access
    denied, a wrong namespace or any other failure is ``error`` and makes the lap
    unverifiable; it is never read as "controller not present".
    """
    if opened:
        return "present"
    return "absent" if last_error == ERROR_FILE_NOT_FOUND else "error"


def probe_sample(open_existing: Callable[[str], tuple[bool, int]], now_ms: int) -> dict[str, Any]:
    """One read-only observation of the control map and the positive control."""

    def state(name: str) -> str:
        try:
            opened, last_error = open_existing(name)
        except Exception:  # noqa: BLE001 - any probe failure must surface as "error"
            return "error"
        if type(opened) is not bool or type(last_error) is not int:
            return "error"
        return classify_open_result(opened, last_error)

    return {
        "kind": "probe",
        "t_ms": now_ms,
        "sections": {name: state(name) for name in HUMAN_ATTESTATION_SECTIONS},
        "reference": state(HUMAN_ATTESTATION_REFERENCE_SECTION),
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InputError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _InputError("nonfinite_value")


def _loads(raw: bytes | str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _InputError("invalid_json") from exc


def parse_journal(raw: bytes) -> list[dict[str, Any]]:
    """Strict JSON-lines reader: any torn, mistyped or time-reversed line is fatal."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise _InputError("invalid_encoding") from exc
    events: list[dict[str, Any]] = []
    previous = None
    for line in text.split("\n"):
        if not line.strip():
            continue
        event = _loads(line)
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("kind"), str)
            or type(event.get("t_ms")) is not int
            or event["t_ms"] <= 0
        ):
            raise _InputError("invalid_event")
        if previous is not None and event["t_ms"] < previous:
            raise _InputError("clock_regression")
        previous = event["t_ms"]
        events.append(event)
    return events


def _declaration_facts(
    raw: bytes | None, lap_start: int, lap_end: int, reasons: list[str]
) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        events = parse_journal(raw)
        if any(
            event["kind"] != "declaration"
            or event.get("surface") not in HUMAN_ATTESTATION_DECLARATION_SURFACES
            or event.get("action") not in DECLARATION_ACTIONS
            for event in events
        ):
            raise _InputError("invalid_event")
    except _InputError:
        reasons.append("declaration_journal_invalid")
        return None
    declared = [e for e in events if e["action"] == HUMAN_ATTESTATION_DECLARE_ACTION]
    if not declared:
        return None
    before = [e for e in declared if e["t_ms"] <= lap_start]
    selected = before[-1] if before else declared[0]
    declared_ms = selected["t_ms"]
    return {
        "surface": selected["surface"],
        "action": HUMAN_ATTESTATION_DECLARE_ACTION,
        "journal_sha256": hashlib.sha256(raw).hexdigest(),
        "declared_ms": declared_ms,
        "cleared_count": sum(
            1 for e in events if e["action"] == CLEAR_ACTION and declared_ms <= e["t_ms"] <= lap_end
        ),
    }


def _control_map_facts(
    raw: bytes, events: Sequence[Mapping[str, Any]], coverage_start: int, end_ms: int
) -> dict[str, Any] | None:
    probes = [event for event in events if event["kind"] == "probe"]
    if not probes:
        return None
    first = max((i for i, e in enumerate(probes) if e["t_ms"] <= coverage_start), default=0)
    last = min((i for i, e in enumerate(probes) if e["t_ms"] >= end_ms), default=len(probes) - 1)
    selected = probes[first : last + 1]
    if not selected:
        return None
    expected = set(HUMAN_ATTESTATION_SECTIONS)
    present = error = reference_unavailable = 0
    for event in selected:
        sections = event.get("sections")
        states = list(sections.values()) if isinstance(sections, dict) else []
        if (
            not isinstance(sections, dict)
            or set(sections) != expected
            or any(state not in ("absent", "present") for state in states)
        ):
            error += 1
        elif "present" in states:
            present += 1
        if event.get("reference") != "present":
            reference_unavailable += 1
    return {
        "sections": list(HUMAN_ATTESTATION_SECTIONS),
        "reference_section": HUMAN_ATTESTATION_REFERENCE_SECTION,
        "journal_sha256": hashlib.sha256(raw).hexdigest(),
        "sample_count": len(selected),
        "present_count": present,
        "error_count": error,
        "reference_unavailable_count": reference_unavailable,
        "first_ms": selected[0]["t_ms"],
        "last_ms": selected[-1]["t_ms"],
        "max_gap_ms": max(
            (b["t_ms"] - a["t_ms"] for a, b in zip(selected, selected[1:], strict=False)),
            default=0,
        ),
    }


def _vendor_candidate(
    read_ms: int, digest: str, raw: bytes, lap_ms: int, lap_n: int
) -> tuple[dict[str, Any], str, bool] | None:
    """Facts from one vendor practice record, its session, and whether it flags this lap.

    ``None`` means the bytes cannot be read as a practice record.
    """
    if hashlib.sha256(raw).hexdigest() != digest:
        return None
    try:
        payload = _loads(raw)
    except _InputError:
        return None
    if (
        not isinstance(payload, dict)
        or type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != 1
        or type(payload.get("sessionStartedAtMs")) is not int
        or type(payload.get("savedAtMs")) is not int
        or not isinstance(payload.get("sessionId"), str)
        or not payload["sessionId"]
    ):
        return None
    summary = payload.get("summary")
    rows = summary.get("laps") if isinstance(summary, dict) else None
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    matches = []
    flagged = False
    for row in rows:
        # Any row carrying this lap's number with an AI label counts against the lap,
        # whatever duration that row currently shows.
        # Deliberately loose on the number's type: 2, 2.0 and "2" all name this lap.
        number = row.get("lapNumber")
        if (number == lap_n or str(number) == str(lap_n)) and (
            row.get("aiIntervened") is True or row.get("eligibility") == "ai-debug-only"
        ):
            flagged = True
        seconds = row.get("lapTimeSeconds")
        if seconds is None:
            continue  # a lap the vendor has not timed yet
        if type(seconds) not in (int, float) or not math.isfinite(seconds):
            return None
        if not 0 < seconds < 86_400:
            continue
        duration = round(seconds * 1000)
        if abs(duration - lap_ms) <= HUMAN_ATTESTATION_VENDOR_LAP_TOLERANCE_MS:
            matches.append((duration, row))
    lap = None
    key = summary.get("referenceKey")
    if matches:
        duration, row = matches[0]
        key = row.get("referenceKey", key)
        lap = {
            "lap_time_ms": duration,
            "lap_number": row.get("lapNumber"),
            "ai_intervened": row.get("aiIntervened"),
            "complete": row.get("complete"),
            "finalized": row.get("finalized"),
            "eligibility": row.get("eligibility"),
        }
    facts = {
        "record_sha256": digest,
        "read_ms": read_ms,
        "session_started_ms": payload["sessionStartedAtMs"],
        "saved_ms": payload["savedAtMs"],
        "reference_key": key if isinstance(key, str) else None,
        "matched_laps": len(matches),
        "session_lap_count": len(rows),
        "lap": lap,
    }
    return facts, payload["sessionId"], flagged


def _vendor_facts(
    events: Sequence[Mapping[str, Any]],
    vendor: Mapping[str, bytes],
    lap_ms: int,
    lap_n: int,
    exported_ms: int,
    reasons: list[str],
) -> dict[str, Any] | None:
    """The latest read of a record that can contain this lap, or why none is usable.

    The last look at the vendor file must have succeeded, and every record read after
    the finish must be readable: a failed or malformed later read is never skipped in
    favour of an earlier, cleaner one. A record saved before the latest possible
    finish cannot be relied on to contain the lap and is not a candidate. A read that
    marks this lap number as AI-intervened, or an in-lap read that cannot be parsed,
    counts as a disagreement even if a later read shows the lap clean.
    """
    lap_start, lap_end = exported_ms - lap_ms, exported_ms + 1000
    snapshots = [event for event in events if event["kind"] == "vendor_snapshot"]
    reads = [event for event in snapshots if _is_hash(event.get("sha256"))]
    if not reads:
        return None
    after = [event for event in snapshots if event["t_ms"] >= lap_end]
    if after and not _is_hash(after[-1].get("sha256")):
        reasons.append("vendor_record_unreadable")
        return None
    parsed: dict[str, tuple[dict[str, Any], str, bool] | None] = {}

    def candidate(event: Mapping[str, Any]) -> tuple[dict[str, Any], str, bool] | None:
        digest = event["sha256"]
        raw = vendor.get(digest)
        result = _vendor_candidate(event["t_ms"], digest, raw, lap_ms, lap_n) if raw else None
        if result is not None or digest not in parsed:
            parsed[digest] = result  # keeps the latest read time per content
        return result

    considered = [event for event in after if _is_hash(event.get("sha256"))] or [reads[-1]]
    for event in considered:
        if candidate(event) is None:
            reasons.append("vendor_record_unreadable")
            return None
    ordered = sorted(
        (parsed[digest] for digest in dict.fromkeys(event["sha256"] for event in considered)),
        key=lambda item: item[0]["read_ms"],
    )
    covering = [
        item
        for item in ordered
        if item[0]["saved_ms"] >= lap_end and item[0]["session_started_ms"] <= lap_start + 1000
    ]
    if not covering:
        return {**ordered[-1][0], "covering_reads": 0, "disagreeing_reads": 0}
    decision, session, _ = covering[-1]
    # A look at the file that failed after the deciding content was last read may
    # have hidden a change to it, even if a newer session's record was read later.
    if any(
        not _is_hash(event.get("sha256")) and event["t_ms"] > decision["read_ms"] for event in after
    ):
        reasons.append("vendor_record_unreadable")
        return None
    # Every record that contradicts the deciding read, counted once per content.
    contradicting = {
        facts["record_sha256"]
        for facts, other, flagged in covering[:-1]
        if flagged
        or other != session
        or facts["matched_laps"] > 1
        or (facts["matched_laps"] and facts["lap"] != decision["lap"])
    }
    # Reads taken while the lap was running (from the earliest start the wall-clock
    # rule allows) are evidence too; one that cannot be parsed counts against the lap.
    in_lap_start = lap_start - HUMAN_ATTESTATION_WINDOW_MARGIN_MS
    for event in reads:
        digest = event["sha256"]
        if in_lap_start <= event["t_ms"] < lap_end and digest not in parsed:
            if candidate(event) is None:
                contradicting.add(digest)
    # A record that marks this lap number as AI contradicts a clean verdict when it
    # belongs to the deciding vendor session, or to any session overlapping the lap
    # that was saved after the lap began.
    for digest, item in parsed.items():
        if item is None or not item[2]:
            continue
        facts, other, _ = item
        if other == session or (
            facts["saved_ms"] >= in_lap_start and facts["session_started_ms"] <= lap_end
        ):
            contradicting.add(digest)
    disagreeing = len(contradicting)
    return {**decision, "covering_reads": len(covering), "disagreeing_reads": disagreeing}


# --------------------------------------------------------------------------------------
# Producer
# --------------------------------------------------------------------------------------
def signal_reasons(
    record: Mapping[str, Any],
    *,
    source_sha256: str,
    capture_journal: bytes | None,
    declaration_journal: bytes | None,
    vendor: Mapping[str, bytes] | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    """All signal-level abstention reasons and, when the record is usable, the witness.

    This never consults or changes the ledger and never honours the opt-in by
    itself; :func:`attest_lap` adds both guards before anything can certify.
    """
    if not isinstance(record, Mapping):
        return ["archive_root_invalid"], None
    reasons: list[str] = []
    if type(record.get("schema_version")) is not int or record.get("schema_version") != 1:
        reasons.append("archive_schema_unsupported")
    if record.get("source") != "in_game" or record.get("import_format") is not None:
        reasons.append("archive_source_unsupported")
    identity = archive_identity(record)
    reasons.extend(_identity_reasons(identity))
    if not _is_hash(source_sha256):
        reasons.append("archive_source_hash_unavailable")
    try:
        digest = payload_sha256(record)
    except AttributionError as exc:
        reasons.append(str(exc))
        digest = None
    exported_ms = _utc_ms(record.get("exported_at"))
    if exported_ms is None:
        reasons.append("attestation_lap_window_unavailable")
    if reasons or digest is None or exported_ms is None:
        return list(dict.fromkeys(reasons)), None
    lap_ms = identity["lap_ms"]
    lap_start, lap_end = exported_ms - lap_ms, exported_ms + 1000
    start_ms = lap_start - HUMAN_ATTESTATION_WINDOW_MARGIN_MS
    end_ms = lap_end + HUMAN_ATTESTATION_WINDOW_MARGIN_MS

    declaration = _declaration_facts(declaration_journal, lap_start, lap_end, reasons)
    events: list[dict[str, Any]] = []
    control = vendor_facts = None
    if capture_journal is not None:
        try:
            events = parse_journal(capture_journal)
        except _InputError:
            reasons.append("capture_journal_invalid")
        else:
            coverage_start = min(start_ms, declaration["declared_ms"]) if declaration else start_ms
            control = _control_map_facts(capture_journal, events, coverage_start, end_ms)
            vendor_facts = _vendor_facts(
                events, vendor or {}, lap_ms, identity["lap_n"], exported_ms, reasons
            )
    observation = _map(record.get("trace")).get("control_observation")
    witness = {
        "schema_version": 1,
        "producer": HUMAN_ATTESTATION_ORIGIN,
        "archive": {
            "identity": identity,
            "source": record.get("source"),
            "import_format": record.get("import_format"),
            "exported_at": record.get("exported_at"),
            "payload_sha256": digest,
            "source_sha256": source_sha256,
        },
        "window": {"start_ms": start_ms, "end_ms": end_ms},
        "declaration": declaration,
        "control_map": control,
        "native_ai": dict(observation) if isinstance(observation, Mapping) else None,
        "vendor_practice": vendor_facts,
    }
    reasons.extend(
        human_witness_reasons(
            witness,
            identity=identity,
            payload_digest=digest,
            source_digest=source_sha256,
            record=record,
        )
    )
    return list(dict.fromkeys(reasons)), witness


def attest_lap(
    record: Mapping[str, Any],
    *,
    source_sha256: str,
    capture_journal: bytes | None,
    declaration_journal: bytes | None,
    vendor: Mapping[str, bytes] | None = None,
) -> Attestation:
    """Certify one native lap, or abstain with every specific reason."""
    if not human_attestation_enabled():
        return unverified(DISABLED)
    if not isinstance(record, Mapping):
        return unverified("archive_root_invalid")
    # Never relabel: an embedded assessment or any ledger fact (including an
    # unreadable ledger) ends attestation before a signal is even considered.
    resolved = resolve_archive_provenance(record, source_sha256=source_sha256)
    if "qualification" in resolved:
        existing = resolved["qualification"]
        error = _map(existing).get("resolution_error")
        if error:
            return unverified(f"attribution_unavailable:{error}")
        return unverified(f"existing_attribution:{_map(existing).get('authority') or 'unknown'}")
    reasons, witness = signal_reasons(
        record,
        source_sha256=source_sha256,
        capture_journal=capture_journal,
        declaration_journal=declaration_journal,
        vendor=vendor,
    )
    if reasons or witness is None:
        return unverified(*reasons)
    try:
        encoded = json.dumps(
            witness, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError):
        return unverified("attestation_witness_unserializable")
    digest = hashlib.sha256(encoded).hexdigest()
    envelope = build_qualification(
        record,
        authority="human",
        origin=HUMAN_ATTESTATION_ORIGIN,
        supported_uses={use: use in HUMAN_ATTESTATION_USES for use in USES},
        channels={name: {"unit": unit, "basis": "measured"} for name, unit in _UNITS.items()},
        evidence=[{"kind": "verified_human_control", "sha256": digest, "witness": witness}],
        reasons=["Capture-time attestation; human progression and analysis only."],
    )
    # The reader's rule must agree with the producer before anything is published.
    if not human_control_attestation_evidence(
        envelope,
        identity=archive_identity(record),
        payload_digest=witness["archive"]["payload_sha256"],
        source_digest=source_sha256,
        record=record,
    ):
        return unverified("attestation_self_check_failed")
    return Attestation(True, "verified_human_control", (), envelope, digest)


def _optional_bytes(path: Path, reason: str, reasons: list[str]) -> bytes | None:
    try:
        return _stable_bytes(path)
    except FileNotFoundError:
        return None
    except (AttributionError, OSError):
        reasons.append(reason)
        return None


def _capture_inputs(
    capture_dir: Path | None, reasons: list[str]
) -> tuple[bytes | None, bytes | None, dict[str, bytes]]:
    if capture_dir is None:
        return None, None, {}
    capture = _optional_bytes(capture_dir / CAPTURE_JOURNAL, "capture_journal_unreadable", reasons)
    declarations = _optional_bytes(
        capture_dir / DECLARATION_JOURNAL, "declaration_journal_unreadable", reasons
    )
    vendor: dict[str, bytes] = {}
    try:
        names = sorted((capture_dir / VENDOR_DIR).glob("*.json"))
    except OSError:
        names = []
    for name in names:
        raw = _optional_bytes(name, "vendor_record_unreadable", reasons)
        if raw is not None and _is_hash(name.stem):
            vendor[name.stem] = raw
    return capture, declarations, vendor


def attest_archive(archive_path: str | Path, capture_dir: str | Path | None) -> Attestation:
    """File-level producer: original archive bytes plus one capture directory."""
    if not human_attestation_enabled():
        return unverified(DISABLED)
    try:
        raw = _stable_bytes(Path(archive_path))
        record = _loads(raw)
    except (AttributionError, OSError, ValueError):
        return unverified("archive_unreadable")
    reasons: list[str] = []
    capture, declarations, vendor = _capture_inputs(
        Path(capture_dir) if capture_dir is not None else None, reasons
    )
    result = attest_lap(
        record,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        capture_journal=capture,
        declaration_journal=declarations,
        vendor=vendor,
    )
    # An input that exists but could not be read always abstains, whatever else held.
    return unverified(*reasons, *result.reasons) if reasons else result


def certify_archive(
    archive_path: str | Path,
    capture_dir: str | Path | None,
    *,
    register: bool = False,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Attest one archive and, only on request, append the certification.

    A named ledger is used for both the never-relabel guard and the append, so the
    guard can never read one store while the certification lands in another.
    """
    with _ledger_scope(ledger_path):
        result = attest_archive(archive_path, capture_dir)
        receipt: dict[str, Any] = {
            "archive": str(archive_path),
            "verified": result.verified,
            "reason": result.reason,
            "reasons": list(result.reasons),
            "witness_sha256": result.witness_sha256,
            "registered": None,
        }
        if result.verified and register and result.qualification is not None:
            try:
                receipt["registered"] = register_human_attestation(
                    archive_path, result.qualification, ledger_path=ledger_path
                )
            except (AttributionError, OSError, ValueError) as exc:
                receipt["registered"] = {"registered": False, "reason": str(exc)}
        return receipt


# --------------------------------------------------------------------------------------
# Offline scorecard and bench verdict
# --------------------------------------------------------------------------------------
def scorecard(
    ledger_path: str | Path, laps_dir: str | Path, *, first: int | None = None
) -> dict[str, Any]:
    """Run the producer over laps already attributed non-human; it must certify none.

    Read-only. Each registered identity is located among the archives by exact
    identity. ``signal_reasons`` are reported separately from the ledger guard so
    a zero is not merely "the ledger already said so".
    """
    with _ledger_scope(ledger_path):
        return _scorecard(Path(ledger_path), Path(laps_dir), first)


def _scorecard(ledger_path: Path, laps_dir: Path, first: int | None) -> dict[str, Any]:
    entries = _read_ledger(ledger_path, required=True)
    selected = entries if first is None else entries[:first]
    wanted = {entry["identity"]["lap_uuid"]: entry for entry in selected}
    found: dict[str, tuple[Path, bytes, dict[str, Any]]] = {}
    unreadable = 0
    for path in sorted(laps_dir.glob("*.json")):
        try:
            raw = _stable_bytes(path)
            record = json.loads(raw)
        except (AttributionError, OSError, ValueError, RecursionError):
            unreadable += 1
            continue
        if isinstance(record, dict) and record.get("lap_uuid") in wanted:
            found[record["lap_uuid"]] = (path, raw, record)
    rows = []
    histogram: Counter[str] = Counter()
    certified = signals_clear = evaluated = 0
    for lap_uuid, entry in wanted.items():
        authority = _map(entry["qualification"]).get("authority")
        if lap_uuid not in found:
            rows.append({"lap_uuid": lap_uuid, "ledger_authority": authority, "archive": None})
            continue
        path, raw, record = found[lap_uuid]
        digest = hashlib.sha256(raw).hexdigest()
        result = attest_lap(
            record, source_sha256=digest, capture_journal=None, declaration_journal=None
        )
        signals, _ = signal_reasons(
            record, source_sha256=digest, capture_journal=None, declaration_journal=None
        )
        evaluated += 1
        certified += result.verified
        signals_clear += not signals
        histogram.update(signals)
        rows.append(
            {
                "lap_uuid": lap_uuid,
                "ledger_authority": authority,
                "archive": path.name,
                "verified": result.verified,
                "reasons": list(result.reasons),
                "signal_reasons": signals,
            }
        )
    return {
        "schema_version": 1,
        "enabled": human_attestation_enabled(),
        "ledger_entries": len(entries),
        "selected_entries": len(selected),
        "archives_evaluated": evaluated,
        "archives_missing": len(selected) - evaluated,
        "archives_unreadable": unreadable,
        "certified": certified,
        "signals_clear_without_ledger_guard": signals_clear,
        "signal_reason_histogram": dict(sorted(histogram.items())),
        "laps": rows,
    }


def bench_verdict(
    manifest: Mapping[str, Any], results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply #988's fixed acceptance rule to a pre-labelled bench session.

    ``manifest["laps"]`` rows carry ``session_uuid``, ``lap_n`` and ``arm``; results
    are :func:`certify_archive` receipts extended with the archive identity. A
    labelled lap without a result counts as not captured. Any certified non-human
    or mixed lap is FAIL, whatever else happened (the stop rule).
    """
    laps = manifest.get("laps") if isinstance(manifest, Mapping) else None
    if not isinstance(laps, list) or any(
        not isinstance(row, Mapping)
        or row.get("arm") not in BENCH_ARMS
        or not isinstance(row.get("session_uuid"), str)
        or type(row.get("lap_n")) is not int
        for row in laps
    ):
        return {"verdict": "INCONCLUSIVE", "reasons": ["manifest_invalid"]}
    keys = [(row["session_uuid"], row["lap_n"]) for row in laps]
    if len(set(keys)) != len(keys):
        return {"verdict": "INCONCLUSIVE", "reasons": ["manifest_duplicate_lap"]}
    if any(
        not isinstance(result, Mapping) or type(result.get("verified")) is not bool
        for result in results
    ):
        return {"verdict": "INCONCLUSIVE", "reasons": ["results_invalid"]}
    by_key = {}
    for result in results:
        identity = _map(result.get("identity"))
        by_key.setdefault((identity.get("session_uuid"), identity.get("lap_n")), []).append(result)
    counts: Counter[str] = Counter()
    certified: Counter[str] = Counter()
    false_certifications = []
    for row, key in zip(laps, keys, strict=True):
        matched = by_key.get(key, [])
        verified = any(result.get("verified") is True for result in matched)
        if verified and row["arm"] != "human":
            false_certifications.append(dict(row))
        if len(matched) != 1:
            continue
        counts[row["arm"]] += 1
        certified[row["arm"]] += verified
    unlabelled = [key for key in by_key if key not in set(keys)]
    vendor_total = sum(counts[arm] for arm in BENCH_ARMS if arm.startswith("vendor_ai"))
    summary = {
        "captured": dict(sorted(counts.items())),
        "certified": dict(sorted(certified.items())),
        "false_certifications": false_certifications,
        "unlabelled_results": len(unlabelled),
    }
    if false_certifications:
        return {"verdict": "FAIL", "reasons": ["non_human_lap_certified"], **summary}
    if any(
        result.get("verified") is True and not _is_hash(result.get("witness_sha256"))
        for result in results
    ):
        return {"verdict": "FAIL", "reasons": ["certification_without_hash_binding"], **summary}
    reasons = []
    if unlabelled:
        reasons.append("unlabelled_results")
    if counts["human"] < 6:
        reasons.append("fewer_than_6_human_laps")
    if counts["project_autonomous"] < 4:
        reasons.append("fewer_than_4_project_autonomous_laps")
    if vendor_total < 4:
        reasons.append("fewer_than_4_vendor_ai_laps")
    if counts["vendor_ai_mid_lap"] < 2:
        reasons.append("fewer_than_2_vendor_ai_mid_lap_laps")
    if counts["vendor_ai_record_missing"] < 1:
        reasons.append("no_vendor_record_missing_lap")
    if manifest.get("vendor_record_available") is not True:
        reasons.append("vendor_record_unavailable_for_session")
    if reasons:
        return {"verdict": "INCONCLUSIVE", "reasons": reasons, **summary}
    if certified["human"] * 6 < counts["human"] * 5:
        return {"verdict": "FAIL", "reasons": ["fewer_than_5_of_6_human_laps_certified"], **summary}
    return {"verdict": "PASS", "reasons": [], **summary}


# --------------------------------------------------------------------------------------
# Operator declaration sink and capture monitor
# --------------------------------------------------------------------------------------
def record_declaration(
    path: Path, action: str, *, surface: str = "rig_controls", now_ms: int | None = None
) -> None:
    """Append one operator declaration event; the file is only ever appended to."""
    if action not in DECLARATION_ACTIONS:
        raise ValueError("unknown declaration action")
    if surface not in HUMAN_ATTESTATION_DECLARATION_SURFACES:
        raise ValueError("unknown declaration surface")
    # The launcher GUI and keypad worker share one process and may both append.
    # Timestamp inside the same lock so their records preserve journal order.
    with _DECLARATION_WRITE_LOCK:
        event = {
            "kind": "declaration",
            "t_ms": int(time.time() * 1000) if now_ms is None else now_ms,
            "surface": surface,
            "action": action,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())


def declaration_sink(*, surface: str = "rig_controls") -> Callable[[str], None] | None:
    """Return the surface's journal writer while process-local capture is configured."""
    target = os.environ.get(DECLARATION_JOURNAL_ENV)
    if not human_attestation_enabled() or not target or not target.strip():
        return None
    path = Path(target).expanduser()
    return lambda action: record_declaration(path, action, surface=surface)


def _win_open_existing(name: str) -> tuple[bool, int]:  # pragma: no cover - rig-only
    """Open-existing-only, read-only; never creates or writes a section."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenFileMappingW.restype = wintypes.HANDLE
    kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel32.OpenFileMappingW(0x0004, False, name)
    if handle:
        kernel32.CloseHandle(handle)
        return True, 0
    return False, int(ctypes.get_last_error())


def run_monitor(
    capture_dir: Path,
    *,
    open_existing: Callable[[str], tuple[bool, int]],
    vendor_snapshot: Path | None = None,
    period_s: float = 0.1,
    vendor_period_s: float = 2.0,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """Journal read-only probes (and vendor-record reads) until stopped.

    The vendor practice record is one rolling file that the next session overwrites,
    so every distinct content is preserved once under ``vendor/<sha256>.json``.
    """
    if period_s <= 0 or period_s * 1000 > HUMAN_ATTESTATION_MAX_PROBE_GAP_MS / 2:
        raise ValueError("probe period must stay well inside the maximum probe gap")
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / VENDOR_DIR).mkdir(exist_ok=True)
    written = 0
    next_vendor = 0.0
    with (capture_dir / CAPTURE_JOURNAL).open("a", encoding="utf-8") as journal:

        def emit(event: dict[str, Any]) -> None:
            nonlocal written
            journal.write(json.dumps(event, sort_keys=True) + "\n")
            journal.flush()
            written += 1

        emit(
            {
                "kind": "header",
                "t_ms": int(clock() * 1000),
                "schema_version": 1,
                "sections": list(HUMAN_ATTESTATION_SECTIONS),
                "reference_section": HUMAN_ATTESTATION_REFERENCE_SECTION,
            }
        )
        while not should_stop():
            now = clock()
            emit(probe_sample(open_existing, int(now * 1000)))
            if vendor_snapshot is not None and now >= next_vendor:
                next_vendor = now + vendor_period_s
                event: dict[str, Any] = {"kind": "vendor_snapshot", "t_ms": int(now * 1000)}
                try:
                    raw = _stable_bytes(vendor_snapshot)
                    if len(raw) > MAX_VENDOR_BYTES:
                        raise AttributionError("vendor_record_too_large")
                    digest = hashlib.sha256(raw).hexdigest()
                    target = capture_dir / VENDOR_DIR / f"{digest}.json"
                    if not target.exists():
                        target.write_bytes(raw)
                    event["sha256"] = digest
                except FileNotFoundError:
                    event["status"] = "missing"
                except (AttributionError, OSError):
                    event["status"] = "unreadable"
                emit(event)
            sleep(period_s)
    return written


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _identity_of(path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(_stable_bytes(path))
    except (AttributionError, OSError, ValueError, RecursionError):
        return None
    return archive_identity(record) if isinstance(record, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    monitor = commands.add_parser("monitor", help="journal read-only capture signals (rig)")
    monitor.add_argument("--capture-dir", required=True, type=Path)
    monitor.add_argument("--vendor-snapshot", type=Path)
    monitor.add_argument("--period", type=float, default=0.1)
    attest = commands.add_parser("attest", help="attest archives against one capture directory")
    attest.add_argument("--archive", required=True, type=Path, action="append")
    attest.add_argument("--capture-dir", type=Path)
    attest.add_argument("--register", action="store_true")
    attest.add_argument("--ledger", type=Path)
    score = commands.add_parser("scorecard", help="offline check over attributed laps")
    score.add_argument("--ledger", required=True, type=Path)
    score.add_argument("--laps", required=True, type=Path)
    score.add_argument("--first", type=int)
    verdict = commands.add_parser("verdict", help="apply the bench acceptance rule")
    verdict.add_argument("--manifest", required=True, type=Path)
    # One results file per capture directory; a bench session has at least two.
    verdict.add_argument("--results", required=True, type=Path, action="append")
    args = parser.parse_args(argv)
    try:
        with _ledger_scope(getattr(args, "ledger", None)):
            return _run(args)
    except (AttributionError, _InputError, OSError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.command == "monitor":
        if not human_attestation_enabled():
            print(json.dumps({"ok": False, "reason": DISABLED}))
            return 2
        if sys.platform != "win32":
            print(json.dumps({"ok": False, "reason": "monitor_requires_windows"}))
            return 2
        try:  # pragma: no cover - rig-only
            run_monitor(
                args.capture_dir,
                open_existing=_win_open_existing,
                vendor_snapshot=args.vendor_snapshot,
                period_s=args.period,
            )
        except KeyboardInterrupt:  # pragma: no cover - rig-only
            pass
        return 0  # pragma: no cover - rig-only
    if args.command == "attest":
        receipts = [
            {
                "identity": _identity_of(path),
                **certify_archive(
                    path, args.capture_dir, register=args.register, ledger_path=args.ledger
                ),
            }
            for path in args.archive
        ]
        print(json.dumps({"schema_version": 1, "results": receipts}, indent=2))
        return 0
    if args.command == "scorecard":
        report = scorecard(args.ledger, args.laps, first=args.first)
        print(json.dumps(report, indent=2))
        clean = not report["certified"] and not report["signals_clear_without_ledger_guard"]
        return 0 if clean else 1
    manifest = _loads(_stable_bytes(args.manifest))
    rows: list[Any] = []
    for path in args.results:
        results = _loads(_stable_bytes(path))
        part = results.get("results") if isinstance(results, dict) else None
        if not isinstance(part, list):
            raise _InputError("results_invalid")
        rows.extend(part)
    report = bench_verdict(manifest, rows)
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
