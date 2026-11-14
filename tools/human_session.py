"""Private, durable consumption of the one-session #529 human practice campaign.

Declarations are operator attestations, never verified control or progression evidence.
The immutable archives and canonical attribution ledger remain separate authorities.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import string
import tempfile
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PRACTICE_COMBO = ("ks_porsche_911_gt3_r_2016", "spa", None)
MAX_LAPS = 10
MAX_NATIVE_GAP_S = 0.30
MAX_NATIVE_AGE_S = 5.0
_REASON_CHARACTERS = frozenset(string.ascii_lowercase + string.digits + "_")
_ASSISTANCE_VALUES = {
    "mode": {"live"},
    "abs": {"off", "factory", "on"},
    "tc": {"off", "factory", "on"},
    "gears": {"manual", "automatic"},
    "clutch": {"off", "on"},
    "blip": {"off", "on"},
    "stability": {"off", "on"},
}
_BOOL_DECLARATIONS = {
    "human_steering": True,
    "human_throttle": True,
    "human_brake": True,
    "ai": False,
    "shared": False,
    "harness": False,
}
_LEVEL_FIELDS = {"abs_level", "tc_level", "stability_level"}


class HumanSessionError(ValueError):
    """A stable, fail-closed campaign error code."""


def campaign_path(root: str | Path) -> Path:
    return Path(root) / "practice-session-529.json"


def _process_identity() -> dict[str, Any]:
    import psutil

    return {"pid": os.getpid(), "created": psutil.Process().create_time()}


def _owner_alive(owner: Any) -> bool | None:
    import psutil

    if not isinstance(owner, dict) or type(owner.get("pid")) is not int:
        return None
    try:
        return psutil.Process(owner["pid"]).create_time() == owner.get("created")
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, OSError):
        return None


def _digest(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HumanSessionError("campaign_value_invalid") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _declaration(driver_id: Any, assistance: Any) -> dict[str, Any]:
    if (
        not isinstance(driver_id, str)
        or not driver_id.strip()
        or len(driver_id) > 128
        or driver_id.strip().lower() in {"unknown", "unconfirmed", "unspecified", "?", "n/a"}
    ):
        raise HumanSessionError("driver_declaration_required")
    if not isinstance(assistance, Mapping):
        raise HumanSessionError("assistance_declaration_required")
    if set(assistance) != set(_ASSISTANCE_VALUES) | set(_BOOL_DECLARATIONS) | _LEVEL_FIELDS:
        raise HumanSessionError("assistance_declaration_incomplete")
    if any(assistance[key] is not value for key, value in _BOOL_DECLARATIONS.items()):
        raise HumanSessionError("exclusive_human_control_not_attested")
    if any(
        not isinstance(assistance[key], str) or assistance[key] not in values
        for key, values in _ASSISTANCE_VALUES.items()
    ):
        raise HumanSessionError("assistance_declaration_unknown")
    if any(
        not isinstance(assistance[key], str)
        or not assistance[key].strip()
        or len(assistance[key]) > 128
        or assistance[key].strip().lower() in {"unknown", "unspecified", "?", "n/a"}
        for key in _LEVEL_FIELDS
    ):
        raise HumanSessionError("assistance_level_required")
    return {"driver_id": driver_id.strip(), "assistance": dict(assistance)}


def _read(path: Path) -> dict[str, Any]:
    try:
        from tools.lap_qualification import _stable_bytes

        raw = _stable_bytes(path)
        if len(raw) > 4 * 1024 * 1024:
            raise HumanSessionError("campaign_state_invalid")
        state = json.loads(raw)
        _validate_state(state)
        return state
    except HumanSessionError:
        raise
    except Exception as exc:
        raise HumanSessionError("campaign_state_unavailable") from exc


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _state_digest(state: Mapping[str, Any]) -> str:
    return _digest({key: value for key, value in state.items() if key != "state_sha256"})


def _validate_state(state: Any) -> None:
    from tools.lap_qualification import _identity_reasons

    try:
        if (
            not isinstance(state, dict)
            or type(state.get("schema_version")) is not int
            or state.get("schema_version") != 1
            or state.get("campaign") != "issue529_rex03"
            or type(state.get("max_laps")) is not int
            or state.get("max_laps") != MAX_LAPS
            or state.get("combo") != list(PRACTICE_COMBO)
            or state.get("phase") not in {"prepared", "active", "closed", "aborted"}
            or not isinstance(state.get("permit_id"), str)
            or not state["permit_id"]
            or type(state.get("attempted_laps")) is not int
            or not 0 <= state["attempted_laps"] <= MAX_LAPS
            or not isinstance(state.get("windows"), dict)
            or not isinstance(state.get("archives"), dict)
            or len(state["windows"]) > MAX_LAPS + 1
            or len(state["archives"]) > MAX_LAPS
            or not isinstance(state.get("reason"), str)
            or not state["reason"]
            or any(char not in _REASON_CHARACTERS for char in state["reason"])
            or _declaration(**state["declaration"]) != state["declaration"]
            or _digest(state["declaration"]) != state.get("declaration_sha256")
            or type(state.get("revision")) is not int
            or state["revision"] < 1
            or not _hash(state.get("state_sha256"))
            or state["state_sha256"] != _state_digest(state)
            or not _number(state.get("created_at"))
            or state["created_at"] <= 0
            or type(state.get("end_confirmed")) is not bool
            or type(state.get("end_conflict", False)) is not bool
            or type(state.get("capture_sealed", False)) is not bool
            or (
                state.get("voice_bank") is not None
                and (not isinstance(state["voice_bank"], str) or not state["voice_bank"].strip())
            )
        ):
            raise HumanSessionError("campaign_state_invalid")
        native, windows, archives = state.get("native"), state["windows"], state["archives"]
        current = state.get("current_ordinal")
        if native is None:
            if (
                state["phase"] == "active"
                or state["attempted_laps"]
                or windows
                or archives
                or current is not None
                or any(
                    key in state
                    for key in ("owner", "owner_process", "archive_root", "preexisting_paths")
                )
            ):
                raise HumanSessionError("campaign_state_invalid")
        else:
            if (
                not isinstance(native, dict)
                or native.get("car_id") != PRACTICE_COMBO[0]
                or native.get("track_id") != PRACTICE_COMBO[1]
                or not isinstance(native.get("session_uuid"), str)
                or not native["session_uuid"].strip()
                or type(native.get("session_index")) is not int
                or native["session_index"] < 0
                or native.get("is_live") is not True
                or native.get("is_ai") is not False
                or native.get("is_replay") is not False
                or type(native.get("archive_lap_n")) is not int
                or native["archive_lap_n"] != 1
                or not _number(native.get("lap_time_ms"))
                or not 0 <= native["lap_time_ms"] <= 250
            ):
                raise HumanSessionError("campaign_state_invalid")
            owner = state.get("owner_process")
            if (
                not isinstance(state.get("owner"), str)
                or len(state["owner"]) != 32
                or not isinstance(owner, dict)
                or type(owner.get("pid")) is not int
                or owner["pid"] <= 0
                or not _number(owner.get("created"))
                or owner["created"] <= 0
            ):
                raise HumanSessionError("campaign_state_invalid")
            root = state.get("archive_root")
            previous = state.get("preexisting_paths")
            if (
                not isinstance(root, str)
                or not Path(root).is_absolute()
                or str(Path(root).resolve()) != root
                or not isinstance(previous, list)
                or any(not isinstance(item, str) for item in previous)
                or len(set(previous)) != len(previous)
            ):
                raise HumanSessionError("campaign_state_invalid")
            if state["phase"] == "prepared":
                raise HumanSessionError("campaign_state_invalid")
        if current is None:
            if windows or archives or (state["phase"] == "active" and state["attempted_laps"] != 0):
                raise HumanSessionError("campaign_state_invalid")
        else:
            if (
                type(current) is not int
                or not 1 <= current <= MAX_LAPS + 1
                or set(windows) != {str(value) for value in range(1, current + 1)}
                or state["attempted_laps"] < min(current, MAX_LAPS)
                or (
                    state["phase"] == "active" and state["attempted_laps"] != min(current, MAX_LAPS)
                )
            ):
                raise HumanSessionError("campaign_state_invalid")
            for key, window in windows.items():
                if (
                    not isinstance(window, dict)
                    or any(
                        not _number(window.get(name))
                        for name in ("start_tick", "last_tick", "last_elapsed_ms", "last_spline")
                    )
                    or window["start_tick"] > window["last_tick"]
                    or window["last_elapsed_ms"] < 0
                    or not 0 <= window["last_spline"] <= 1
                    or type(window.get("ticks")) is not int
                    or window["ticks"] < 1
                    or type(window.get("closed")) is not bool
                    or window["closed"] is not (int(key) < current)
                ):
                    raise HumanSessionError("campaign_state_invalid")
                if window["closed"] and (
                    not _number(window.get("end_tick"))
                    or not 0 <= window["end_tick"] - window["last_tick"] <= MAX_NATIVE_GAP_S
                    or window["end_tick"] != windows[str(int(key) + 1)]["start_tick"]
                ):
                    raise HumanSessionError("campaign_state_invalid")
        lap_ids = set()
        for key, receipt in archives.items():
            if (
                not isinstance(receipt, dict)
                or key not in windows
                or not windows[key]["closed"]
                or not key.isdigit()
                or not 1 <= int(key) <= MAX_LAPS
            ):
                raise HumanSessionError("campaign_state_invalid")
            identity = receipt.get("identity")
            if (
                not isinstance(identity, dict)
                or _identity_reasons(identity)
                or identity.get("lap_n") != int(key)
                or identity.get("session_uuid") != native["session_uuid"]
                or (identity.get("car_id"), identity.get("track_id"), identity.get("layout"))
                != PRACTICE_COMBO
                or identity["lap_uuid"] in lap_ids
            ):
                raise HumanSessionError("campaign_state_invalid")
            lap_ids.add(identity["lap_uuid"])
            target = receipt.get("path")
            if (
                not isinstance(target, str)
                or Path(target).parent != Path(state["archive_root"])
                or not Path(target).name.startswith("lap_")
                or Path(target).suffix != ".json"
                or target in state["preexisting_paths"]
                or receipt.get("permit_id") != state["permit_id"]
                or receipt.get("declaration_sha256") != state["declaration_sha256"]
                or receipt.get("native_window_sha256") != _digest(windows[key])
                or type(receipt.get("reference_eligible")) is not bool
                or receipt["reference_eligible"] != (int(key) <= 2)
                or any(
                    not _hash(receipt.get(name))
                    for name in (
                        "payload_sha256",
                        "source_sha256",
                        "declaration_sha256",
                        "native_window_sha256",
                    )
                )
            ):
                raise HumanSessionError("campaign_state_invalid")
        if state.get("capture_sealed") and (
            state["phase"] not in {"closed", "aborted"}
            or current != 11
            or state["attempted_laps"] != 10
            or set(archives) != {str(value) for value in range(1, 11)}
        ):
            raise HumanSessionError("campaign_state_invalid")
        end = state.get("end_declaration")
        if end is not None:
            if state["phase"] not in {"closed", "aborted"} or (
                end != {"valid": False} and _declaration(**end) != end
            ):
                raise HumanSessionError("campaign_state_invalid")
        if state["end_confirmed"] and (
            native is None or end != state["declaration"] or state.get("end_conflict")
        ):
            raise HumanSessionError("campaign_state_invalid")
        _digest(state)
    except HumanSessionError:
        raise
    except Exception as exc:
        raise HumanSessionError("campaign_state_invalid") from exc


@contextmanager
def _locked(path: Path, *, wait_s: float = 0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    deadline = time.perf_counter() + wait_s
    attempts = max(1, int(wait_s / 0.01) + 2)
    for attempt in range(attempts):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as exc:
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or attempt == attempts - 1:
                raise HumanSessionError("campaign_writer_busy") from exc
            time.sleep(min(0.01, remaining))
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _write(path: Path, state: dict[str, Any]) -> None:
    state["revision"] = state.get("revision", 0) + 1
    state["state_sha256"] = _state_digest(state)
    _validate_state(state)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as out:
            name = out.name
            json.dump(state, out, sort_keys=True, indent=2, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def _public(state: dict[str, Any], *, private: bool) -> dict[str, Any]:
    result = {
        "configured": True,
        "active": state["phase"] == "active",
        "phase": state["phase"],
        "reason": state["reason"],
    }
    if private:
        result.update(
            **copy.deepcopy(state["declaration"]),
            combo=list(PRACTICE_COMBO),
            attempted_laps=state["attempted_laps"],
            remaining_laps=MAX_LAPS - state["attempted_laps"],
            session_uuid=(state.get("native") or {}).get("session_uuid"),
            permit_id=state["permit_id"],
            end_confirmed=state.get("end_confirmed", False),
            end_recorded="end_declaration" in state,
            accepted_laps=copy.deepcopy(list(state["archives"].values())),
            voice_bank=state.get("voice_bank"),
        )
    return result


class HumanSessionPermit:
    def __init__(self, path: Path, state: dict[str, Any]) -> None:
        self.path, self._state = path, state
        self._owner = uuid.uuid4().hex
        self._last_native_seen: float | None = None
        self._live_windows: dict[str, Any] = {}
        self._live_current: int | None = None
        self._revision = state["revision"]
        self._checksum = state["state_sha256"]
        self._attempt_watermark = state["attempted_laps"]
        self._archive_watermark = copy.deepcopy(state["archives"])
        self._closed_windows = {
            key: copy.deepcopy(value) for key, value in state["windows"].items() if value["closed"]
        }
        self._immutable = {
            key: copy.deepcopy(state.get(key))
            for key in (
                "permit_id",
                "declaration",
                "declaration_sha256",
                "created_at",
                "combo",
                "voice_bank",
            )
        }
        self._admission = (
            self._admission_identity(state) if state.get("native") is not None else None
        )
        self._terminal_seen = state["phase"] in {"closed", "aborted"}
        self._revocation_reason: str | None = None
        self._revocation_pending = False

    @staticmethod
    def _admission_identity(state: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(state.get(key))
            for key in ("native", "owner", "owner_process", "archive_root", "preexisting_paths")
        }

    def _adopt(self, state: dict[str, Any]) -> None:
        if (
            state["revision"] < self._revision
            or (state["revision"] == self._revision and state["state_sha256"] != self._checksum)
            or state["attempted_laps"] < self._attempt_watermark
        ):
            raise HumanSessionError("campaign_state_rollback")
        if any(state.get(key) != value for key, value in self._immutable.items()) or (
            self._admission is not None and self._admission_identity(state) != self._admission
        ):
            raise HumanSessionError("campaign_identity_changed")
        if (
            self._terminal_seen
            and state["phase"] not in {"closed", "aborted"}
            or any(
                state["archives"].get(key) != value
                for key, value in self._archive_watermark.items()
            )
            or any(
                state["windows"].get(key) != value for key, value in self._closed_windows.items()
            )
        ):
            raise HumanSessionError("campaign_state_rollback")
        self._revision, self._checksum = state["revision"], state["state_sha256"]
        self._attempt_watermark = state["attempted_laps"]
        self._archive_watermark = copy.deepcopy(state["archives"])
        self._closed_windows = {
            key: copy.deepcopy(value) for key, value in state["windows"].items() if value["closed"]
        }
        if state.get("native") is not None:
            self._admission = self._admission_identity(state)
        self._terminal_seen = self._terminal_seen or state["phase"] in {"closed", "aborted"}
        self._state = state

    @classmethod
    def prepare(
        cls,
        path: str | Path,
        *,
        driver_id: str,
        assistance: Mapping[str, Any],
        combo: tuple[str, str, str | None] = PRACTICE_COMBO,
        voice_bank: str | None = None,
    ) -> HumanSessionPermit:
        if tuple(combo) != PRACTICE_COMBO:
            raise HumanSessionError("campaign_combo_mismatch")
        declaration = _declaration(driver_id, assistance)
        if voice_bank is not None and (not isinstance(voice_bank, str) or not voice_bank.strip()):
            raise HumanSessionError("voice_bank_invalid")
        target = Path(path)
        state = {
            "schema_version": 1,
            "campaign": "issue529_rex03",
            "permit_id": uuid.uuid4().hex,
            "max_laps": MAX_LAPS,
            "combo": list(PRACTICE_COMBO),
            "declaration": declaration,
            "declaration_sha256": _digest(declaration),
            "created_at": time.time(),
            "phase": "prepared",
            "reason": "awaiting_native_session",
            "attempted_laps": 0,
            "windows": {},
            "archives": {},
            "end_confirmed": False,
            "voice_bank": voice_bank,
        }
        with _locked(target):
            if target.exists():
                raise HumanSessionError("campaign_already_exists")
            _write(target, state)
        return cls(target, state)

    @classmethod
    def load(cls, path: str | Path) -> HumanSessionPermit:
        """Child-startup load: a previously admitted campaign can never resume."""
        target = Path(path)
        with _locked(target):
            state = _read(target)
            if state.get("native") is not None or state["phase"] == "active":
                if state["phase"] not in {"closed", "aborted"}:
                    alive = _owner_alive(state.get("owner_process"))
                    if alive is not False:
                        raise HumanSessionError(
                            "campaign_in_use" if alive else "campaign_owner_unavailable"
                        )
                    state.update(phase="aborted", reason="campaign_process_restarted")
                    _write(target, state)
        return cls(target, state)

    @classmethod
    def read_status(cls, path: str | Path, *, private: bool = False) -> dict[str, Any]:
        target = Path(path)
        if not target.exists():
            return {
                "configured": False,
                "active": False,
                "phase": "unavailable",
                "reason": "not_configured",
            }
        try:
            return _public(_read(target), private=private)
        except HumanSessionError as exc:
            return {"configured": True, "active": False, "phase": "unavailable", "reason": str(exc)}

    def reload(self) -> HumanSessionPermit:
        state = _read(self.path)
        if state["permit_id"] != self._state["permit_id"]:
            raise HumanSessionError("campaign_identity_changed")
        self._adopt(state)
        return self

    def status(self, private: bool = False) -> dict[str, Any]:
        if self._revocation_pending:
            result = _public(self._state, private=private)
            result.update(active=False, phase="aborted", reason=self._revocation_reason)
            if private:
                result["revocation_pending"] = True
            return result
        self.reload()
        return _public(self._state, private=private)

    def _active(self, state: dict[str, Any]) -> None:
        if self._revocation_reason is not None:
            raise HumanSessionError("campaign_not_active")
        self._adopt(state)
        if state["phase"] != "active" or state.get("owner") != self._owner:
            raise HumanSessionError("campaign_not_active")

    def admit(
        self, native_identity: Mapping[str, Any], *, archive_root: str | Path | None = None
    ) -> dict[str, Any]:
        from tools.lap_qualification import archive_combo, default_attribution_path

        native = dict(native_identity)
        combo = archive_combo(
            {"car": {"id": native.get("car_id")}, "track": {"id": native.get("track_id")}}
        )
        if combo != PRACTICE_COMBO:
            raise HumanSessionError("native_combo_mismatch")
        if not isinstance(native.get("session_uuid"), str) or not native["session_uuid"].strip():
            raise HumanSessionError("native_session_identity_unavailable")
        if type(native.get("session_index")) is not int or native["session_index"] < 0:
            raise HumanSessionError("native_session_identity_unavailable")
        if (
            native.get("is_live") is not True
            or native.get("is_ai") is not False
            or native.get("is_replay") is not False
        ):
            raise HumanSessionError("native_control_unproved")
        if native.get("archive_lap_n") != 1 or type(native.get("archive_lap_n")) is not int:
            raise HumanSessionError("native_session_not_prospective")
        elapsed = native.get("lap_time_ms")
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or not 0 <= elapsed <= 250
        ):
            raise HumanSessionError("native_session_not_prospective")
        root = (
            Path(archive_root)
            if archive_root is not None
            else default_attribution_path().parent / "laps"
        ).resolve()
        with _locked(self.path):
            state = _read(self.path)
            self._adopt(state)
            if (
                state["permit_id"] != self._state["permit_id"]
                or state["phase"] != "prepared"
                or state.get("native") is not None
            ):
                raise HumanSessionError("campaign_already_consumed")
            state.update(
                native=native,
                owner=self._owner,
                owner_process=_process_identity(),
                archive_root=str(root),
                preexisting_paths=sorted(str(path.resolve()) for path in root.glob("lap_*.json")),
                phase="active",
                reason="operator_attestation_only",
            )
            _write(self.path, state)
            self._adopt(state)
        self._last_native_seen = time.monotonic()
        return self.status()

    def observe_native(
        self, payload: Mapping[str, Any], *, now: float | None = None
    ) -> dict[str, Any]:
        stamp = time.monotonic() if now is None else now
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
        ):
            raise HumanSessionError("native_clock_invalid")
        with _locked(self.path):
            state = _read(self.path)
            self._active(state)
            # Intra-lap samples are owned memory. Only ordinal transitions/revocation
            # need durable writes; loss of this handle permanently consumes the study.
            state["windows"] = copy.deepcopy(self._live_windows)
            if self._live_current is not None:
                state["current_ordinal"] = self._live_current
            ordinal = payload.get("archive_lap_n")
            if type(ordinal) is int and ordinal > 0:
                state["attempted_laps"] = max(state["attempted_laps"], min(MAX_LAPS, ordinal))
            reason = ""
            if (
                payload.get("is_live") is not True
                or payload.get("is_ai") is not False
                or payload.get("is_replay") is not False
            ):
                reason = "native_control_unproved"
            elif payload.get("archive_session_uuid") != state["native"]["session_uuid"]:
                reason = "native_session_changed"
            elif type(ordinal) is not int or not 1 <= ordinal <= MAX_LAPS + 1:
                reason = "lap_budget_exhausted"
            elapsed, spline = payload.get("lap_time_ms"), payload.get("spline")
            if not reason and any(
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                for value in (elapsed, spline)
            ):
                reason = "native_lap_context_unavailable"
            current = state.get("current_ordinal")
            if not reason and (
                current is None
                and ordinal != 1
                or current is not None
                and ordinal not in {current, current + 1}
            ):
                reason = "native_lap_context_gap"
            if not reason and (not 0 <= spline <= 1 or elapsed < 0):
                reason = "native_lap_context_unavailable"
            if not reason:
                if current != ordinal:
                    if elapsed > 250:
                        reason = "native_lap_start_missing"
                    if current is not None:
                        previous = state["windows"][str(current)]
                        if not 0 <= stamp - previous["last_tick"] <= MAX_NATIVE_GAP_S:
                            reason = "native_lap_trace_gap"
                        if not reason:
                            previous["closed"] = True
                            previous["end_tick"] = stamp
                    if not reason:
                        state["windows"][str(ordinal)] = {
                            "start_tick": stamp,
                            "last_tick": stamp,
                            "last_elapsed_ms": elapsed,
                            "last_spline": spline,
                            "ticks": 1,
                            "closed": False,
                        }
                        state["current_ordinal"] = ordinal
                else:
                    window = state["windows"][str(ordinal)]
                    if (
                        not 0 < stamp - window["last_tick"] <= MAX_NATIVE_GAP_S
                        or elapsed < window["last_elapsed_ms"]
                        or spline < window["last_spline"]
                        or abs(
                            elapsed
                            - window["last_elapsed_ms"]
                            - (stamp - window["last_tick"]) * 1000
                        )
                        > 250
                    ):
                        reason = "native_lap_trace_gap"
                    if not reason:
                        window.update(
                            last_tick=stamp,
                            last_elapsed_ms=elapsed,
                            last_spline=spline,
                            ticks=window["ticks"] + 1,
                        )
            if reason:
                state.update(phase="aborted", reason=reason)
            elif ordinal == MAX_LAPS + 1:
                state["reason"] = "lap_budget_exhausted"
            if reason or current != ordinal:
                _write(self.path, state)
            self._live_windows = copy.deepcopy(state["windows"])
            self._live_current = state.get("current_ordinal")
            self._adopt(state)
        self._last_native_seen = time.monotonic()
        return self.status()

    def accept_archive(
        self, path: str | Path, *, expected_combo: tuple[str, str, str | None] = PRACTICE_COMBO
    ) -> dict[str, Any]:
        from tools.lap_qualification import (
            _stable_bytes,
            archive_combo,
            archive_identity,
            payload_sha256,
        )

        self.reload()
        self._active(self._state)
        target = Path(path).resolve()
        root = Path(self._state["archive_root"])
        if target.parent != root or not target.name.startswith("lap_") or target.suffix != ".json":
            raise HumanSessionError("archive_outside_native_root")
        if str(target) in self._state.get("preexisting_paths", []):
            raise HumanSessionError("archive_predates_admission")
        raw = _stable_bytes(target)
        if len(raw) > 32 * 1024 * 1024:
            raise HumanSessionError("archive_size_exceeded")
        try:
            record = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise HumanSessionError("archive_invalid") from exc
        if (
            not isinstance(record, dict)
            or record.get("source") != "in_game"
            or record.get("import_format") is not None
        ):
            raise HumanSessionError("native_archive_required")
        if tuple(expected_combo) != PRACTICE_COMBO or archive_combo(record) != PRACTICE_COMBO:
            raise HumanSessionError("archive_combo_mismatch")
        identity = archive_identity(record)
        ordinal = identity["lap_n"]
        if (
            type(ordinal) is not int
            or not 1 <= ordinal <= MAX_LAPS
            or identity["session_uuid"] != self._state["native"]["session_uuid"]
        ):
            raise HumanSessionError("archive_session_mismatch")
        digest, source_digest = payload_sha256(record), hashlib.sha256(raw).hexdigest()
        with _locked(self.path):
            state = _read(self.path)
            self._active(state)
            old = state["archives"].get(str(ordinal))
            if old is not None:
                if (
                    old["identity"] != identity
                    or old["payload_sha256"] != digest
                    or old["source_sha256"] != source_digest
                    or old["path"] != str(target)
                ):
                    raise HumanSessionError("conflicting_native_archive")
                return copy.deepcopy(old)
            if state.get("current_ordinal") != ordinal + 1:
                raise HumanSessionError("archive_not_fresh_completion")
            window = state["windows"].get(str(ordinal))
            if not window or not window["closed"] or window["ticks"] < 2:
                raise HumanSessionError("native_lap_window_incomplete")
            lap_ms = identity["lap_ms"]
            if (
                isinstance(lap_ms, bool)
                or not isinstance(lap_ms, (int, float))
                or not math.isfinite(lap_ms)
                or abs(lap_ms - window["last_elapsed_ms"]) > 500
            ):
                raise HumanSessionError("native_lap_time_mismatch")
            if not isinstance(identity["lap_uuid"], str) or not identity["lap_uuid"]:
                raise HumanSessionError("archive_identity_incomplete")
            if any(
                item["identity"]["lap_uuid"] == identity["lap_uuid"]
                for item in state["archives"].values()
            ):
                raise HumanSessionError("duplicate_native_archive")
            receipt = {
                "identity": identity,
                "payload_sha256": digest,
                "source_sha256": source_digest,
                "path": str(target),
                "permit_id": state["permit_id"],
                "declaration_sha256": state["declaration_sha256"],
                "native_window_sha256": _digest(window),
                "reference_eligible": ordinal <= 2,
            }
            if raw != _stable_bytes(target):
                raise HumanSessionError("archive_changed_during_acceptance")
            state["archives"][str(ordinal)] = receipt
            _write(self.path, state)
            self._adopt(state)
        return copy.deepcopy(receipt)

    def qualification_context(
        self, record: Mapping[str, Any], *, expected_combo: tuple[str, str, str | None]
    ) -> dict[str, Any]:
        from tools.lap_qualification import (
            _stable_bytes,
            archive_combo,
            archive_identity,
            payload_sha256,
        )

        self.reload()
        self._active(self._state)
        if (
            self._last_native_seen is None
            or time.monotonic() - self._last_native_seen > MAX_NATIVE_AGE_S
        ):
            self.revoke("native_session_stale")
            raise HumanSessionError("native_session_stale")
        if tuple(expected_combo) != PRACTICE_COMBO or archive_combo(record) != PRACTICE_COMBO:
            raise HumanSessionError("archive_combo_mismatch")
        identity = archive_identity(record)
        receipt = self._state["archives"].get(str(identity["lap_n"]))
        if (
            not receipt
            or receipt["identity"] != identity
            or receipt["payload_sha256"] != payload_sha256(record)
        ):
            raise HumanSessionError("archive_not_accepted")
        if (
            hashlib.sha256(_stable_bytes(Path(receipt["path"]))).hexdigest()
            != receipt["source_sha256"]
        ):
            raise HumanSessionError("attribution_source_hash_mismatch")
        return copy.deepcopy({key: value for key, value in receipt.items() if key != "path"})

    @contextmanager
    def _registration_guard(
        self, record: Mapping[str, Any], *, expected_combo: tuple[str, str, str | None]
    ):
        # Close/revoke cannot race publication of a new attribution. Neither path
        # holds the canonical ledger lock while acquiring this private state lock.
        try:
            with _locked(self.path):
                self.reload()
                self._active(self._state)
                if (
                    self._last_native_seen is None
                    or time.monotonic() - self._last_native_seen > MAX_NATIVE_AGE_S
                ):
                    raise HumanSessionError("native_session_stale")
                self.qualification_context(record, expected_combo=expected_combo)
                yield
        finally:
            # The actor's stop latch applies immediately, even while this worker
            # owns the file lock. Settle that same campaign after releasing it.
            if self._revocation_pending:
                self._flush_revocation()

    def current_qualification(
        self, record: Mapping[str, Any], *, use: str, expected_combo: tuple[str, str, str | None]
    ):
        from tools.lap_qualification import qualify_practice_archive

        return qualify_practice_archive(record, use=use, permit=self, expected_combo=expected_combo)

    def revoke(self, reason: str) -> dict[str, Any]:
        _validate_reason(reason)
        if self._revocation_reason is None:
            self._revocation_reason = reason
        self._revocation_pending = True
        try:
            return self._flush_revocation(wait_s=0)
        except HumanSessionError as exc:
            if str(exc) != "campaign_writer_busy":
                raise
            return self.status(private=True)

    def _flush_revocation(self, *, wait_s: float = 0.25) -> dict[str, Any]:
        result = _revoke_campaign(self.path, self._revocation_reason, wait_s=wait_s)
        self._revocation_pending = False
        self.reload()
        return result

    def close(self, end_declaration: Mapping[str, Any]) -> dict[str, Any]:
        result = close_campaign(self.path, end_declaration)
        self.reload()
        return result

    def seal_capture(self) -> dict[str, Any]:
        """Finish all ten captured laps; the parked driver may declare the end later."""
        with _locked(self.path):
            state = _read(self.path)
            self._active(state)
            if state["attempted_laps"] != MAX_LAPS or set(state["archives"]) != {
                str(value) for value in range(1, MAX_LAPS + 1)
            }:
                raise HumanSessionError("campaign_capture_incomplete")
            state.update(phase="closed", reason="awaiting_end_declaration", capture_sealed=True)
            _write(self.path, state)
            self._adopt(state)
        return self.status(private=True)


def _validate_reason(reason: Any) -> None:
    if (
        not isinstance(reason, str)
        or not reason
        or any(char not in _REASON_CHARACTERS for char in reason)
    ):
        raise HumanSessionError("campaign_reason_invalid")


def revoke_campaign(path: str | Path, reason: str) -> dict[str, Any]:
    return _revoke_campaign(path, reason, wait_s=0.25)


def _revoke_campaign(path: str | Path, reason: str, *, wait_s: float) -> dict[str, Any]:
    _validate_reason(reason)
    target = Path(path)
    with _locked(target, wait_s=wait_s):
        state = _read(target)
        if (
            state["phase"] not in {"closed", "aborted"}
            or state["reason"] == "awaiting_end_declaration"
        ):
            state.update(phase="aborted", reason=reason, end_confirmed=False)
            _write(target, state)
    return _public(state, private=True)


def close_campaign(path: str | Path, end_declaration: Mapping[str, Any]) -> dict[str, Any]:
    target = Path(path)
    with _locked(target, wait_s=0.25):
        state = _read(target)
        try:
            declaration = _declaration(**dict(end_declaration))
            matched = declaration == state["declaration"] and state.get("native") is not None
        except (TypeError, HumanSessionError):
            declaration = {"valid": False}
            matched = False
        if "end_declaration" in state:
            if declaration != state["end_declaration"]:
                state.update(end_confirmed=False, end_conflict=True)
                _write(target, state)
            return _public(state, private=True)
        if (
            state["phase"] not in {"aborted", "closed"}
            or state["reason"] == "awaiting_end_declaration"
        ):
            state.update(
                phase="closed",
                reason="end_declaration_matched" if matched else "end_declaration_mismatch",
            )
        state["end_confirmed"] = matched
        state["end_declaration"] = declaration
        _write(target, state)
    return _public(state, private=True)
