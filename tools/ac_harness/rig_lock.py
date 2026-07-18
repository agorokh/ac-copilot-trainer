"""Cross-process ownership guard for the single physical Assetto Corsa rig.

Assetto Corsa and Content Manager are machine-global resources: two ``auto_drive`` processes from
different git worktrees cannot safely share them.  A repository-local lock is insufficient because
each worktree has its own ``.scratch`` directory, so the lock lives under the product's LocalAppData
folder and uses an OS file lock that is released automatically when the owner process exits.
"""

from __future__ import annotations

import errno
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "cwd": self.cwd,
            "car": self.car,
            "track": self.track,
            "started_at": self.started_at,
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
        if timeout < 0:
            raise ValueError("rig lock timeout must be >= 0")
        if poll_interval <= 0:
            raise ValueError("rig lock poll interval must be > 0")
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
        lock_file = self.path.open("a+b")
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
        payload = json.dumps(self.owner.to_dict(), sort_keys=True).encode("utf-8")
        lock_file.seek(1)
        lock_file.truncate()
        lock_file.write(payload)
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
            payload = lock_file.read().decode("utf-8").strip()
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
    try:
        try:
            RigSessionLock._lock_byte(lock_file)
        except OSError as exc:
            if RigSessionLock._is_lock_contention(exc):
                return RigSessionLock._read_owner(lock_file)
            raise
        else:
            RigSessionLock._unlock_byte(lock_file)
            return None
    finally:
        lock_file.close()
