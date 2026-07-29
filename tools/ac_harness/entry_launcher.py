"""Detect-and-retry launcher for deterministic AC on-track entry.

This is the actuator half of EPIC #154/#177. ``shared_memory.py`` answers
"is car 0 actually driving?"; this module owns what to do while the answer is
"not yet": normalize prior state, launch AC, poll the shared-memory detector,
and retry through a pluggable actuator until driving is observed or the retry
budget is exhausted.

The default actuator is deliberately conservative: set ``SPAWN_SET=PIT`` in
``race.ini``, kill any existing ``acs.exe``, and cold-launch ``acs.exe`` again
when the menu-skip race loses. ViGEm/virtual-gamepad and Content Manager IPC
are left as future actuator plugins; the loop does not bake either in.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import io
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from tools.ac_harness.shared_memory import (
    AcGameStatus,
    DrivingEntryDetector,
    GraphicsSnapshot,
    PhysicsSnapshot,
    SharedMemoryReader,
    SharedMemoryUnavailable,
)


class EntryPhase(StrEnum):
    """High-level state of the entry attempt from one shared-memory poll."""

    STARTING = "starting"
    STUCK_IN_MENU = "stuck_in_menu"
    IN_PIT = "in_pit"
    DRIVING = "driving"


class EntryOutcome(StrEnum):
    """Terminal outcome of one launcher run."""

    DRIVING = "driving"
    FAILED = "failed"


class EntryLaunchUnsupported(RuntimeError):
    """Raised when an actuator cannot run on the current host/platform."""


@dataclass(frozen=True)
class ActuatorEvent:
    """One actuator action taken by the launcher."""

    action: str
    detail: str = ""
    supported: bool = True


class EntryActuator(Protocol):
    """Pluggable session-entry actuator.

    A future ViGEm or CM-IPC actuator can implement ``trigger_drive`` without
    changing the detector loop. The default cold-restart actuator reports
    ``supported=False`` for ``trigger_drive``, causing the loop to relaunch.
    """

    def normalize_prior_state(self) -> ActuatorEvent | None:
        """Make the next launch start from a stable state."""

    def launch(self) -> ActuatorEvent:
        """Start a fresh AC session attempt."""

    def trigger_drive(self) -> ActuatorEvent:
        """Re-issue a Drive/start-session trigger inside the current attempt."""

    def relaunch(self) -> ActuatorEvent:
        """Quit the current attempt and launch again."""


@dataclass(frozen=True)
class EntryLauncherConfig:
    """Timing and retry budget for :class:`EntryLauncher`."""

    max_launches: int = 3
    attempt_timeout: float = 30.0
    poll_interval: float = 0.03
    trigger_after: float = 3.0
    trigger_interval: float = 1.0
    max_drive_triggers_per_launch: int = 5
    required_live_reads: int = 5
    stagnation_seconds: float = 0.05

    def __post_init__(self) -> None:
        if self.max_launches < 1:
            raise ValueError("max_launches must be >= 1")
        if self.attempt_timeout <= 0:
            raise ValueError("attempt_timeout must be > 0")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")
        if self.trigger_after < 0:
            raise ValueError("trigger_after must be >= 0")
        if self.trigger_interval <= 0:
            raise ValueError("trigger_interval must be > 0")
        if self.max_drive_triggers_per_launch < 0:
            raise ValueError("max_drive_triggers_per_launch must be >= 0")
        if self.required_live_reads < 1:
            raise ValueError("required_live_reads must be >= 1")
        if self.stagnation_seconds <= 0:
            raise ValueError("stagnation_seconds must be > 0")


@dataclass(frozen=True)
class EntryLaunchResult:
    """Result of running the detect-and-retry loop."""

    outcome: EntryOutcome
    launches: int
    polls: int
    last_phase: EntryPhase | None
    events: tuple[ActuatorEvent, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is EntryOutcome.DRIVING


class SnapshotReader(Protocol):
    """Small reader protocol shared by the live reader and tests."""

    def read_graphics(self) -> GraphicsSnapshot:
        """Read one graphics snapshot."""

    def read_physics(self) -> PhysicsSnapshot | None:
        """Read one optional physics snapshot."""

    def close(self) -> None:
        """Release any held resources."""


def classify_entry_phase(
    graphics: GraphicsSnapshot,
    *,
    detector: DrivingEntryDetector,
) -> EntryPhase:
    """Classify one poll into the launcher-level entry phase.

    ``DrivingEntryDetector`` remains the authority for success. This classifier
    is intentionally coarser: once the sim is not making progress toward
    sustained LIVE+not-pit+advancing, the actuator loop has enough signal to
    retry or relaunch.
    """

    if detector.driving:
        return EntryPhase.DRIVING
    if graphics.status == AcGameStatus.PAUSE:
        return EntryPhase.STUCK_IN_MENU
    if graphics.is_live and graphics.is_in_pit:
        return EntryPhase.IN_PIT
    return EntryPhase.STARTING


def normalize_race_ini_spawn_set(
    path: str | Path,
    *,
    section: str = "SESSION_0",
    spawn_set: str = "PIT",
) -> None:
    """Set ``[SESSION_0] SPAWN_SET`` in an AC ``race.ini`` file.

    The function uses ``configparser`` rather than string replacement so it
    handles missing sections/options and normal INI escaping consistently. AC's
    generated ``race.ini`` is machine-owned, so rewriting formatting/comments is
    acceptable for this harness normalization step.
    """

    race_ini = Path(path)
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str  # preserve AC's uppercase keys
    if race_ini.exists():
        parser.read(race_ini, encoding="utf-8")
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, "SPAWN_SET", spawn_set)
    tmp_path = race_ini.with_suffix(f"{race_ini.suffix}.tmp" if race_ini.suffix else ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            parser.write(fh, space_around_delimiters=False)
        tmp_path.replace(race_ini)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _taskkill(
    process_name: str,
    runner: Callable[..., subprocess.CompletedProcess],
) -> str:
    """Best-effort ``taskkill`` of a process tree; returns a human-readable detail string."""

    if sys.platform != "win32":
        return f"{process_name} kill skipped on {sys.platform}"
    result = runner(
        ["taskkill", "/IM", process_name, "/F", "/T"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return f"killed {process_name}"
    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else " (process may not have been running)"
    return f"taskkill {process_name} exited {result.returncode}{suffix}"


def _taskkill_soft(
    process_name: str,
    runner: Callable[..., subprocess.CompletedProcess],
) -> str:
    """Graceful ``taskkill`` (WM_CLOSE, no ``/F``); returns a human-readable detail string.

    The #668 batteries measured why this exists: the #627 freeze accumulator arms with
    launch/kill cycles, and hard-kill teardown moved onset from launch ~14 to launch ~8 —
    graceful exits roughly double a boot's clean-launch budget. A wedged render pump cannot
    process WM_CLOSE (observed: one WM_CLOSE hang immediately after a freeze burst), so this
    is only ever a FIRST phase — the forced kill remains the fallback boundary.
    """

    if sys.platform != "win32":
        return f"{process_name} graceful close skipped on {sys.platform}"
    result = runner(
        ["taskkill", "/IM", process_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return f"requested graceful close of {process_name}"
    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    return f"graceful taskkill {process_name} exited {result.returncode}{suffix}"


def running_process_ids(
    process_name: str,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    *,
    strict: bool = False,
) -> frozenset[int]:
    """Return PIDs for a Windows image name without adding a runtime dependency.

    Production uses Toolhelp32 directly so the real-time drive loop does not spawn ``tasklist`` and
    incur a control-latency spike every second. Tests can inject ``runner`` to exercise the stable
    CSV fallback/parser without relying on the host process table.
    """

    if sys.platform != "win32":
        return frozenset()
    if runner is None:
        try:
            return _toolhelp_process_ids(process_name)
        except _PartialProcessEnumerationError as exc:
            if strict:
                raise
            return exc.partial_process_ids
        except OSError:
            if strict:
                raise
            return frozenset()
    result = runner(
        ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if strict:
            detail = (result.stderr or result.stdout or "").strip()
            raise OSError(f"tasklist exited {result.returncode}: {detail or 'unknown error'}")
        return frozenset()
    found: set[int] = set()
    for row in csv.reader(io.StringIO(result.stdout or "")):
        if len(row) < 2 or row[0].casefold() != process_name.casefold():
            continue
        try:
            found.add(int(row[1]))
        except ValueError:
            continue
    return frozenset(found)


class _PartialProcessEnumerationError(OSError):
    """A native process snapshot failed after yielding some useful matching PIDs."""

    def __init__(
        self,
        error: int,
        message: str,
        partial_process_ids: set[int],
    ) -> None:
        super().__init__(error, message)
        self.partial_process_ids = frozenset(partial_process_ids)


def terminate_process_tree_confirmed_absent(
    process_name: str,
    *,
    is_running: Callable[[], bool] | None = None,
    timeout: float = 15.0,
    poll: float = 1.0,
    absent_confirmations: int = 2,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] | None = None,
    graceful_grace: float = 0.0,
) -> bool:
    """Kill one process tree and require consecutive strict absence observations.

    This is the shared rig-safety boundary for both human and autonomous launchers. Enumeration
    failure is unknown—not absence—and triggers the same best-effort taskkill as positive presence.
    A process already absent is not killed, but still needs ``absent_confirmations`` observations.

    ``graceful_grace`` > 0 prepends a WM_CLOSE phase (#668): the first presence observation sends
    a graceful ``taskkill`` (no ``/F``) and the forced kill is deferred until ``graceful_grace``
    seconds have elapsed without absence. The confirmed-absent contract is unchanged — the forced
    fallback and the overall ``timeout`` still bound the wait, so a wedged process (which cannot
    pump WM_CLOSE) degrades to exactly the old behavior, ``graceful_grace`` later. Callers must
    size ``timeout`` to leave room for the forced phase (``timeout > graceful_grace``).
    """
    if timeout <= 0:
        raise ValueError("process termination timeout must be > 0")
    if poll <= 0:
        raise ValueError("process termination poll must be > 0")
    if absent_confirmations < 1:
        raise ValueError("absent_confirmations must be >= 1")
    if graceful_grace < 0:
        raise ValueError("graceful_grace must be >= 0")
    if graceful_grace >= timeout:
        raise ValueError("graceful_grace must leave room for the forced phase (< timeout)")
    emit = log or (lambda _message: None)
    if sys.platform != "win32":
        emit(f"cannot confirm {process_name} termination on unsupported platform {sys.platform}")
        return False
    check_running = is_running
    if check_running is None:

        def check_running() -> bool:
            return bool(running_process_ids(process_name, strict=True))

    run = runner or subprocess.run
    started = clock()
    deadline = started + timeout
    forced_after = started + graceful_grace
    absent_run = 0
    soft_attempted = False
    kill_attempted = False
    while True:
        try:
            present: bool | None = check_running()
        except OSError as exc:
            present = None
            emit(f"process enumeration failed for {process_name}: {exc}")
        if present is False:
            absent_run += 1
            if absent_run >= absent_confirmations:
                return True
        else:
            absent_run = 0
            if graceful_grace > 0 and not soft_attempted:
                try:
                    emit(_taskkill_soft(process_name, run))
                except OSError as exc:
                    emit(f"failed to invoke graceful taskkill for {process_name}: {exc}")
                soft_attempted = True
            elif not kill_attempted and (graceful_grace <= 0 or clock() >= forced_after):
                if soft_attempted:
                    emit(
                        f"{process_name} survived the {graceful_grace:.0f}s graceful grace — "
                        "escalating to forced kill (wedged pumps cannot process WM_CLOSE)"
                    )
                try:
                    emit(_taskkill(process_name, run))
                except OSError as exc:
                    emit(f"failed to invoke taskkill for {process_name}: {exc}")
                kill_attempted = True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleep(min(poll, remaining))


def _toolhelp_process_ids(process_name: str) -> frozenset[int]:
    """Enumerate Windows processes in-process via ``CreateToolhelp32Snapshot``."""

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, "CreateToolhelp32Snapshot failed")
    found: set[int] = set()
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        ctypes.set_last_error(0)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(error, "Process32FirstW failed")
        while True:
            if entry.szExeFile.casefold() == process_name.casefold():
                found.add(int(entry.th32ProcessID))
            ctypes.set_last_error(0)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            if not ok:
                error = ctypes.get_last_error()
                if error not in (0, 18):  # ERROR_NO_MORE_FILES is normal enumeration completion.
                    raise _PartialProcessEnumerationError(
                        error,
                        "Process32NextW failed",
                        found,
                    )
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return frozenset(found)


def process_module_names(
    process_id: int,
    *,
    retries: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> frozenset[str]:
    """Casefolded basenames of every module loaded in ``process_id``.

    Used by the #625 A/B to observe which init perturbers were actually injected into a live
    ``acs.exe`` (#719). The treatment is otherwise asserted by the operator and never measured.

    **Raises** ``OSError`` when the snapshot cannot be taken. That failure MUST NOT be folded into
    an empty set: "the process loaded no modules" and "we could not look" are different claims, and
    only the caller can encode the difference (an empty set would read as *perturber absent*, which
    would silently invert the treatment check this exists to provide).

    ``CreateToolhelp32Snapshot`` fails with ``ERROR_BAD_LENGTH`` while the target is still loading
    its module list — documented as retryable, and the common case here because the launcher probes
    a process that AC is actively starting.
    """

    if sys.platform != "win32":
        return frozenset()

    import ctypes
    from ctypes import wintypes

    max_module_name32 = 255

    class ModuleEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * (max_module_name32 + 1)),
            ("szExePath", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Module32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ModuleEntry32W))
    kernel32.Module32FirstW.restype = wintypes.BOOL
    kernel32.Module32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ModuleEntry32W))
    kernel32.Module32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    invalid_handle = wintypes.HANDLE(-1).value
    snapshot_flags = 0x00000008 | 0x00000010  # TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    error_bad_length = 24

    snapshot = invalid_handle
    last_error = 0
    for attempt in range(max(1, retries)):
        ctypes.set_last_error(0)
        snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_flags, process_id)
        if snapshot != invalid_handle:
            break
        last_error = ctypes.get_last_error()
        if last_error != error_bad_length:
            break
        if attempt + 1 < max(1, retries):
            sleep(0.15)
    if snapshot == invalid_handle:
        raise OSError(last_error, f"CreateToolhelp32Snapshot(module) failed for pid {process_id}")

    names: set[str] = set()
    try:
        entry = ModuleEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        ctypes.set_last_error(0)
        if not kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
            error = ctypes.get_last_error()
            raise OSError(error, f"Module32FirstW failed for pid {process_id}")
        while True:
            names.add(entry.szModule.casefold())
            ctypes.set_last_error(0)
            if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error not in (0, 18):  # ERROR_NO_MORE_FILES ends enumeration normally.
                    raise OSError(error, f"Module32NextW failed for pid {process_id}")
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return frozenset(names)


class ColdRestartActuator:
    """Default no-new-dependency actuator: normalize state, kill, relaunch AC."""

    def __init__(
        self,
        *,
        acs_exe: str | Path,
        race_ini: str | Path | None = None,
        launch_args: Sequence[str] = (),
        process_name: str = "acs.exe",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.acs_exe = Path(acs_exe).expanduser().resolve(strict=False)
        self.race_ini = (
            Path(race_ini).expanduser().resolve(strict=False) if race_ini is not None else None
        )
        self.launch_args = tuple(launch_args)
        self.process_name = process_name
        self._runner = runner
        self._popen = popen

    def normalize_prior_state(self) -> ActuatorEvent | None:
        kill_detail = self._kill_existing()
        if self.race_ini is None:
            return ActuatorEvent("normalize", kill_detail)
        normalize_race_ini_spawn_set(self.race_ini, spawn_set="PIT")
        return ActuatorEvent("normalize", f"{kill_detail}; {self.race_ini}: SPAWN_SET=PIT")

    def launch(self) -> ActuatorEvent:
        if sys.platform != "win32":
            raise EntryLaunchUnsupported("ColdRestartActuator launch is Windows-only")
        if not self.acs_exe.exists():
            raise FileNotFoundError(f"acs.exe not found: {self.acs_exe}")
        cmd = [str(self.acs_exe), *self.launch_args]
        self._popen(cmd, cwd=str(self.acs_exe.parent))
        return ActuatorEvent("launch", " ".join(cmd))

    def trigger_drive(self) -> ActuatorEvent:
        return ActuatorEvent(
            "trigger_drive",
            "no in-session Drive trigger configured; falling back to cold relaunch",
            supported=False,
        )

    def relaunch(self) -> ActuatorEvent:
        normalized = self.normalize_prior_state()
        launch = self.launch()
        if normalized is None:
            return ActuatorEvent("relaunch", launch.detail)
        return ActuatorEvent("relaunch", f"{normalized.detail}; {launch.detail}")

    def _kill_existing(self) -> str:
        return _taskkill(self.process_name, self._runner)


class ContentManagerActuator:
    """Content Manager IPC actuator — de-elevated on-track launch via the ``acmanager://`` URL.

    Spawning ``Content Manager.exe "acmanager://race/quick?presetFile=<preset>"`` hands the URL to
    the already-running (non-elevated) Content Manager through its single-instance IPC; CM runs the
    Quick Drive preset (``QuickDrive.RunAsync``) and launches ``acs.exe`` as **its own** child —
    i.e. non-elevated. That survives the rig's elevation split (elevated agent/daemon shell vs
    non-elevated Steam + CM) that makes a direct ``acs.exe`` launch trip the Steam-integrity
    mismatch. Verified live on ``AG_PC``: car on track in ~3 s, physics advancing at ~333 Hz
    (EPIC #154 #232).

    CM owns the immediate-start handshake, so there is no in-attempt Drive re-trigger:
    :meth:`trigger_drive` reports ``supported=False`` and :class:`EntryLauncher` cold-relaunches
    when the (genuinely non-deterministic) pre-drive menu-skip race loses.
    """

    DEFAULT_CM_EXE = Path(r"C:\Program Files (x86)\ContentManager\Content Manager.exe")

    def __init__(
        self,
        *,
        preset: str | Path,
        cm_exe: str | Path | None = None,
        process_name: str = "acs.exe",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        # Resolve to absolute: the URL is read by a *separate* CM process with its own cwd, so a
        # relative presetFile would break `File.ReadAllText`. Mirrors ColdRestartActuator.
        self.preset = Path(preset).expanduser().resolve(strict=False)
        cm = Path(cm_exe).expanduser() if cm_exe is not None else self.DEFAULT_CM_EXE
        self.cm_exe = cm.resolve(strict=False)
        self.process_name = process_name
        self._runner = runner
        self._popen = popen

    def quick_drive_url(self) -> str:
        """``acmanager://race/quick?presetFile=<url-encoded preset path>`` (CM runs the preset)."""
        return "acmanager://race/quick?presetFile=" + urllib.parse.quote(str(self.preset), safe="")

    def normalize_prior_state(self) -> ActuatorEvent | None:
        # Cold-start the menu-skip race: kill any stale acs.exe so each launch is deterministic.
        return ActuatorEvent("normalize", _taskkill(self.process_name, self._runner))

    def launch(self) -> ActuatorEvent:
        if sys.platform != "win32":
            raise EntryLaunchUnsupported("ContentManagerActuator launch is Windows-only")
        if not self.cm_exe.exists():
            raise FileNotFoundError(f"Content Manager not found: {self.cm_exe}")
        if not self.preset.exists():
            raise FileNotFoundError(f"Quick Drive preset not found: {self.preset}")
        url = self.quick_drive_url()
        self._popen([str(self.cm_exe), url])
        return ActuatorEvent("launch", url)

    def trigger_drive(self) -> ActuatorEvent:
        return ActuatorEvent(
            "trigger_drive",
            "Content Manager owns immediate-start; relaunch on menu-skip-race timeout",
            supported=False,
        )

    def relaunch(self) -> ActuatorEvent:
        normalized = self.normalize_prior_state()
        launch = self.launch()
        if normalized is None:
            return ActuatorEvent("relaunch", launch.detail)
        return ActuatorEvent("relaunch", f"{normalized.detail}; {launch.detail}")

    def restart_content_manager(self) -> ActuatorEvent:
        """Kill the Content Manager process (tree) so the NEXT launch cold-starts a FRESH CM.

        The ``acmanager://`` URL is handed to the already-running CM via single-instance IPC. A CM
        instance that has gone stale — no longer honoring the ``presetFile`` and re-running its
        cached last session (#537 / #558) — keeps serving that cached session no matter how often
        the URL is re-sent (a plain :meth:`relaunch` only kills ``acs.exe``). Killing the CM
        process makes the next :meth:`launch` cold-start a fresh instance that processes the preset
        URL — exactly the recovery a MANUAL Content Manager restart performs (live-proven on AG_PC
        2026-07-13: after the restart the next launch hijacked on probe 1 and drove a clean lap).
        ``/T`` also takes down CM's ``acs.exe`` child in the same call.
        """
        return ActuatorEvent("restart_cm", _taskkill(self.cm_exe.name, self._runner))


LAUNCH_MODES = ("cm", "acs")


def make_actuator(
    launch_mode: str,
    *,
    acs_exe: str | Path | None = None,
    race_ini: str | Path | None = None,
    cm_exe: str | Path | None = None,
    cm_preset: str | Path | None = None,
) -> EntryActuator:
    """Build the entry actuator for ``launch_mode``.

    ``"cm"`` → :class:`ContentManagerActuator` (de-elevated CM-URL launch; needs ``cm_preset``).
    ``"acs"`` → :class:`ColdRestartActuator` (direct ``acs.exe`` launch; needs ``acs_exe``).
    """

    if launch_mode == "cm":
        if cm_preset is None:
            raise ValueError(
                "launch_mode='cm' requires a Content Manager Quick Drive preset (cm_preset)"
            )
        return ContentManagerActuator(preset=cm_preset, cm_exe=cm_exe)
    if launch_mode == "acs":
        if acs_exe is None:
            raise ValueError("launch_mode='acs' requires acs_exe")
        return ColdRestartActuator(acs_exe=acs_exe, race_ini=race_ini)
    raise ValueError(f"unknown launch_mode: {launch_mode!r} (expected one of {LAUNCH_MODES})")


class EntryLauncher:
    """Run the detect-and-retry loop against one actuator and reader factory."""

    def __init__(
        self,
        actuator: EntryActuator,
        *,
        reader_factory: Callable[[], SnapshotReader] = SharedMemoryReader,
        config: EntryLauncherConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.actuator = actuator
        self.reader_factory = reader_factory
        self.config = config or EntryLauncherConfig()
        self.clock = clock
        self.sleep = sleep

    def run(self) -> EntryLaunchResult:
        """Normalize, launch, and retry until driving or exhausted."""

        events: list[ActuatorEvent] = []
        polls = 0
        last_phase: EntryPhase | None = None
        last_reason = ""

        normalized = self.actuator.normalize_prior_state()
        if normalized is not None:
            events.append(normalized)

        for launch_index in range(self.config.max_launches):
            if launch_index == 0:
                events.append(self.actuator.launch())
            else:
                events.append(self.actuator.relaunch())

            attempt = self._poll_one_launch()
            polls += attempt.polls
            events.extend(attempt.events)
            last_phase = attempt.last_phase
            last_reason = attempt.reason
            if attempt.outcome is EntryOutcome.DRIVING:
                return EntryLaunchResult(
                    EntryOutcome.DRIVING,
                    launches=launch_index + 1,
                    polls=polls,
                    last_phase=EntryPhase.DRIVING,
                    events=tuple(events),
                    reason=attempt.reason,
                )

        return EntryLaunchResult(
            EntryOutcome.FAILED,
            launches=self.config.max_launches,
            polls=polls,
            last_phase=last_phase,
            events=tuple(events),
            reason=(
                f"not driving after {self.config.max_launches} launch attempt(s)"
                + (f"; last attempt: {last_reason}" if last_reason else "")
            ),
        )

    def _poll_one_launch(self) -> EntryLaunchResult:
        detector = DrivingEntryDetector(
            required_live_reads=self.config.required_live_reads,
            stagnation_seconds=self.config.stagnation_seconds,
        )
        events: list[ActuatorEvent] = []
        polls = 0
        phase: EntryPhase | None = None
        drive_trigger_attempts = 0
        stop_reason = "attempt timed out"
        attempt_start = self.clock()
        next_trigger_at = attempt_start + self.config.trigger_after
        deadline = attempt_start + self.config.attempt_timeout
        reader: SnapshotReader | None = None
        last_unavailable = ""

        try:
            while self.clock() <= deadline:
                now = self.clock()
                if reader is None:
                    try:
                        reader = self.reader_factory()
                    except SharedMemoryUnavailable as err:
                        last_unavailable = str(err)
                        self.sleep(self.config.poll_interval)
                        continue
                try:
                    graphics = reader.read_graphics()
                    physics = reader.read_physics()
                except SharedMemoryUnavailable as err:
                    last_unavailable = str(err)
                    reader.close()
                    reader = None
                    self.sleep(self.config.poll_interval)
                    continue

                detector.observe(graphics, physics, now=now)
                polls += 1
                phase = classify_entry_phase(graphics, detector=detector)
                if phase is EntryPhase.DRIVING:
                    return EntryLaunchResult(
                        EntryOutcome.DRIVING,
                        launches=1,
                        polls=polls,
                        last_phase=phase,
                        events=tuple(events),
                        reason="shared-memory detector observed sustained driving",
                    )

                if (
                    phase in {EntryPhase.STUCK_IN_MENU, EntryPhase.IN_PIT}
                    and now >= next_trigger_at
                ):
                    if drive_trigger_attempts >= self.config.max_drive_triggers_per_launch:
                        stop_reason = "drive trigger budget exhausted"
                        break
                    drive_trigger_attempts += 1
                    event = self.actuator.trigger_drive()
                    events.append(event)
                    if not event.supported:
                        stop_reason = f"actuator requested relaunch: {event.detail}"
                        break
                    next_trigger_at = now + self.config.trigger_interval

                self.sleep(self.config.poll_interval)
        finally:
            if reader is not None:
                reader.close()

        return EntryLaunchResult(
            EntryOutcome.FAILED,
            launches=1,
            polls=polls,
            last_phase=phase,
            events=tuple(events),
            reason=last_unavailable if polls == 0 and last_unavailable else stop_reason,
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AC detect-and-retry entry launcher")
    parser.add_argument(
        "--launch-mode",
        choices=LAUNCH_MODES,
        default="acs",
        help="cm = de-elevated Content Manager URL launch; acs = direct acs.exe (default)",
    )
    parser.add_argument("--acs-exe", help="Path to acs.exe (required for --launch-mode acs)")
    parser.add_argument("--race-ini", help="Path to Documents/Assetto Corsa/cfg/race.ini")
    parser.add_argument(
        "--cm-exe",
        help="Path to Content Manager.exe (default: standard install; --launch-mode cm)",
    )
    parser.add_argument(
        "--cm-preset",
        help="Path to a Quick Drive .cmpreset (required for --launch-mode cm)",
    )
    parser.add_argument("--max-launches", type=int, default=3)
    parser.add_argument("--attempt-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=0.03)
    parser.add_argument("--trigger-after", type=float, default=3.0)
    parser.add_argument("--trigger-interval", type=float, default=1.0)
    parser.add_argument("--max-drive-triggers-per-launch", type=int, default=5)
    parser.add_argument("--required-live-reads", type=int, default=5)
    parser.add_argument("--stagnation-seconds", type=float, default=0.05)
    return parser


def _main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.launch_mode == "acs" and args.acs_exe is None:
        parser.error("--launch-mode acs requires --acs-exe")
    if args.launch_mode == "cm" and args.cm_preset is None:
        parser.error("--launch-mode cm requires --cm-preset (path to a Quick Drive .cmpreset)")
    actuator = make_actuator(
        args.launch_mode,
        acs_exe=args.acs_exe,
        race_ini=args.race_ini,
        cm_exe=args.cm_exe,
        cm_preset=args.cm_preset,
    )
    launcher = EntryLauncher(
        actuator,
        config=EntryLauncherConfig(
            max_launches=args.max_launches,
            attempt_timeout=args.attempt_timeout,
            poll_interval=args.poll_interval,
            trigger_after=args.trigger_after,
            trigger_interval=args.trigger_interval,
            max_drive_triggers_per_launch=args.max_drive_triggers_per_launch,
            required_live_reads=args.required_live_reads,
            stagnation_seconds=args.stagnation_seconds,
        ),
    )
    result = launcher.run()
    for event in result.events:
        support = "" if event.supported else " (unsupported)"
        print(f"[entry] {event.action}{support}: {event.detail}")
    print(
        f"[entry] outcome={result.outcome.value} launches={result.launches} "
        f"polls={result.polls} phase={result.last_phase} reason={result.reason}"
    )
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    raise SystemExit(_main())
