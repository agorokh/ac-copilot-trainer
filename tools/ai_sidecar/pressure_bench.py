"""Default-deny, process-local permission for the adopted issue956 AI bench.

Canonical analysis eligibility is necessary but never grants setup authority.
An explicit arm binds one sealed native-AI case to a live rig-owner epoch, a
reviewed candidate/oracle pair and this runtime. Neither environment presence
nor a process restart arms anything. Decisions stay in experiments.jsonl.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import secrets
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.ac_harness.rig_lock import default_rig_session_lock_path, read_rig_session_owner
from tools.ai_sidecar.setup_prescription import TTL_S, WHEELS, _evaluate_prescription
from tools.lap_qualification import payload_sha256, qualify_archive

PERMIT_ENV = "AC_COPILOT_PRESSURE_BENCH_PERMIT"
MODE = "956_ai_bench"
CARD_MODE = "ai_bench"
ORACLE_MODE = "956_ai_bench_oracle"
AUTHORITY = "operator_adopted_pr970_native_ai_bench"
MAX_RUN_SECONDS = 4 * 60 * 60
MAX_RECEIPT_BYTES = 256 * 1024
_HASH = re.compile(r"^[a-f0-9]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_IDENTITY_KEYS = ("car_id", "track_id", "layout_id", "compound_index", "setup_path", "session_id")
_SPINNER_KEYS = (
    "section",
    "value",
    "min",
    "max",
    "step",
    "unit",
    "range_known",
    "read_only",
    "display_multiplier",
)


class BenchDenied(ValueError):
    """Bench permission is absent or no longer matches the live evidence."""


def _public_reason(exc: Exception) -> str:
    # File locations can identify the hidden oracle receipt. Keep those paths
    # and raw parsing failures out of status/screens; the cause remains local.
    return (
        str(exc) if isinstance(exc, BenchDenied) else "Bench permission or evidence is unavailable"
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _pressure_rows(spinners: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for raw in spinners:
        if not isinstance(raw, dict) or raw.get("section") not in WHEELS.values():
            continue
        normalized = {key: raw.get(key) for key in _SPINNER_KEYS}
        normalized["read_only"] = raw.get("read_only", False)
        normalized["display_multiplier"] = raw.get("display_multiplier", 1)
        if not _finite(normalized["value"]):
            raise BenchDenied("Bench pressure baseline is not finite")
        rows.append(normalized)
    rows.sort(key=lambda row: row["section"])
    if [row["section"] for row in rows] != sorted(WHEELS.values()):
        raise BenchDenied("Bench requires exactly four distinct pressure baselines")
    return rows


def pressure_spinners_sha256(spinners: list[dict[str, Any]]) -> str:
    return canonical_sha256(_pressure_rows(spinners))


def _identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or any(key not in value for key in _IDENTITY_KEYS):
        raise BenchDenied("Bench identity is incomplete")
    result = {key: value[key] for key in _IDENTITY_KEYS}
    if not all(
        isinstance(result[key], str) and result[key]
        for key in ("car_id", "track_id", "setup_path", "session_id")
    ) or not isinstance(result["layout_id"], str):
        raise BenchDenied("Bench identity is incomplete")
    compound = result["compound_index"]
    if not _finite(compound) or compound < 0 or int(compound) != compound:
        raise BenchDenied("Bench compound identity is invalid")
    result["compound_index"] = int(compound)
    return result


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    before = path.stat()
    if before.st_size > MAX_RECEIPT_BYTES:
        raise BenchDenied("Bench receipt exceeds the bounded size")
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BenchDenied("Bench receipt changed during read")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise BenchDenied("Duplicate bench receipt key")
            out[key] = value
        return out

    def invalid_constant(_value):
        raise BenchDenied("Nonfinite bench receipt value")

    data = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise BenchDenied("Bench receipt must be an object")
    return data, hashlib.sha256(raw).hexdigest()


def _process_creation_time(pid: int) -> float:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            *([ctypes.POINTER(wintypes.FILETIME)] * 4),
        ]
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise BenchDenied("Bench owner process is unavailable")
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                raise BenchDenied("Bench owner process creation time is unavailable")
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return ticks / 10_000_000 - 11_644_473_600
        finally:
            kernel.CloseHandle(handle)
    # Linux is useful for hermetic tests; unsupported hosts fail closed.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    start_ticks = int(fields[19])
    boot = next(
        int(line.split()[1])
        for line in Path("/proc/stat").read_text().splitlines()
        if line.startswith("btime ")
    )
    return boot + start_ticks / os.sysconf("SC_CLK_TCK")


def _analysis_admission(archive: dict[str, Any], identity: dict[str, Any]) -> None:
    qualification = qualify_archive(
        archive,
        use="analysis",
        expected_combo=(
            identity["car_id"],
            identity["track_id"],
            identity.get("layout_id") or None,
        ),
    )
    if (
        archive.get("source") != "in_game"
        or not qualification.allowed
        or not qualification.managed
        or qualification.authority != "ai"
    ):
        raise BenchDenied("Bench requires qualified, explicitly attributed native-AI evidence")


class PressureBenchGuard:
    """One explicitly armed case; every boundary repeats admission checks."""

    def __init__(
        self,
        candidate_sha256: str,
        oracle_sha256: str,
        *,
        permit_path: str | Path | None = None,
        lock_path: str | Path | None = None,
        runtime_id: str | None = None,
        clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        owner_reader: Callable[[str | Path], dict[str, Any] | None] = read_rig_session_owner,
        process_create_time: Callable[[int], float] = _process_creation_time,
    ) -> None:
        self.candidate_sha256, self.oracle_sha256 = candidate_sha256, oracle_sha256
        supplied = permit_path if permit_path is not None else os.environ.get(PERMIT_ENV)
        self.permit_path = Path(supplied).resolve() if supplied else None
        self.lock_path = Path(lock_path or default_rig_session_lock_path()).resolve()
        self.runtime_id = runtime_id or secrets.token_hex(24)
        self.clock, self.owner_reader = clock, owner_reader
        self.monotonic_clock = monotonic_clock
        self.process_create_time = process_create_time
        self._active: dict[str, Any] | None = None
        self._peers: list[Any] = []
        self._seen_cases: dict[tuple[str, str], str] = {}
        self._seen_sources: dict[tuple[str, str], str] = {}
        self._reason = "Bench is disarmed"
        self._disarm_epoch = 0

    @property
    def disarm_epoch(self) -> int:
        """Invalidate any admission that yielded before the latest disarm."""
        return self._disarm_epoch

    def status(self) -> dict[str, Any]:
        if self._active is not None:
            try:
                self._check_active_clock()
                _permit, digest = self._permit()
                case, case_hash = _read_json(self._active["case_path"])
                if (
                    digest != self._active["permit_sha256"]
                    or case_hash != self._active["case_sha256"]
                    or not _finite(case.get("expires_at"))
                    or self.clock() >= case["expires_at"]
                ):
                    raise BenchDenied("Bench permission or sealed case changed or expired")
                _oracle, oracle_hash = _read_json(Path(case["oracle_seal"]["path"]))
                if oracle_hash != case["oracle_seal"]["sha256"]:
                    raise BenchDenied("Independent oracle seal changed")
            except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
                self.disarm(_public_reason(exc))
        return {
            "active": self._active is not None,
            "mode": CARD_MODE,
            "runtime_id": self.runtime_id,
            "run_id": self._active["permit"]["run_id"] if self._active else None,
            "case_id": self._active["case"]["case_id"] if self._active else None,
            "reason": self._reason,
        }

    def disarm(self, reason: str = "Bench explicitly disarmed") -> None:
        self._disarm_epoch += 1
        self._active, self._peers, self._reason = None, [], str(reason)[:160]

    def disconnected(self, peer: Any) -> None:
        if any(item is peer for item in self._peers):
            self.disarm("Bench participant disconnected")

    def _check_active_clock(self) -> None:
        active = self._active
        if active is None:
            return
        wall, tick = self.clock(), self.monotonic_clock()
        if (
            not _finite(wall)
            or not _finite(tick)
            or wall < active["last_wall"]
            or tick < active["started_mono"]
            or tick >= active["expires_mono"]
        ):
            raise BenchDenied("Bench clock regressed or monotonic permission deadline expired")
        active["last_wall"] = wall

    def _permit(self) -> tuple[dict[str, Any], str]:
        if self.permit_path is None:
            raise BenchDenied("Bench run permit is not configured")
        permit, digest = _read_json(self.permit_path)
        now = self.clock()
        if (
            type(permit.get("schema_version")) is not int
            or permit.get("schema_version") != 1
            or permit.get("mode") != MODE
            or type(permit.get("issue")) is not int
            or permit.get("issue") != 956
            or permit.get("authority") != AUTHORITY
            or permit.get("allow_native_ai") is not True
            or permit.get("allow_setup_writes") is not True
            or permit.get("runtime_id") != self.runtime_id
            or not _TOKEN.fullmatch(str(permit.get("run_id", "")))
            or permit.get("candidate_sha256") != self.candidate_sha256
            or permit.get("oracle_sha256") != self.oracle_sha256
            or not _HASH.fullmatch(self.candidate_sha256)
            or not _HASH.fullmatch(self.oracle_sha256)
        ):
            raise BenchDenied("Bench run authority or implementation binding is invalid")
        start, end = permit.get("issued_at"), permit.get("expires_at")
        if (
            not _finite(start)
            or not _finite(end)
            or not start <= now < end
            or end - start > MAX_RUN_SECONDS
        ):
            raise BenchDenied("Bench run permit expired or has invalid lifetime")
        if Path(permit.get("rig_lock_path", "")).resolve() != self.lock_path:
            raise BenchDenied("Bench run does not name the canonical rig lock")
        owner, expected = self.owner_reader(self.lock_path), permit.get("rig_owner")
        if not isinstance(expected, dict) or not owner or type(expected.get("pid")) is not int:
            raise BenchDenied("Bench rig ownership is unavailable")
        for key in ("pid", "cwd", "started_at"):
            if not expected.get(key) or owner.get(key) != expected[key]:
                raise BenchDenied("Bench rig owner epoch changed")
        created = permit.get("owner_create_time")
        if not _finite(created) or abs(self.process_create_time(expected["pid"]) - created) > 0.001:
            raise BenchDenied("Bench rig owner process changed")
        return permit, digest

    def _metadata(self, *, readback_only: bool = False) -> dict[str, Any]:
        active = self._active
        if active is None:
            raise BenchDenied("Bench is disarmed")
        return {
            "mode": CARD_MODE,
            "authority": AUTHORITY,
            "run_id": active["permit"]["run_id"],
            "case_id": active["case"]["case_id"],
            "runtime_id": self.runtime_id,
            "permit_sha256": active["permit_sha256"],
            "case_sha256": active["case_sha256"],
            "candidate_sha256": self.candidate_sha256,
            "oracle_sha256": self.oracle_sha256,
            "expires_at": min(active["permit"]["expires_at"], active["case"]["expires_at"]),
            "readback_only": readback_only,
        }

    def arm(
        self,
        case_path: str | Path,
        ctx: dict[str, Any],
        archives: list[dict[str, Any]],
        targets: dict[str, Any],
        peer: Any,
    ) -> dict[str, Any]:
        self.disarm("Enrolling a sealed bench case")
        try:
            permit, permit_hash = self._permit()
            run_root = Path(permit["run_root"]).resolve()
            path = Path(case_path).resolve()
            if not path.is_relative_to(run_root) or path == self.permit_path:
                raise BenchDenied("Bench case receipt must stay in the permitted run root")
            case, case_hash = _read_json(path)
            if (
                type(case.get("schema_version")) is not int
                or case.get("schema_version") != 1
                or case.get("mode") != MODE
                or case.get("run_id") != permit["run_id"]
                or not _TOKEN.fullmatch(str(case.get("case_id", "")))
                or case.get("oracle_sha256") != self.oracle_sha256
            ):
                raise BenchDenied("Bench sealed case binding is invalid")
            key = (permit["run_id"], case["case_id"])
            if key in self._seen_cases and self._seen_cases[key] != case_hash:
                raise BenchDenied("A previously enrolled bench case was changed")
            if not _finite(case.get("expires_at")):
                raise BenchDenied("Bench sealed case expiry is invalid")
            wall, tick = self.clock(), self.monotonic_clock()
            self._active = {
                "permit": permit,
                "permit_sha256": permit_hash,
                "case": case,
                "case_sha256": case_hash,
                "case_path": path,
                "ctx": copy.deepcopy(ctx),
                "last_wall": wall,
                "started_mono": tick,
                "expires_mono": tick + min(permit["expires_at"], case["expires_at"]) - wall,
            }
            result = self.validate(ctx, archives, targets, peer)
            self._seen_cases[key] = case_hash
            for source in case["sources"]:
                self._seen_sources[(permit["run_id"], source["sha256"])] = case["case_id"]
            self._reason = "956 AI BENCH armed for one sealed case"
            return result
        except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
            reason = _public_reason(exc)
            self.disarm(reason)
            raise BenchDenied(reason) from exc

    def validate(
        self,
        ctx: dict[str, Any],
        archives: list[dict[str, Any]],
        targets: dict[str, Any],
        peer: Any,
        *,
        card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            active = self._active
            if active is None:
                raise BenchDenied("Bench is disarmed; explicit arm is required")
            self._check_active_clock()
            permit, permit_hash = self._permit()
            case, case_hash = _read_json(active["case_path"])
            if permit_hash != active["permit_sha256"] or case_hash != active["case_sha256"]:
                raise BenchDenied("Bench permission or sealed case changed")
            now, sealed, expiry = self.clock(), case.get("sealed_at"), case.get("expires_at")
            if (
                not _finite(sealed)
                or not _finite(expiry)
                or not permit["issued_at"] <= sealed <= now < expiry
                or expiry > permit["expires_at"]
            ):
                raise BenchDenied("Bench sealed case expired or predates permission")
            if ctx.get("capture_isolated") is not True:
                raise BenchDenied("Bench native capture isolation is not active")
            if ctx.get("is_in_pit") is not True or ctx.get("reset_allowed") is not True:
                raise BenchDenied("Bench requires the current pit box")
            if _identity(ctx.get("identity")) != _identity(case.get("identity")):
                raise BenchDenied("Bench session, compound or setup scope changed")
            if canonical_sha256(targets) != case.get("targets_sha256"):
                raise BenchDenied("Bench authored targets changed")
            sources = case.get("sources")
            if (
                not isinstance(sources, list)
                or not 1 <= len(sources) <= 2
                or len(sources) != len(archives)
            ):
                raise BenchDenied("Bench source selection is incomplete")
            lap_dir = Path(ctx["lap_dir"]).resolve()
            paths = set()
            source_bindings = []
            for source, archive in zip(sources, archives, strict=True):
                path = Path(source["path"]).resolve()
                if (
                    path.parent != lap_dir
                    or not path.name.startswith("lap_")
                    or path.suffix != ".json"
                    or path in paths
                    or not _HASH.fullmatch(str(source.get("sha256", "")))
                ):
                    raise BenchDenied("Bench sources are not distinct current native archives")
                paths.add(path)
                raw = path.read_bytes()
                if len(raw) > 32 * 1024 * 1024:
                    raise BenchDenied("Bench native source exceeds bounded archive size")
                if hashlib.sha256(raw).hexdigest() != source["sha256"] or canonical_sha256(
                    json.loads(raw)
                ) != canonical_sha256(archive):
                    raise BenchDenied("Bench native source bytes or selection changed")
                seen = self._seen_sources.get((permit["run_id"], source["sha256"]))
                if seen is not None and seen != case["case_id"]:
                    raise BenchDenied("Bench lap evidence was already enrolled in another case")
                _analysis_admission(archive, ctx["identity"])
                source_bindings.append(
                    {
                        "path": path,
                        "sha256": source["sha256"],
                        "canonical_sha256": canonical_sha256(archive),
                        "payload_sha256": payload_sha256(archive),
                        "session_id": archive["session_uuid"],
                        "lap_uuid": archive["lap_uuid"],
                        "lap_n": archive["lap"]["lap_n"],
                    }
                )
            seal = case.get("oracle_seal")
            if not isinstance(seal, dict) or not _HASH.fullmatch(str(seal.get("sha256", ""))):
                raise BenchDenied("Independent oracle seal is unavailable")
            seal_path = Path(seal["path"]).resolve()
            if not seal_path.is_relative_to(Path(permit["run_root"]).resolve()) or seal_path in (
                active["case_path"],
                self.permit_path,
            ):
                raise BenchDenied("Independent oracle seal changed")
            # Read only structural admission bindings. Gold label, directions,
            # measurements and expected decisions are never consulted or exposed.
            oracle, oracle_hash = _read_json(seal_path)
            if (
                oracle_hash != seal["sha256"]
                or type(oracle.get("schema_version")) is not int
                or oracle["schema_version"] != 1
                or oracle.get("mode") != ORACLE_MODE
                or oracle.get("run_id") != case["run_id"]
                or oracle.get("case_id") != case["case_id"]
                or oracle.get("oracle_sha256") != self.oracle_sha256
                or oracle.get("enrollable") is not True
                or oracle.get("authority") != "ai"
            ):
                raise BenchDenied("Independent oracle seal is not admitted for this run and case")
            if (
                canonical_sha256(_identity(oracle.get("identity")))
                != canonical_sha256(_identity(case["identity"]))
                or oracle.get("targets_sha256") != case["targets_sha256"]
                or oracle.get("spinners_sha256") != case["spinners_sha256"]
            ):
                raise BenchDenied("Independent oracle identity, targets or baseline differ")
            oracle_start, oracle_end = oracle.get("sealed_at"), oracle.get("expires_at")
            if (
                not _finite(oracle_start)
                or not _finite(oracle_end)
                or not oracle_start <= sealed <= now < oracle_end
                or expiry > oracle_end
                or not 0 < oracle_end - oracle_start <= TTL_S
            ):
                raise BenchDenied("Independent oracle seal expired or case extends its lifetime")
            oracle_sources = oracle.get("sources")
            if (
                not isinstance(oracle_sources, list)
                or len(oracle_sources) != len(source_bindings)
                or oracle.get("archive_hashes") != [s["canonical_sha256"] for s in source_bindings]
            ):
                raise BenchDenied("Independent oracle source selection differs")
            for attested, current in zip(oracle_sources, source_bindings, strict=True):
                if Path(attested["path"]).resolve() != current["path"] or any(
                    attested.get(key) != current[key]
                    for key in (
                        "sha256",
                        "canonical_sha256",
                        "payload_sha256",
                        "session_id",
                        "lap_uuid",
                        "lap_n",
                    )
                ):
                    raise BenchDenied("Independent oracle source binding differs")
            for key in ("run_manifest_sha256", "rule_sha256"):
                if key in case and case[key] != oracle.get(key):
                    raise BenchDenied("Independent oracle registration or rules differ")
            current_rows = _pressure_rows(ctx["spinners"])
            if card is not None:
                metadata = card.get("bench", {})
                issued = active.get("issued_card")
                if (
                    card.get("mode") != CARD_MODE
                    or card.get("authority") != AUTHORITY
                    or any(
                        metadata.get(key) != value
                        for key, value in self._metadata().items()
                        if key != "readback_only"
                    )
                    or issued is None
                    or card.get("prescription_id") != issued["prescription_id"]
                    or card.get("changes") != issued["changes"]
                ):
                    raise BenchDenied("Bench card belongs to another permission, case or proposal")
            readback_only = (
                card is not None
                and card.get("decision") == "accept"
                and card.get("status") in {"accepted_unverified", "verified_applied"}
            )
            if readback_only:
                baseline = active["baseline"]
                changed = {item["section"]: item for item in card.get("changes", [])}
                for row, original in zip(current_rows, baseline, strict=True):
                    if {k: v for k, v in row.items() if k != "value"} != {
                        k: v for k, v in original.items() if k != "value"
                    }:
                        raise BenchDenied("Bench pressure bounds, units or step changed")
                    allowed = [original["value"]]
                    change = changed.get(row["section"])
                    if change is not None:
                        if change.get("from") != original["value"] or not _finite(change.get("to")):
                            raise BenchDenied("Bench readback targets are malformed")
                        allowed.append(change["to"])
                    if not any(abs(row["value"] - value) <= 0.001 for value in allowed):
                        raise BenchDenied("Bench pressure state left the authorized readback scope")
            elif canonical_sha256(current_rows) != case.get("spinners_sha256"):
                raise BenchDenied("Bench current pressure baseline changed")
            else:
                active["baseline"] = current_rows
            if peer is not None and not any(item is peer for item in self._peers):
                self._peers.append(peer)
            active["ctx"] = copy.deepcopy(ctx)
            return self._metadata(readback_only=readback_only)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
            reason = _public_reason(exc)
            self.disarm(reason)
            raise BenchDenied(reason) from exc

    def build_prescription(
        self,
        archives: list[dict[str, Any]],
        spinners: list[dict[str, Any]],
        *,
        identity: dict[str, Any],
        targets: dict[str, Any],
    ) -> dict[str, Any]:
        if self._active is None:
            raise BenchDenied("Bench is disarmed; explicit arm is required")
        ctx = {**self._active["ctx"], "identity": identity, "spinners": spinners}
        metadata = self.validate(ctx, archives, targets, None)
        card = _evaluate_prescription(
            archives,
            spinners,
            identity=identity,
            targets=targets,
            admit_archive=_analysis_admission,
        )
        card.update(
            mode=CARD_MODE,
            authority=AUTHORITY,
            run_id=metadata["run_id"],
            case_id=metadata["case_id"],
            bench=metadata,
        )
        card["summary"] = "956 AI BENCH: " + card["summary"]
        card["prescription_id"] = canonical_sha256(
            {"bench": metadata, "prescription_id": card["prescription_id"]}
        )[:32]
        self._active["issued_card"] = copy.deepcopy(card)
        return card
