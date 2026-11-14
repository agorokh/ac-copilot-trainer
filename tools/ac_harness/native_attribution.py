"""Prospective native AI control evidence for the explicit #529 plant-fit opt-in."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.lap_qualification import (
    _UNITS,
    NATIVE_HARNESS_ORIGIN,
    USES,
    AttributionError,
    _is_hash,
    _stable_bytes,
    archive_identity,
    build_qualification,
    native_harness_report_clean,
    payload_sha256,
    register_attribution,
)


def attribute_native_control(
    archive_paths: Sequence[str | Path],
    *,
    report: Mapping[str, Any],
    driver: str,
    app_install: Mapping[str, Any],
    evidence_dir: str | Path,
) -> dict[str, Any]:
    """Append exact current-run AI facts before fitting; never rewrite source bytes.

    Call only on the explicit native-ai-plant-fit path after archive collection and
    before handshake refinement. Failed or invalid laps remain attributed AI with
    plant fitting disabled. Existing restrictive ledger facts cannot be broadened.
    The independent write-once witness avoids hashing the later mutable report.
    """
    if driver not in {"handshake", "alien", "ggv"}:
        raise AttributionError("native_harness_driver_unsupported")
    session = report.get("session_uuid")
    if not isinstance(session, str) or not session:
        raise AttributionError("native_harness_session_missing")
    timed = report.get("timed_laps")
    if (
        not isinstance(timed, list)
        or not timed
        or any(
            not isinstance(row, dict)
            or type(row.get("lap_n")) is not int
            or type(row.get("lap_ms")) is not int
            or row["lap_n"] <= 0
            or row["lap_ms"] <= 0
            for row in timed
        )
    ):
        raise AttributionError("native_harness_timed_laps_missing")
    drive = report.get("drive")
    if not isinstance(drive, Mapping):
        raise AttributionError("native_harness_drive_missing")
    app = {key: app_install.get(key) for key in ("status", "installed_digest", "harness_digest")}
    clean = (
        native_harness_report_clean(report, driver=driver)
        and app["status"] == "match"
        and _is_hash(app["harness_digest"])
        and app["installed_digest"] == app["harness_digest"]
    )
    loaded = []
    identities = []
    for name in archive_paths:
        path = Path(name)
        raw = _stable_bytes(path)
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("source") != "in_game":
            raise AttributionError("native_harness_source_required")
        if (
            record.get("import_format") is not None
            or type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
        ):
            raise AttributionError("native_harness_schema_required")
        identity = archive_identity(record)
        if (
            identity["session_uuid"] != session
            or identity["car_id"] != report.get("car_id")
            or identity["track_id"] != report.get("track_id")
            or {"lap_n": identity["lap_n"], "lap_ms": identity["lap_ms"]} not in timed
        ):
            raise AttributionError("native_harness_report_identity_mismatch")
        if identity in identities:
            raise AttributionError("native_harness_duplicate_identity")
        identities.append(identity)
        loaded.append((path, raw, record))
    actual_laps = [(row["lap_n"], row["lap_ms"]) for row in identities]
    clean = clean and sorted(actual_laps) == sorted((row["lap_n"], row["lap_ms"]) for row in timed)
    witness = {
        "schema_version": 1,
        "driver": driver,
        "session_uuid": session,
        "clean_run": bool(clean),
        "report": {
            **{key: report.get(key) for key in ("ok", "session_uuid", "car_id", "track_id")},
            "drive": {
                **{
                    key: drive.get(key)
                    for key in (
                        "drove",
                        "sim_dead",
                        "session_replaced",
                        "recoveries",
                        "recovery_capped",
                        "unexpected_sim_pids",
                    )
                },
                "payload": {"ok": drive.get("payload", {}).get("ok")}
                if isinstance(drive.get("payload"), Mapping)
                else {},
            },
        },
        "timed_laps": timed,
        "app_install": app,
        "archives": [
            {
                "identity": archive_identity(record),
                "source": record["source"],
                "import_format": record.get("import_format"),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "payload_sha256": payload_sha256(record),
            }
            for _, raw, record in loaded
        ],
    }
    encoded = json.dumps(witness, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    witness_path = Path(evidence_dir) / "native-control-witness.json"
    witness_path.parent.mkdir(parents=True, exist_ok=True)
    with witness_path.open("xb") as output:
        output.write(encoded)
    receipts = []
    for path, raw, record in loaded:
        if raw != _stable_bytes(path):
            raise AttributionError("input_changed_during_native_attribution")
        lap = record.get("lap")
        plant_fit = bool(clean) and isinstance(lap, dict) and lap.get("is_valid") is True
        envelope = build_qualification(
            record,
            authority="ai",
            origin=NATIVE_HARNESS_ORIGIN,
            supported_uses={
                use: use == "analysis" or (use == "plant_fit" and plant_fit) for use in USES
            },
            channels={name: {"unit": unit, "basis": "measured"} for name, unit in _UNITS.items()},
            evidence=[
                {
                    "kind": "native_harness_plant_fit" if plant_fit else "native_harness_control",
                    "sha256": digest,
                    "witness": witness,
                }
            ],
            reasons=["Native harness AI control; never human progression or reference technique."],
        )
        receipts.append({"path": str(path), **register_attribution(path, envelope)})
    return {"witness": str(witness_path), "sha256": digest, "archives": receipts}
