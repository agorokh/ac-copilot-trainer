"""Independent, nonrenewable deadline for one explicitly owned Windows rig run.

Start this separate process and observe ``armed.json`` before enabling AI driving.
No heartbeat, agent continuation, name-based kill, or process-tree kill is involved.
After the verified owner exits, the armed guardian may acquire an idle canonical lock
solely to close its pinned targets. An active replacement owner blocks that takeover.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import ntpath
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Protocol

from tools.ac_harness.rig_lock import (
    RigSessionLock,
    RigSessionOwner,
    default_rig_session_lock_path,
    read_rig_session_owner,
)

MAX_RUNTIME_S = 600.0


def require_independent_worker() -> None:
    """Refuse a worker whose lifetime could be tied to a disposable Windows Job."""
    if sys.platform != "win32":
        raise OSError("rig watchdog requires Windows")
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    kernel.IsProcessInJob.restype = w.BOOL
    in_job = w.BOOL()
    if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(in_job)):
        raise ctypes.WinError(ctypes.get_last_error())
    if in_job.value:
        raise RuntimeError("watchdog is inside a Windows Job; independent lifetime is unproved")


def require_scheduled_worker(run_id: str) -> dict:
    """Bind this exact task action PID to the Schedule service and bounded task definition."""
    from ctypes import wintypes as w

    from tools.ac_harness.remote_launcher import task_name_for, validate_run_component

    validate_run_component("run id", run_id)
    shim = Path(__file__).resolve().with_name("_remote_exec.py")
    if len(sys.argv) != 2 or Path(sys.argv[0]).resolve() != shim or sys.argv[1] != run_id:
        raise RuntimeError("scheduled watchdog must execute inside its canonical task action")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.OpenSCManagerW.argtypes, api.OpenSCManagerW.restype = (
        [w.LPCWSTR, w.LPCWSTR, w.DWORD],
        w.HANDLE,
    )
    api.OpenServiceW.argtypes, api.OpenServiceW.restype = [w.HANDLE, w.LPCWSTR, w.DWORD], w.HANDLE
    api.QueryServiceStatusEx.argtypes = [
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
        ctypes.POINTER(w.DWORD),
    ]
    api.QueryServiceStatusEx.restype = w.BOOL
    api.CloseServiceHandle.argtypes, api.CloseServiceHandle.restype = [w.HANDLE], w.BOOL
    manager = api.OpenSCManagerW(None, None, 1)
    if not manager:
        raise ctypes.WinError(ctypes.get_last_error())
    service = None
    try:
        service = api.OpenServiceW(manager, "Schedule", 4)
        if not service:
            raise ctypes.WinError(ctypes.get_last_error())
        status, required = (w.DWORD * 9)(), w.DWORD()
        if not api.QueryServiceStatusEx(
            service, 0, status, ctypes.sizeof(status), ctypes.byref(required)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        scheduler_pid = int(status[7])
        if status[1] != 4 or scheduler_pid <= 0 or os.getppid() != scheduler_pid:
            raise RuntimeError(
                "task action is not a direct child of the running Schedule service: "
                f"parent={os.getppid()}, service={scheduler_pid}"
            )
    finally:
        if service:
            api.CloseServiceHandle(service)
        api.CloseServiceHandle(manager)
    task = task_name_for(run_id)
    queried = subprocess.run(
        ["schtasks", "/query", "/tn", task, "/xml"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if queried.returncode:
        raise RuntimeError("cannot verify scheduled watchdog definition")
    validate_scheduled_definition(
        queried.stdout, run_id=run_id, interpreter=sys.executable, shim=shim
    )
    process = WindowsProcess(os.getpid())
    try:
        identity = process.identity()
    finally:
        process.close()
    return {
        "kind": "task_scheduler_owned_job",
        "task": task,
        "run_id": run_id,
        "worker": asdict(identity),
        "scheduler_service_pid": scheduler_pid,
        "execution_time_limit_s": 660,
        "definition_sha256": hashlib.sha256(queried.stdout.encode()).hexdigest(),
    }


def validate_scheduled_definition(xml: str, *, run_id: str, interpreter: str, shim: Path) -> None:
    root = ET.fromstring(xml)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    actions = root.findall("t:Actions/t:Exec", ns)
    if len(actions) != 1 or len(root.findall("t:Actions/*", ns)) != 1:
        raise RuntimeError("scheduled watchdog must have exactly one canonical action")
    principals = root.findall("t:Principals/t:Principal", ns)
    action_group = root.find("t:Actions", ns)
    if (
        len(principals) != 1
        or not principals[0].get("id")
        or action_group.get("Context") != principals[0].get("id")
    ):
        raise RuntimeError("scheduled watchdog action must use its single verified principal")
    command, arguments = (
        actions[0].findtext("t:Command", namespaces=ns),
        actions[0].findtext("t:Arguments", namespaces=ns),
    )
    if (
        not command
        or Path(command).resolve() != Path(interpreter).resolve()
        or arguments != subprocess.list2cmdline([str(shim), run_id])
    ):
        raise RuntimeError("scheduled watchdog action identity mismatch")
    duration = root.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=ns) or ""
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    seconds = (
        sum(
            int(part or 0) * factor
            for part, factor in zip(match.groups(), (3600, 60, 1), strict=True)
        )
        if match
        else 0
    )
    if (
        seconds != 660
        or root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns)
        != "InteractiveToken"
        # Scheduler omits the default LeastPrivilege when exporting its normalized XML.
        or root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns)
        not in {None, "LeastPrivilege"}
    ):
        raise RuntimeError(
            "scheduled watchdog requires bounded duration and existing unelevated token: "
            f"duration={duration!r}, "
            f"logon={root.findtext('t:Principals/t:Principal/t:LogonType', namespaces=ns)!r}, "
            f"level={root.findtext('t:Principals/t:Principal/t:RunLevel', namespaces=ns)!r}"
        )


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created_filetime: int
    exe: str

    def __post_init__(self):
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("PID must be a positive integer")
        if type(self.created_filetime) is not int or self.created_filetime <= 0:
            raise ValueError("creation FILETIME must be a positive integer (100 ns ticks)")
        if not isinstance(self.exe, str) or not PureWindowsPath(self.exe).is_absolute():
            raise ValueError("executable must be an absolute Windows path")

    def matches(self, other: ProcessIdentity) -> bool:
        return (
            self.pid == other.pid
            and self.created_filetime == other.created_filetime
            and ntpath.normcase(ntpath.normpath(self.exe))
            == ntpath.normcase(ntpath.normpath(other.exe))
        )


class BoundProcess(Protocol):
    def identity(self) -> ProcessIdentity: ...
    def exited(self) -> bool: ...
    def request_close(self) -> int: ...
    def terminate(self) -> None: ...
    def close(self) -> None: ...


class WindowsProcess:
    """Retain one kernel process handle, including during graceful/forced shutdown.

    Holding the handle binds termination to that process object, not a later PID reuse.
    Pointer-width prototypes follow the existing native harness backends. The existing
    entry_launcher cleanup is name-based, so it must not be called from this boundary.
    """

    def __init__(self, pid: int, *, can_terminate: bool = False):
        if sys.platform != "win32":
            raise OSError("rig watchdog requires Windows")
        if type(pid) is not int or pid <= 0:
            raise ValueError("PID must be positive")
        from ctypes import wintypes as w

        self.pid = pid
        self._can_terminate = can_terminate
        self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        self._u = ctypes.WinDLL("user32", use_last_error=True)
        self._callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        declarations = (
            (self._k.OpenProcess, [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self._k.CloseHandle, [w.HANDLE], w.BOOL),
            (self._k.WaitForSingleObject, [w.HANDLE, w.DWORD], w.DWORD),
            (self._k.TerminateProcess, [w.HANDLE, w.UINT], w.BOOL),
            (
                self._k.GetProcessTimes,
                [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)],
                w.BOOL,
            ),
            (
                self._k.QueryFullProcessImageNameW,
                [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            (self._u.EnumWindows, [self._callback_type, w.LPARAM], w.BOOL),
            (self._u.GetWindowThreadProcessId, [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self._u.PostMessageW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
        )
        for function, args, result in declarations:
            function.argtypes, function.restype = args, result
        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE, plus TERMINATE for explicit targets only.
        access = 0x1000 | 0x00100000 | (0x0001 if can_terminate else 0)
        self._handle = self._k.OpenProcess(access, False, pid)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def identity(self) -> ProcessIdentity:
        from ctypes import wintypes as w

        creation, exit_time, kernel, user = (w.FILETIME() for _ in range(4))
        if not self._k.GetProcessTimes(
            self._handle, *(ctypes.byref(value) for value in (creation, exit_time, kernel, user))
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        size = w.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not self._k.QueryFullProcessImageNameW(self._handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ProcessIdentity(self.pid, ticks, image.value)

    def exited(self) -> bool:
        result = self._k.WaitForSingleObject(self._handle, 0)
        if result == 0:
            return True
        if result == 258:  # WAIT_TIMEOUT: the retained process object is not signaled.
            return False
        raise OSError(f"process wait failed: {result}")

    def request_close(self) -> int:
        from ctypes import wintypes as w

        if not self._can_terminate:
            raise RuntimeError("read-only process handle")
        windows = []
        errors = []

        @self._callback_type
        def collect(hwnd, _param):
            pid = w.DWORD()
            if self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) and pid.value == self.pid:
                windows.append(hwnd)
            return True

        if not self._u.EnumWindows(collect, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        posted = 0
        for hwnd in windows:
            if self.exited():
                break
            pid = w.DWORD()
            # Recheck window ownership just before posting; never send global keyboard input.
            if self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) and pid.value == self.pid:
                if self._u.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE, asynchronous/bounded
                    posted += 1
                else:
                    errors.append(ctypes.get_last_error())
        if errors:
            raise OSError(f"WM_CLOSE failed: {errors}")
        return posted

    def terminate(self) -> None:
        if not self._can_terminate:
            raise RuntimeError("read-only process handle")
        if not self._k.TerminateProcess(self._handle, 1):
            if not self.exited():
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._k.CloseHandle(self._handle)
            self._handle = None


@dataclass(frozen=True)
class WatchdogConfig:
    owner_pid: int
    ac: ProcessIdentity
    run_dir: Path
    max_runtime_s: float = MAX_RUNTIME_S
    graceful_s: float = 15.0
    terminate_s: float = 5.0
    poll_s: float = 0.25
    sidecar: ProcessIdentity | None = None
    sidecar_stop_file: Path | None = None

    def __post_init__(self):
        if type(self.owner_pid) is not int or self.owner_pid <= 0:
            raise ValueError("owner PID must be positive")
        for field, maximum in (
            ("max_runtime_s", MAX_RUNTIME_S),
            ("graceful_s", 30.0),
            ("terminate_s", 15.0),
            ("poll_s", 1.0),
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError(f"{field} must be finite and in (0, {maximum}]")
        if ntpath.basename(self.ac.exe).casefold() not in {"acs.exe", "acs_x86.exe"}:
            raise ValueError("AC target must explicitly name acs.exe or acs_x86.exe")
        pids = [self.owner_pid, self.ac.pid]
        if self.sidecar:
            pids.append(self.sidecar.pid)
        if len(set(pids)) != len(pids):
            raise ValueError("owner, AC and optional sidecar must have distinct PIDs")
        if (self.sidecar is None) != (self.sidecar_stop_file is None):
            raise ValueError("sidecar identity and stop file must be specified together")


class OwnershipError(RuntimeError):
    pass


def run_watchdog(
    config: WatchdogConfig,
    *,
    process_factory=WindowsProcess,
    owner_reader=read_rig_session_owner,
    lock_factory=RigSessionLock,
    clock=time.monotonic,
    sleep=time.sleep,
    lifetime_basis: dict | None = None,
) -> dict:
    """Block in the independent watchdog process until exit or its fixed deadline.

    The fresh output directory is ``run_dir/watchdog``. The sidecar stop file, when
    supplied, must be absent and directly in the existing run directory. Only exact
    explicit targets are closed; owner/launcher/CM/Steam/SimHub peers are untouched.
    """
    run_dir = config.run_dir.resolve(strict=True)
    if not run_dir.is_dir():
        raise ValueError("run directory must already exist")
    output = run_dir / "watchdog"
    output.mkdir(exist_ok=False)
    lock_path = default_rig_session_lock_path()
    started = clock()
    deadline = started + config.max_runtime_s
    handles = []
    cleanup_lock = None
    armed = False
    receipt = {
        "schema_version": 1,
        "status": "failed",
        "reason": "not_armed",
        "watchdog_pid": os.getpid(),
        "owner_pid": config.owner_pid,
        "lock_path": str(lock_path),
        "started_monotonic_s": started,
        "deadline_monotonic_s": deadline,
        "max_runtime_s": config.max_runtime_s,
        "shutdown_max_s": config.graceful_s + config.terminate_s,
        "owner_exit_policy": "acquire_idle_canonical_lock_then_cleanup_pinned_targets",
        "lifetime_basis": lifetime_basis or {"kind": "independent_process"},
        "ac": asdict(config.ac),
        "sidecar": asdict(config.sidecar) if config.sidecar else None,
        "events": [],
        "errors": [],
    }

    def record(event, **details):
        row = {"event": event, "monotonic_s": clock(), **details}
        receipt["events"].append(row)
        try:
            with (output / "events.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(row) + "\n")
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            # Loss of diagnostics after arming must never cancel deadline enforcement.
            receipt["errors"].append(f"event_write_failed: {exc}")

    def bind(pid, can_terminate):
        process = process_factory(pid, can_terminate=can_terminate)
        handles.append(process)
        return process

    def assert_identity(process, expected):
        if not expected.matches(process.identity()):
            raise OwnershipError(f"process_identity_mismatch: pid={expected.pid}")

    try:
        if os.getpid() in {
            config.owner_pid,
            config.ac.pid,
            config.sidecar.pid if config.sidecar else 0,
        }:
            raise ValueError("watchdog must be independent of owner and target processes")
        stop_path = None
        if config.sidecar_stop_file is not None:
            stop_path = config.sidecar_stop_file.absolute()
            if (
                stop_path.parent.resolve() != run_dir
                or stop_path.exists()
                or stop_path.is_symlink()
            ):
                raise ValueError(
                    "sidecar stop file must be fresh and directly inside run directory"
                )
        original_owner = owner_reader(lock_path)
        if (
            not original_owner
            or type(original_owner.get("pid")) is not int
            or original_owner.get("pid") != config.owner_pid
        ):
            raise OwnershipError("canonical_owner_mismatch")
        owner = bind(config.owner_pid, False)
        owner_identity = owner.identity()
        receipt["owner_identity"] = asdict(owner_identity)
        # Phase may legitimately change, but a new run/owner record is never inherited.
        owner_key = {k: v for k, v in original_owner.items() if k != "phase"}

        def assert_owner():
            nonlocal cleanup_lock
            if cleanup_lock is not None:
                # This process retains the authoritative byte lock until handles are closed.
                # Re-reading our own byte lock is not a portable ownership test.
                return
            observed = owner_reader(lock_path)
            if owner.exited():
                if not armed or observed is not None:
                    raise OwnershipError("owner_exited_without_idle_lock_cleanup_grant")
                # Race-free takeover: a new owner winning after the read makes acquire fail.
                # The lease grants cleanup only; it never extends the driving deadline.
                lease = lock_factory(
                    lock_path,
                    owner=RigSessionOwner(
                        pid=os.getpid(),
                        cwd=str(Path.cwd()),
                        car=original_owner.get("car"),
                        track=original_owner.get("track"),
                        started_at=datetime.now(UTC).isoformat(),
                        session_kind="bounded_watchdog_cleanup",
                        phase="closing",
                    ),
                    timeout=0.0,
                )
                lease.acquire()
                cleanup_lock = lease
                record("owner_exit_cleanup_lock_acquired", original_owner_pid=config.owner_pid)
                return
            if not observed or {k: v for k, v in observed.items() if k != "phase"} != owner_key:
                raise OwnershipError("canonical_owner_lost_or_changed")
            assert_identity(owner, owner_identity)

        ac = bind(config.ac.pid, True)
        assert_identity(ac, config.ac)
        targets = [("ac", ac, config.ac)]
        if config.sidecar is not None:
            sidecar = bind(config.sidecar.pid, True)
            assert_identity(sidecar, config.sidecar)
            targets.append(("sidecar", sidecar, config.sidecar))
        assert_owner()
        if any(process.exited() for _, process, _ in targets):
            raise OwnershipError("target_exited_before_arming")
        # Exclusive durable publication is the parent's permission to enable the run.
        temporary_arm = output / "armed.tmp"
        with temporary_arm.open("x", encoding="utf-8") as file:
            json.dump({**receipt, "status": "armed", "reason": "fixed_deadline"}, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        temporary_arm.rename(output / "armed.json")
        armed = True
        record("armed")
        while True:
            assert_owner()
            if cleanup_lock is not None:
                trigger = "owner_exited"
                break
            if ac.exited():
                trigger = "ac_exited"
                break
            remaining = deadline - clock()
            if remaining <= 0:
                trigger = "deadline"
                break
            sleep(min(config.poll_s, remaining))
        record("shutdown_started", trigger=trigger)
        # Signal both explicit targets before waiting: sidecar grace runs concurrently with AC.
        for role, process, identity in targets:
            if process.exited():
                continue
            assert_owner()
            assert_identity(process, identity)
            try:
                if role == "sidecar":
                    with stop_path.open("x", encoding="utf-8") as file:
                        json.dump(
                            {"owner_pid": config.owner_pid, "sidecar_pid": identity.pid}, file
                        )
                        file.flush()
                        os.fsync(file.fileno())
                    record("stop_file_created", role=role)
                else:
                    record("graceful_close", role=role, windows=process.request_close())
            except OSError as exc:
                record("graceful_close_failed", role=role, detail=str(exc))
        grace_end = clock() + config.graceful_s
        while not all(process.exited() for _, process, _ in targets) and clock() < grace_end:
            assert_owner()
            sleep(max(0.0, min(config.poll_s, grace_end - clock())))
        forced = []
        for role, process, identity in targets:
            if process.exited():
                continue
            assert_owner()
            assert_identity(process, identity)
            try:
                process.terminate()
                forced.append(role)
                record("terminate_retained_handle", role=role)
            except OSError as exc:
                # One denied target must not strand another explicitly owned child. Its
                # unsignaled handle still makes the bounded final verdict fail.
                record("terminate_failed", role=role, detail=str(exc))
        terminate_end = clock() + config.terminate_s
        while not all(process.exited() for _, process, _ in targets) and clock() < terminate_end:
            sleep(max(0.0, min(config.poll_s, terminate_end - clock())))
        exited = {role: process.exited() for role, process, _ in targets}
        receipt.update(
            status="complete" if all(exited.values()) else "failed",
            reason=trigger if all(exited.values()) else "shutdown_timeout",
            forced=forced,
            exited=exited,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt.update(status="failed", reason=str(exc))
        record("failed", detail=str(exc))
    finally:
        try:
            for process in reversed(handles):
                process.close()
        finally:
            if cleanup_lock is not None:
                cleanup_lock.release()
                record("cleanup_lock_released")
    receipt["finished_monotonic_s"] = clock()
    if receipt["errors"]:
        receipt["status"] = "failed"
    with (output / "receipt.json").open("x", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    return receipt


def start_watchdog(
    config: WatchdogConfig, *, popen=subprocess.Popen, clock=time.monotonic, sleep=time.sleep
) -> dict:
    """Detach a console-independent watchdog and wait at most five seconds for arming.

    No startup timeout ever kills the guardian: it may already be protecting a run.
    The caller must not enable driving unless this function returns its armed receipt.
    Startup requires Windows Job breakaway; if the host disallows it, fail without
    fallback. The worker also verifies that it is not inside a remaining parent Job.
    """
    if sys.platform != "win32":
        raise OSError("rig watchdog requires Windows")
    run_dir = config.run_dir.resolve(strict=True)
    if (run_dir / "watchdog").exists():
        raise FileExistsError("watchdog directory already exists; cannot reset its deadline")
    args = [
        # Windows virtualenv's redirector creates its own Job and child interpreter.
        # This stdlib-only worker uses the base interpreter directly so its retained
        # Popen PID is the worker PID and the independent-job check remains meaningful.
        getattr(sys, "_base_executable", sys.executable),
        "-B",
        "-m",
        "tools.ac_harness.rig_watchdog",
        "run",
        "--owner-pid",
        str(config.owner_pid),
        "--run-dir",
        str(run_dir),
        "--max-runtime-s",
        str(config.max_runtime_s),
        "--graceful-s",
        str(config.graceful_s),
        "--terminate-s",
        str(config.terminate_s),
        "--poll-s",
        str(config.poll_s),
    ]
    for role, identity in (("ac", config.ac), ("sidecar", config.sidecar)):
        if identity is not None:
            args.extend(
                [
                    f"--{role}-pid",
                    str(identity.pid),
                    f"--{role}-created-filetime",
                    str(identity.created_filetime),
                    f"--{role}-exe",
                    identity.exe,
                ]
            )
    if config.sidecar_stop_file is not None:
        args.extend(["--sidecar-stop-file", str(config.sidecar_stop_file.absolute())])
    with (run_dir / "watchdog-launch.log").open("x", encoding="utf-8") as log:
        child = popen(
            args,
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB.
            # No fallback to a guardian tied to the launching tool's job lifetime.
            creationflags=0x00000008 | 0x00000200 | 0x01000000,
        )
    deadline = clock() + 5.0
    arm_file = run_dir / "watchdog/armed.json"
    final_file = run_dir / "watchdog/receipt.json"
    while clock() < deadline:
        if child.poll() is not None or final_file.exists():
            raise RuntimeError(f"watchdog failed before activation; inspect {run_dir / 'watchdog'}")
        if arm_file.exists():
            armed = json.loads(arm_file.read_text(encoding="utf-8"))
            if (
                armed.get("watchdog_pid") == child.pid
                and armed.get("status") == "armed"
                and armed.get("deadline_monotonic_s", 0) > clock()
            ):
                return armed
            raise RuntimeError("watchdog armed receipt does not match live child/deadline")
        sleep(min(0.05, max(0.0, deadline - clock())))
    raise RuntimeError(
        f"watchdog startup unconfirmed, PID {child.pid}; driving must remain disabled"
    )


def main(argv=None, *, scheduler_context=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="read-only exact process identity")
    inspect.add_argument("--pid", type=int, required=True)
    for command in ("start", "run", "scheduled-run"):
        run = commands.add_parser(
            command, help="detach and arm" if command == "start" else "worker"
        )
        run.add_argument("--owner-pid", type=int, required=True)
        run.add_argument("--run-dir", type=Path, required=True)
        run.add_argument("--max-runtime-s", type=float, default=MAX_RUNTIME_S)
        run.add_argument("--graceful-s", type=float, default=15.0)
        run.add_argument("--terminate-s", type=float, default=5.0)
        run.add_argument("--poll-s", type=float, default=0.25)
        for role in ("ac", "sidecar"):
            required = role == "ac"
            run.add_argument(f"--{role}-pid", type=int, required=required)
            run.add_argument(f"--{role}-created-filetime", type=int, required=required)
            run.add_argument(f"--{role}-exe", required=required)
        run.add_argument("--sidecar-stop-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        process = WindowsProcess(args.pid)
        try:
            print(json.dumps(asdict(process.identity())))
        finally:
            process.close()
        return 0
    sidecar_fields = (args.sidecar_pid, args.sidecar_created_filetime, args.sidecar_exe)
    if any(value is not None for value in sidecar_fields) and any(
        value is None for value in sidecar_fields
    ):
        parser.error("all three sidecar identity fields are required together")
    config = WatchdogConfig(
        owner_pid=args.owner_pid,
        ac=ProcessIdentity(args.ac_pid, args.ac_created_filetime, args.ac_exe),
        run_dir=args.run_dir,
        max_runtime_s=args.max_runtime_s,
        graceful_s=args.graceful_s,
        terminate_s=args.terminate_s,
        poll_s=args.poll_s,
        sidecar=ProcessIdentity(*sidecar_fields) if args.sidecar_pid is not None else None,
        sidecar_stop_file=args.sidecar_stop_file,
    )
    if args.command == "run":
        require_independent_worker()
    if args.command == "scheduled-run" and scheduler_context is None:
        parser.error("scheduled-run requires the verified canonical Task Scheduler action")
    result = (
        start_watchdog(config)
        if args.command == "start"
        else run_watchdog(config, lifetime_basis=scheduler_context)
    )
    print(json.dumps({"status": result["status"], "reason": result["reason"]}))
    return 0 if result["status"] in {"armed", "complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
