"""Cross-process ownership guard for the single physical Assetto Corsa rig.

Assetto Corsa and Content Manager are machine-global resources: two ``auto_drive`` processes from
different git worktrees cannot safely share them.  A repository-local lock is insufficient because
each worktree has its own ``.scratch`` directory, so the lock lives under the product's LocalAppData
folder and uses an OS file lock that is released automatically when the owner process exits.
"""

from __future__ import annotations

import errno
import json
import math
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO

MAX_OWNER_BYTES = 4096


def default_rig_session_lock_path(*, local_app_data: str | Path | None = None) -> Path:
    """Return the cross-worktree lock path in the app's per-user data folder."""

    base = local_app_data or os.environ.get("LOCALAPPDATA")
    if base is None:
        # Off-rig fallback for development hosts. Production is Windows and always supplies
        # LOCALAPPDATA; tests pass an explicit temporary directory.
        base = Path.home() / ".local" / "state"
    return Path(base) / "AC Copilot Trainer" / "Harness" / "rig-session.lock"


@dataclass(frozen=True)
class RigSessionOwner:
    """Human-readable metadata stored behind the lock byte for busy diagnostics."""

    pid: int
    cwd: str
    car: str | None = None
    track: str | None = None
    started_at: str | None = None
    session_kind: str | None = None
    phase: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "cwd": self.cwd,
            "car": self.car,
            "track": self.track,
            "started_at": self.started_at,
            "session_kind": self.session_kind,
            "phase": self.phase,
        }


class RigSessionBusy(RuntimeError):
    """Raised when another process owns the single-rig session lock."""

    def __init__(self, path: Path, owner: dict[str, Any] | None = None) -> None:
        self.path = path
        self.owner = owner or {}
        detail = ", ".join(
            f"{key}={self.owner[key]}"
            for key in ("pid", "car", "track", "cwd", "started_at")
            if self.owner.get(key) not in (None, "")
        )
        super().__init__(
            f"another harness owns the rig lock at {path}" + (f" ({detail})" if detail else "")
        )


class RigOwnerMismatch(RuntimeError):
    """Raised when a delegated run's expected owner does not hold the canonical lock."""


class RigSessionLock:
    """Non-reentrant cross-process file lock with stale-safe owner metadata."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner: RigSessionOwner,
        timeout: float = 0.0,
        poll_interval: float = 0.1,
    ) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("rig lock timeout must be finite and >= 0")
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("rig lock poll interval must be finite and > 0")
        self.path = Path(path)
        self.owner = owner
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._file: BinaryIO | None = None

    def __enter__(self) -> RigSessionLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.release()

    def acquire(self) -> None:
        if self._file is not None:
            raise RuntimeError("rig session lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            lock_file = os.fdopen(descriptor, "r+b")
        except BaseException:
            os.close(descriptor)
            raise
        if lock_file.seek(0, os.SEEK_END) == 0:
            lock_file.write(b"\0")
            lock_file.flush()

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock_byte(lock_file)
                break
            except OSError as exc:
                if not self._is_lock_contention(exc):
                    lock_file.close()
                    raise
                if time.monotonic() >= deadline:
                    owner = self._read_owner(lock_file)
                    lock_file.close()
                    raise RigSessionBusy(self.path, owner) from None
                time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))

        self._file = lock_file
        try:
            self._write_owner()
        except BaseException as exc:
            # Metadata publication is part of acquisition. Roll back the authoritative byte lock
            # on every abnormal exit so one disk/sharing error cannot wedge the physical rig until
            # this process happens to terminate.
            self._file = None
            try:
                self._unlock_byte(lock_file)
            except OSError as cleanup_exc:
                exc.add_note(f"additional rig-lock rollback failure: {cleanup_exc}")
            try:
                lock_file.close()
            except OSError as cleanup_exc:
                exc.add_note(f"additional rig-lock close failure: {cleanup_exc}")
            raise

    def set_phase(self, phase: str) -> None:
        """Publish a durable owner phase while retaining the authoritative byte lock."""
        if not phase.strip():
            raise ValueError("rig session phase must not be empty")
        if self._file is None:
            raise RuntimeError("rig session lock is not acquired")
        self.owner = replace(self.owner, phase=phase)
        self._write_owner()

    def _write_owner(self) -> None:
        lock_file = self._file
        if lock_file is None:
            raise RuntimeError("rig session lock is not acquired")
        payload = json.dumps(self.owner.to_dict(), sort_keys=True).encode("utf-8")
        if len(payload) > MAX_OWNER_BYTES:
            raise ValueError(f"rig owner metadata exceeds {MAX_OWNER_BYTES} bytes")
        lock_file.seek(0, os.SEEK_END)
        previous_payload_size = max(0, lock_file.tell() - 1)
        payload_end = 1 + len(payload)
        padding = min(
            max(0, previous_payload_size - len(payload)),
            MAX_OWNER_BYTES - len(payload),
        )
        replacement = payload + (b" " * padding)
        lock_file.seek(1)
        lock_file.write(replacement)
        lock_file.flush()
        # Truncate only after the replacement payload has been written. Status probes read bytes
        # after the separately locked byte zero. Padding a shorter replacement with JSON-legal
        # whitespace keeps the pre-truncate record valid too, so readers see old or new metadata,
        # never an empty/partial JSON record while set_phase("stable") publishes the handoff.
        lock_file.truncate(payload_end)
        lock_file.flush()

    def release(self) -> None:
        lock_file = self._file
        if lock_file is None:
            return
        self._file = None
        try:
            lock_file.seek(1)
            lock_file.truncate()
            lock_file.flush()
            self._unlock_byte(lock_file)
        finally:
            lock_file.close()

    @staticmethod
    def _is_lock_contention(exc: OSError) -> bool:
        """Return whether an OS lock failure means another process owns the byte."""

        if sys.platform == "win32":
            # msvcrt.locking reports LK_NBLCK contention as EACCES on CPython; native callers may
            # preserve ERROR_LOCK_VIOLATION (33). File-open permission failures happen earlier and
            # unexpected lock API errors must retain their real diagnosis.
            return exc.errno in {errno.EACCES, errno.EAGAIN} or getattr(exc, "winerror", None) in {
                33
            }
        return isinstance(exc, BlockingIOError) or exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
            errno.EWOULDBLOCK,
        }

    @staticmethod
    def _read_owner(lock_file: BinaryIO) -> dict[str, Any] | None:
        try:
            lock_file.seek(1)
            raw = lock_file.read(MAX_OWNER_BYTES + 1)
            if len(raw) > MAX_OWNER_BYTES:
                return None
            payload = raw.decode("utf-8").strip()
            parsed = json.loads(payload) if payload else None
            return parsed if isinstance(parsed, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _lock_byte(lock_file: BinaryIO) -> None:
        lock_file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_byte(lock_file: BinaryIO) -> None:
        lock_file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_rig_session_owner(path: str | Path) -> dict[str, Any] | None:
    """Return metadata only when the authoritative OS lock byte is currently owned.

    PID liveness is insufficient: an unclean exit leaves JSON behind and the PID can be reused by
    an unrelated process. Probe the byte non-blockingly; successfully taking it proves idleness and
    stale metadata is ignored. Real launchers allow a short acquisition grace so this microsecond
    status probe cannot create a false busy failure.
    """
    lock_path = Path(path)
    try:
        lock_file = lock_path.open("r+b")
    except FileNotFoundError:
        return None
    except OSError:
        return {"cwd": "unknown"}
    try:
        try:
            if sys.platform == "win32":
                # Windows exclusive byte-range locks deny overlapping reads. Reading byte zero is
                # a contend-only query: it fails with ERROR_LOCK_VIOLATION when owned and never
                # acquires a lock that could race a real launcher.
                lock_file.seek(0)
                try:
                    lock_file.read(1)
                except OSError as exc:
                    if not RigSessionLock._is_lock_contention(exc):
                        return {"cwd": "unknown"}
                    return RigSessionLock._read_owner(lock_file) or {"cwd": "unknown"}
                return None
            try:
                RigSessionLock._lock_byte(lock_file)
            except OSError as exc:
                if RigSessionLock._is_lock_contention(exc):
                    return RigSessionLock._read_owner(lock_file) or {"cwd": "unknown"}
                return {"cwd": "unknown"}
            RigSessionLock._unlock_byte(lock_file)
            return None
        except OSError:
            return {"cwd": "unknown"}
    finally:
        try:
            lock_file.close()
        except OSError:
            pass


def require_rig_session_owner(owner_pid: int, path: str | Path) -> dict[str, Any]:
    """Verify that ``owner_pid`` holds the canonical rig lock now; never acquire or replace it.

    A composed run (#815: voice capture, bounded guardian and autonomous driver) shares one owner
    that a separate process holds for the whole run, instead of each tool taking the lock in turn.
    """
    if type(owner_pid) is not int or owner_pid <= 0:
        raise ValueError("owner PID must be positive")
    owner = read_rig_session_owner(path)
    if not owner or owner.get("pid") != owner_pid:
        raise RigOwnerMismatch(f"rig owner mismatch: expected PID {owner_pid}; observed {owner}")
    return owner


MAX_HOLD_SECONDS = 4 * 60 * 60


def hold_rig_session(
    path: str | Path,
    *,
    owner: RigSessionOwner,
    stop_file: str | Path,
    max_hold_s: float,
    poll_interval: float = 0.5,
    emit=print,  # noqa: ANN001 - injectable for tests
) -> str:
    """Own the rig until ``stop_file`` appears or the fixed hold bound elapses.

    The stop path must not exist beforehand: one hold is one ownership epoch, and a leftover stop
    request cannot be mistaken for the release of a new hold. Returns the release reason.
    """
    if not math.isfinite(max_hold_s) or not 0 < max_hold_s <= MAX_HOLD_SECONDS:
        raise ValueError(f"max hold must be within (0, {MAX_HOLD_SECONDS}] seconds")
    stop = Path(stop_file)
    if stop.exists():
        raise FileExistsError(f"stop file already exists; start a fresh hold epoch: {stop}")
    deadline = time.monotonic() + max_hold_s
    with RigSessionLock(path, owner=owner) as lock:
        emit(json.dumps({"status": "held", "lock": str(lock.path), "owner": owner.to_dict()}))
        reason = "stop_file"
        while not stop.exists():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = "max_hold_elapsed"
                break
            time.sleep(min(poll_interval, remaining))
    emit(json.dumps({"status": "released", "reason": reason}))
    return reason


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m tools.ac_harness.rig_lock")
    sub = parser.add_subparsers(dest="command", required=True)
    hold = sub.add_parser("hold", help="own the canonical rig lock until a stop file appears")
    hold.add_argument("--stop-file", required=True, type=Path)
    hold.add_argument("--max-hold-s", type=float, default=60 * 60)
    hold.add_argument("--car")
    hold.add_argument("--track")
    hold.add_argument("--session-kind", default="held_session")
    args = parser.parse_args(argv)
    owner = RigSessionOwner(
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        car=args.car,
        track=args.track,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        session_kind=args.session_kind,
    )
    try:
        hold_rig_session(
            default_rig_session_lock_path(),
            owner=owner,
            stop_file=args.stop_file,
            max_hold_s=args.max_hold_s,
        )
    except RigSessionBusy as exc:
        print(f"rig-lock: RIG BUSY — {exc}")
        return 3
    except (ValueError, FileExistsError) as exc:
        print(f"rig-lock: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
