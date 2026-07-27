"""Run a harness command in the rig's **console session** from an off-rig SSH login (#697).

An OpenSSH logon on the rig is a *network* logon and lands in Windows **session 0**. Two
independent consequences make a session-0 harness run impossible, and neither is a harness bug
(#693):

1. Session 0 enforces the redirection-trust mitigation, so it refuses to traverse the non-admin
   ``apps/lua/ac_copilot_trainer`` junction. The #575 app-provenance preflight is the first code to
   touch it, so the run dies with ``OSError: [WinError 448] … untrusted mount point`` and *looks*
   like a harness defect.
2. Session 0 has no interactive desktop; Assetto Corsa renders on the console session.

The working transport is a ``schtasks /IT`` task ("run only when the user is logged on"), which
executes in the console session and needs no stored credential. PR #694 documented that as a
copy/paste runbook; five review rounds then found **six real Windows defects in a documentation
block**, which is the argument this module exists: the transport is intricate enough that every
off-rig session must not re-derive it by hand.

Every measured Windows fact from #693/#699 is encoded here as a guard that asserts its own
precondition, because the failure mode that costs a whole overnight run is a fail-*open* guard —
one that lets ``schtasks`` report ``create=0``/``run=0`` while the wrapper never executes:

* ``/tr`` gets the **8.3 short path**. A space anywhere in the path makes Task Scheduler accept the
  create and the run and then never launch the wrapper (``Last Result: -2147024894``). Quoting does
  not save it. :func:`short_path` therefore **raises** when 8.3 generation is disabled and the
  returned path still contains whitespace, rather than proceeding into a silent multi-hour wait.
* ``/sd`` is derived from the same ``datetime`` as ``/st`` and formatted ``MM/dd/yyyy``.
  ``/sc once`` defaults the start date to today, so a bare clock time computed after ~23:55 rolls
  to ``00:xx`` and is read as earlier *today* — ``/create`` then fails precisely during the
  overnight runs this path exists for. The *culture* short-date pattern is **not**
  interchangeable: ``M/d/yyyy``, ``dd/MM/yyyy`` and ``yyyy/MM/dd`` were all rejected on the rig
  with ``0x80004005``.
  (``/sc ONDEMAND``, which would remove the date problem entirely, is also rejected.)
* The task name carries a **per-run** id (timestamp + pid + nonce). The threat model is two agents
  on one physical rig: a fixed name lets each clobber the other's registration, and same-second
  starts would otherwise collide. ``/f`` is still passed, because a duplicate ``create`` without it
  does not error — it *blocks* on the interactive "replace it?" prompt.
* Every token interpolated into the generated ``.cmd`` is validated first. ``cmd.exe`` parses ``<``
  and ``>`` as redirection, and ``&``/``|``/``^``/``%VAR%`` are injection inside a file Task
  Scheduler executes as the logged-on user.
* The wrapper is written **ASCII**; a non-ASCII path is mangled to ``?`` by the encoder, producing a
  wrapper whose ``cd /d`` and redirects point nowhere while ``schtasks`` still reports success.
* The wrapper sets ``PYTHONUNBUFFERED=1`` and passes ``-u``: redirected Python is otherwise fully
  buffered, so the poll surface looks hung for minutes on a perfectly healthy run.

Ownership arbitration is **not** duplicated here — the spawned harness takes the cross-worktree rig
lock itself (:mod:`tools.ac_harness.rig_lock`); :func:`poll_run` only *reports* the current owner so
a caller can see who holds the rig without racing for it.

The pure half (run ids, wrapper rendering, ``schtasks`` argv, status parsing) is unit-tested
off-rig; only the ``schtasks``/session calls are Windows-only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.ac_harness.rig_lock import default_rig_session_lock_path, read_rig_session_owner

#: Transport logs live beside (not inside) the harness's own evidence tree: the run directory holds
#: the wrapper and its redirected streams, the harness keeps owning ``--evidence-dir``.
RUN_DIR_RELPATH = (".scratch", "harness-remote")
#: Every task this module creates is named ``ac-harness-<run id>`` so a stale one is reapable by
#: prefix without touching unrelated scheduled tasks.
TASK_PREFIX = "ac-harness-"
STDOUT_NAME = "stdout.log"
STDERR_NAME = "stderr.log"
#: The wrapper appends ``[wrapper] exit=<rc>`` as its last act. Its presence — not the task's
#: ``Status`` — is what says the run finished: ``schtasks /run`` is asynchronous, so deleting the
#: task on ``Status: Ready`` alone can cancel a start that has not spawned yet.
SENTINEL_NAME = "wrapper.log"
SENTINEL_TOKEN = "exit="
RUN_JSON_NAME = "run.json"
#: Control file (the argv Task Scheduler will run) kept OUT of the repo's shared `.scratch` tree —
#: that tree is checked out per worktree, trivially discoverable, and the module already treats it
#: as untrusted. This lives beside the rig lock instead. Same-user isolation is not achievable on
#: this rig (every agent runs as the logged-on account), so this reduces exposure rather than
#: eliminating it; the real protection is that `_remote_exec` re-validates every token and spawns
#: without a shell.
CONTROL_NAME = "control.json"

#: ``/sd`` format measured as the only accepted one on the rig (see the module docstring).
SCHTASKS_DATE_FORMAT = "%m/%d/%Y"
SCHTASKS_TIME_FORMAT = "%H:%M"
#: The trigger never fires — ``/run`` starts the task on demand — but ``/sc once`` requires a start
#: time that is not in the past, so it is placed safely ahead.
DEFAULT_START_DELAY_MINUTES = 5

#: Run-id / task-name alphabet: safe as a Windows path component *and* a Task Scheduler name.
_RUN_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
#: Argv tokens accepted for the payload. The transport no longer builds a shell string — the
#: payload is spawned with ``shell=False`` — so this is defence in depth rather than quoting: it
#: keeps a tampered control file from smuggling anything exotic past
#: :func:`execute_control_file`'s re-validation. ``(``/``)`` stay allowed because AC setup names
#: legitimately contain them (``auto_drive._SETUP_NAME_RE``).
_WRAPPER_TOKEN_RE = re.compile(r"^[ !#$()*+,\-./0-9:;=?@A-Z\[\]_a-z{}~\\]+$")
#: Characters that must never appear in a path interpolated into the wrapper. ``%`` expands inside
#: double quotes, and ``"`` breaks out of them — both are legal ASCII in a Windows path, so an
#: ``isascii()`` check alone is not enough to keep ``cd /d``, the redirects, and the sentinel append
#: pointing where they were meant to.
_WRAPPER_PATH_FORBIDDEN = set('%"<>&|^\r\n\t')

#: The ONLY payload shape this transport will run. Token-level validation is not enough: argv
#: reaches the interpreter as a JSON string list, so no shell quoting is needed and `-c` plus a
#: bare expression (`;`, `()`, `+`, `chr(...)`) — or a plain script path — would be console-session
#: RCE from a tampered control file. The transport exists to run harness modules; anything else
#: fails closed.
_ALLOWED_PAYLOAD_MODULE_RE = re.compile(r"^tools\.ac_harness\.[A-Za-z0-9_]+$")
#: Exit code recorded when the console-session shim itself fails before/around the payload, so a
#: broken run reports a real failure instead of leaving poll/wait hanging until their deadline.
EXEC_FAILURE_RC = 253

_INVALID_SESSION = 0xFFFFFFFF


def control_dir_for(run_id: str, *, local_app_data: str | Path | None = None) -> Path:
    """Where a run's control file and exit sentinel live — **outside** the repo's scratch tree.

    ``.scratch`` is checked out per worktree, trivially discoverable, and this module already treats
    it as untrusted (forged ``run.json``, planted sentinels). Keeping the *control plane* there is
    what let a peer replace the scheduled command outright. Same-user isolation is not achievable on
    this rig — every agent runs as the logged-on account — so this reduces exposure rather than
    eliminating it; the hard part is done by :func:`execute_control_file`, which re-validates every
    token and spawns without a shell.
    """
    base = default_rig_session_lock_path(local_app_data=local_app_data).parent
    return base / "remote" / validate_run_component("run id", run_id)


class RemoteLaunchError(RuntimeError):
    """A transport precondition failed. Never raised for a harness-level (in-sim) failure."""

    def __init__(self, message: str, *, run: RemoteRun | None = None) -> None:
        super().__init__(message)
        #: Set when the payload is already LIVE despite the error, so the CLI can still emit the
        #: handle. Without it, automation parsing stdout never learns the run id and cannot
        #: poll/wait/cleanup a run that is genuinely underway.
        self.run = run


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested off-rig)
# ---------------------------------------------------------------------------


def harness_repo_root() -> Path:
    """Repo root of the checkout this module was imported from.

    Resolved locally rather than imported from :mod:`tools.ac_harness.auto_drive`: that module is
    the *payload* this transport launches, and pulling it in at import time would drag the whole
    in-sim harness (and its dependencies) into a wrapper whose only job is to hand an argv to Task
    Scheduler. Both live in ``tools/ac_harness/``, so ``parents[2]`` is the same root by
    construction.
    """
    return Path(__file__).resolve().parents[2]


def validate_wrapper_path(kind: str, path: Path) -> Path:
    """Reject a path that would rewrite the generated ``.cmd`` instead of sitting inside it."""
    text = str(path)
    if not text.isascii():
        raise RemoteLaunchError(
            f"non-ASCII {kind} {text!r} would be mangled to '?' by the ascii-encoded wrapper"
        )
    _reject_trailing_backslash(kind, text)
    bad = sorted(_WRAPPER_PATH_FORBIDDEN & set(text))
    if bad:
        raise RemoteLaunchError(
            f"unsafe {kind} {text!r}: contains {bad!r}. `%` expands even inside double quotes and "
            '`"` breaks out of them, so such a path can rewrite `cd /d`, the redirects, or the '
            "exit sentinel while schtasks still reports success."
        )
    return path


def validate_run_component(kind: str, value: str) -> str:
    """Reject a run-id fragment that could act as a path segment or a task-name metacharacter."""
    if not value or ".." in value or not _RUN_COMPONENT_RE.match(value):
        raise RemoteLaunchError(f"unsafe {kind} {value!r} (allowed: letters/digits/._-)")
    return value


def build_run_id(
    label: str,
    *,
    now: datetime,
    pid: int,
    nonce: int,
) -> str:
    """A per-run id that is unique across concurrent agents and safe in a path and a task name.

    Second resolution alone is not enough: two agents starting in the same second on the one rig
    would share the run directory, each overwriting the other's wrapper and task registration.
    """
    validate_run_component("run label", label)
    return f"{label}-{now:%Y%m%d-%H%M%S}-{pid}-{nonce}"


def _reject_trailing_backslash(kind: str, text: str) -> None:
    """Reject a trailing ``\\``.

    Kept after the move off a generated ``.cmd``: the Windows CRT argv parser still treats ``\\"``
    as an escaped quote wherever a value is later re-quoted (``schtasks /tr``, any downstream tool),
    and Windows paths and AC ids never need a trailing separator — so refusing costs nothing and
    removes a whole class of mis-parse.
    """
    if text.endswith("\\"):
        raise RemoteLaunchError(
            f"unsafe {kind} {text!r}: a trailing backslash escapes the closing quote in the "
            "Windows CRT argv parser, so the quoted region does not end where it appears to"
        )


def validate_payload_argv(argv: Sequence[str]) -> list[str]:
    """Accept only ``-m <allowlisted harness module> [args…]``.

    Rejects ``-c``, ``-`` (stdin), ``runpy``-style indirection and any first token that looks like a
    filesystem path — each of which turns a tampered control file back into arbitrary code in the
    console session, which is the whole thing this transport exists to prevent.
    """
    tokens = [validate_wrapper_token(str(t)) for t in argv]
    if len(tokens) < 2 or tokens[0] != "-m":
        raise RemoteLaunchError(
            f"payload argv must start with '-m <module>' (got {tokens[:2]!r}) — the transport runs "
            "harness modules, never -c, stdin, or a script path"
        )
    if not _ALLOWED_PAYLOAD_MODULE_RE.match(tokens[1]):
        raise RemoteLaunchError(
            f"module {tokens[1]!r} is not an allowlisted harness module "
            "(expected tools.ac_harness.<name>)"
        )
    return tokens


def validate_wrapper_token(token: str) -> str:
    """Reject an argv token that would become redirection or injection inside the wrapper."""
    if not token:
        raise RemoteLaunchError("empty argv token")
    _reject_trailing_backslash("argv token", token)
    if not _WRAPPER_TOKEN_RE.match(token):
        raise RemoteLaunchError(
            f"unsafe argv token {token!r}: only printable ASCII without quotes or "
            "cmd metacharacters (& | < > ^ %) may reach the generated .cmd"
        )
    return token


#: Placeholders a caller may use in the harness argv; substituted before token validation so the
#: payload can name the same run the transport does (e.g. ``--evidence-dir …/{run_id}``).
RUN_ID_PLACEHOLDER = "{run_id}"
RUN_DIR_PLACEHOLDER = "{run_dir}"


def substitute_run_placeholders(argv: Sequence[str], *, run_id: str, run_dir: Path) -> list[str]:
    """Resolve ``{run_id}`` / ``{run_dir}`` in the harness argv.

    Without this the payload is blind to the transport's run id: transport logs land under
    ``.scratch/harness-remote/<run id>/`` while the harness picks its own evidence directory name,
    so a crash in ``stderr.log`` cannot be correlated with the in-sim evidence it belongs to. (The
    PowerShell runbook this module replaced linked them by hand with ``--evidence-dir "$rel"``.)

    Substitution happens **before** :func:`validate_wrapper_token`, so the resolved value is
    validated like any other token rather than trusted for having come from us.
    """
    return [
        token.replace(RUN_ID_PLACEHOLDER, run_id).replace(RUN_DIR_PLACEHOLDER, str(run_dir))
        for token in argv
    ]


def task_name_for(run_id: str) -> str:
    """The scheduled-task name for a run id."""
    return f"{TASK_PREFIX}{validate_run_component('run id', run_id)}"


def schtasks_create_argv(
    *,
    task: str,
    tr_path: str,
    when: datetime,
    run_as: str,
) -> list[str]:
    """The ``schtasks /create`` argv.

    ``/st`` and ``/sd`` are derived from the **same** ``datetime`` so a start time that rolls past
    midnight carries the correct day; ``/it`` is what puts the task in the console session; ``/f``
    prevents the interactive "replace it?" prompt from blocking a non-interactive create.
    """
    return [
        "schtasks",
        "/create",
        "/tn",
        task,
        "/tr",
        tr_path,
        "/sc",
        "once",
        "/st",
        when.strftime(SCHTASKS_TIME_FORMAT),
        "/sd",
        when.strftime(SCHTASKS_DATE_FORMAT),
        "/ru",
        run_as,
        "/it",
        "/f",
    ]


def parse_task_status(text: str) -> dict[str, str]:
    """Pull ``Status`` / ``Last Result`` out of ``schtasks /query /fo list /v`` output."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in {"status", "last result"}:
            fields.setdefault(key.replace(" ", "_"), value.strip())
    return fields


def parse_sentinel(text: str) -> int | None:
    """The wrapper's exit code, or ``None`` while the run has not finished."""
    # FIRST valid `exit=` wins, not the last. The shim writes exactly one, exclusively-created, so
    # the earliest parsable value is the real one; scanning from the end let a peer append
    # `[wrapper] exit=0` after a genuine `exit=1` and hand automation a forged success.
    for line in text.splitlines():
        marker = line.find(SENTINEL_TOKEN)
        if marker >= 0:
            tail = line[marker + len(SENTINEL_TOKEN) :].strip()
            try:
                return int(tail)
            except ValueError:
                # Keep scanning older lines. Returning None here let a single garbled (or planted)
                # trailing `exit=` hide a real one, so wait/cleanup would believe a finished run
                # never ended — blocking non-force cleanup and reap until timeout.
                continue
    return None


@dataclass(frozen=True)
class RemoteRun:
    """Everything a later poll needs; persisted as ``run.json`` inside the run directory."""

    run_id: str
    task: str
    repo_root: str
    run_dir: str
    argv: list[str]
    started_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RemoteRun:
        return cls(
            run_id=str(payload["run_id"]),
            task=str(payload["task"]),
            repo_root=str(payload["repo_root"]),
            run_dir=str(payload["run_dir"]),
            argv=[str(a) for a in payload.get("argv", [])],
            started_at=str(payload.get("started_at", "")),
        )

    @property
    def directory(self) -> Path:
        return Path(self.run_dir)


# ---------------------------------------------------------------------------
# Windows-only transport
# ---------------------------------------------------------------------------


def current_session_id() -> int:
    """Windows session of this process (an SSH logon reports 0)."""
    import ctypes

    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(  # type: ignore[attr-defined]
        ctypes.c_ulong(os.getpid()), ctypes.byref(session)
    ):
        raise RemoteLaunchError("ProcessIdToSessionId failed")
    return int(session.value)


def console_session_id() -> int:
    """Session id of the physical console, or ``_INVALID_SESSION`` when nobody is logged on."""
    import ctypes

    return int(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())  # type: ignore[attr-defined]


def assert_transport_needed() -> tuple[int, int]:
    """Refuse when the task hop is pure overhead, and fail loudly when it cannot work.

    Returns ``(current session, console session)``.
    """
    current = current_session_id()
    console = console_session_id()
    if console == _INVALID_SESSION:
        raise RemoteLaunchError(
            "no active console session — nobody is logged on at the rig, so a /IT task can never "
            "run and AC has no desktop to render on. Log in at the rig first."
        )
    if current == console:
        raise RemoteLaunchError(
            f"already running in the console session ({current}); run the harness directly — "
            "the scheduled-task hop would be pure overhead"
        )
    return current, console


def resolve_short_path(path: Path, get_short) -> str:  # noqa: ANN001 - injected Win32 callable
    """Buffer-growth wrapper around ``GetShortPathNameW``; separated so it is testable off-Windows.

    A too-small buffer is **not** a failure: the call returns the REQUIRED length, so retry at that
    size rather than refusing a long-but-perfectly-valid repo/run path.
    """
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    size = get_short(str(path), buf, len(buf))
    if size >= len(buf):
        buf = ctypes.create_unicode_buffer(size + 1)
        size = get_short(str(path), buf, len(buf))
    if size == 0 or size >= len(buf):
        raise RemoteLaunchError(f"GetShortPathNameW failed for {path}")
    return buf.value


def short_path(path: Path) -> str:
    """The 8.3 short path for ``/tr``; **raises** rather than silently handing back a spaced path.

    ``GetShortPathNameW`` returns the long path unchanged when 8.3 name generation is disabled on
    the volume. Returning that would make ``schtasks`` report success and never launch the wrapper.
    """
    import ctypes
    from ctypes import wintypes

    get_short = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD
    resolved = resolve_short_path(path, get_short)
    if any(ch.isspace() for ch in resolved):
        raise RemoteLaunchError(
            f"8.3 short path unavailable (got {resolved!r}). Task Scheduler accepts a spaced /tr "
            "and then never launches it — use a space-free repo path or enable 8.3 name generation."
        )
    return resolved


def execute_control_file(run_id: str) -> int:
    """Run a prepared payload in the console session. Invoked by ``_remote_exec`` via ``/tr``.

    Everything load-bearing is **recomputed** from the validated run id rather than trusted from the
    control file: the interpreter, the working directory, the log paths and the sentinel path. Only
    the argv and the repo root come from disk, and both are re-validated here — so even a tampered
    control file cannot inject a command, only fail closed. The payload is spawned with
    ``shell=False``.
    """
    requested = validate_run_component("run id", run_id)
    try:
        return _execute_validated(requested)
    except BaseException as exc:
        # ALWAYS leave a sentinel. Without one, an unreadable control file, a rejected argv or a
        # missing interpreter left poll/wait spinning to their deadline and cleanup/reap refusing
        # to delete — the "unbounded wait with no diagnosis" the bounded wait exists to avoid.
        _record_exec_failure(requested, exc)
        raise


def _write_sentinel(run_id: str, rc: int, note: str = "") -> None:
    """Record the run's real exit code as the FIRST line, overwriting anything already there.

    The shim is the only legitimate writer, so a pre-existing sentinel has no standing — it was
    planted. **Truncating** rather than appending is what makes `parse_sentinel`'s first-wins rule
    trustworthy: an earlier forged `exit=0` is erased, and a later appended one loses. (Appending
    beneath a planted value, which the failure path used to do, silently handed the forgery the
    authoritative slot and undid the exclusive-create guard it was paired with.)
    """
    sentinel = sentinel_path_for(run_id)
    try:
        existed = sentinel.is_file()
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        with sentinel.open("w", encoding="utf-8") as fh:
            fh.write(f"[wrapper] {SENTINEL_TOKEN}{rc}\n")
            if note:
                fh.write(f"[wrapper] {note}\n")
            if existed:
                fh.write("[wrapper] a pre-existing sentinel was overwritten (not written by us)\n")
    except OSError:
        pass  # nothing further we can do; the caller still raises


def _record_exec_failure(run_id: str, exc: BaseException) -> None:
    _write_sentinel(run_id, EXEC_FAILURE_RC, note=f"{type(exc).__name__}: {exc}")


def _execute_validated(requested: str) -> int:
    control = control_dir_for(requested) / CONTROL_NAME
    try:
        payload = json.loads(control.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RemoteLaunchError(f"unreadable control file {control}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RemoteLaunchError(f"control file {control} is not an object")
    # repo_root is NOT taken from the control file. Validating its characters was not enough:
    # it selects the interpreter (`<repo_root>/.venv/Scripts/python.exe`) and the log directory, so
    # a forged control file could point execution at an arbitrary python and writes at an arbitrary
    # tree — the same class as the `-c` hole, one layer down. It is recomputed from THIS module's
    # own location, and a control file that disagrees is rejected rather than silently overridden.
    repo_root = harness_repo_root()
    declared = str(payload.get("repo_root", ""))
    if declared and Path(declared).resolve() != repo_root:
        raise RemoteLaunchError(
            f"control file {control} declares repo_root {declared!r} but this shim lives under "
            f"{repo_root} — refusing to run a payload aimed at another checkout"
        )
    argv = validate_payload_argv(payload.get("argv", []))

    run_dir = repo_root.joinpath(*RUN_DIR_RELPATH, requested)
    run_dir.mkdir(parents=True, exist_ok=True)
    interpreter = repo_root / ".venv" / "Scripts" / "python.exe"
    env = dict(os.environ, PYTHONUNBUFFERED="1", AC_HARNESS_REMOTE_RUN_ID=requested)
    with (
        (run_dir / STDOUT_NAME).open("w", encoding="utf-8", errors="replace") as out,
        (run_dir / STDERR_NAME).open("w", encoding="utf-8", errors="replace") as err,
    ):
        completed = subprocess.run(  # noqa: S603 - validated argv, shell=False, fixed interpreter
            [str(interpreter), "-u", *argv],
            cwd=str(repo_root),
            stdout=out,
            stderr=err,
            env=env,
            check=False,
        )
    _write_sentinel(requested, completed.returncode)
    return completed.returncode


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(argv), capture_output=True, text=True, check=False
    )


def start_run(
    argv: Sequence[str],
    *,
    label: str,
    repo_root: Path | None = None,
    now: datetime | None = None,
    run_as: str | None = None,
    start_delay_minutes: int = DEFAULT_START_DELAY_MINUTES,
    sleep=time.sleep,  # noqa: ANN001 - injectable for tests
) -> RemoteRun:
    """Create and start a per-run console-session task for ``argv``; returns its handle."""
    assert_transport_needed()
    root = (repo_root or harness_repo_root()).resolve()
    # schtasks reads the rig's LOCAL wall clock, so /st and /sd must be local — not UTC.
    moment = now or datetime.now(UTC).astimezone()
    run_id = build_run_id(
        label,
        now=moment,
        pid=os.getpid(),
        nonce=random.randrange(1000, 9999),  # noqa: S311
    )
    run_dir = root.joinpath(*RUN_DIR_RELPATH, run_id)
    # exist_ok=False on purpose: a per-run id should never collide, and REUSING a directory would
    # inherit whatever markers it already holds (a stale or planted sentinel), which is exactly the
    # vector the wrapper's start-marker guard exists to close. A collision is a loud error.
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        # main() only catches RemoteLaunchError; a bare FileExistsError would crash the CLI with a
        # traceback instead of the documented exit code.
        raise RemoteLaunchError(
            f"run directory {run_dir} already exists — refusing to reuse it (it could carry a "
            "stale or planted control/sentinel state)"
        ) from exc

    resolved_argv = substitute_run_placeholders(argv, run_id=run_id, run_dir=run_dir)
    validate_wrapper_path("repo root", root)
    # Validate at the boundary where the caller can still be told. Previously only
    # execute_control_file() applied the module allowlist, so `start -- -c print(1)` created a
    # control file, registered AND ran a task, and returned exit 0 — the rejection arrived later,
    # in the console session, where nobody was listening.
    resolved_argv = validate_payload_argv(resolved_argv)
    control = control_dir_for(run_id)
    control.mkdir(parents=True, exist_ok=True)
    (control / CONTROL_NAME).write_text(
        json.dumps({"repo_root": str(root), "argv": list(resolved_argv)}, indent=2) + "\n",
        encoding="utf-8",
    )

    task = task_name_for(run_id)
    account = run_as or os.environ.get("USERNAME") or ""
    if not account:
        raise RemoteLaunchError("cannot resolve the logged-on account for /ru (USERNAME unset)")
    run = RemoteRun(
        run_id=run_id,
        task=task,
        repo_root=str(root),
        run_dir=str(run_dir),
        argv=list(resolved_argv),
        started_at=moment.isoformat(timespec="seconds"),
    )
    # Persist the handle BEFORE anything can launch. If this write failed after `/run`, the payload
    # could already be live with the one-shot trigger still armed and no way for the caller to poll
    # or clean it up.
    (run_dir / RUN_JSON_NAME).write_text(
        json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8"
    )

    when = moment + timedelta(minutes=start_delay_minutes)
    # `/tr` runs the repo's own interpreter against a version-controlled shim — NOT a generated
    # script inside the agent-writable scratch tree. Executing that file was command injection: a
    # peer could replace it between /create and first execution and have Task Scheduler run
    # anything in the console session as the logged-on user.
    shim = Path(__file__).resolve().with_name("_remote_exec.py")
    tr_path = f"{short_path(root / '.venv' / 'Scripts' / 'python.exe')} {short_path(shim)} {run_id}"
    created = _run(schtasks_create_argv(task=task, tr_path=tr_path, when=when, run_as=account))
    if created.returncode != 0:
        # Nothing is registered, so reap_tasks will never find this run — discard its control
        # directory here or it leaks in the user's profile for every failed attempt.
        _discard_control_dir(run_id)
        raise RemoteLaunchError(
            f"schtasks /create failed ({created.returncode}): {created.stdout}{created.stderr}"
        )
    started = _run(["schtasks", "/run", "/tn", task])
    if started.returncode != 0:
        # /run failed, so nothing was launched and deleting cannot abort a live payload. The delete
        # itself must be checked though: a task left registered keeps its one-shot trigger armed and
        # fires ~start_delay later with no handle for anyone to poll or clean up.
        removed = _run(["schtasks", "/delete", "/tn", task, "/f"])
        detail = f"schtasks /run failed ({started.returncode}): {started.stdout}{started.stderr}"
        if removed.returncode == 0:
            _discard_control_dir(run_id)
        if removed.returncode != 0:
            detail += (
                f" — AND the cleanup delete failed ({removed.returncode}), so task {task!r} is "
                f"still registered with its one-shot trigger ARMED and will fire around "
                f"{when:%Y-%m-%d %H:%M}. Remove it by hand."
            )
        raise RemoteLaunchError(detail)
    # Disable the trigger now that the on-demand start has happened. `/sc once` is a REAL trigger:
    # left armed, it fires at its scheduled time and executes the payload a second time if the run
    # already finished. Disabling removes that class outright — no filesystem marker can do it,
    # because every marker lives somewhere a peer can write. A running instance is unaffected.
    # The payload is now LIVE. Disabling the one-shot trigger is still required, but a failure here
    # must NOT be "cleaned up" by deleting the task: this module documents that /run is asynchronous
    # and that deleting the definition can cancel a start still spawning — so the old fail-closed
    # delete could abort the very run it had just launched, while reporting the start as failed.
    # Retry, then surface the armed trigger loudly and leave the run (and its handle) intact.
    disabled = _run(["schtasks", "/change", "/tn", task, "/disable"])
    if disabled.returncode != 0:
        sleep(2.0)
        disabled = _run(["schtasks", "/change", "/tn", task, "/disable"])
    if disabled.returncode != 0:
        raise RemoteLaunchError(
            f"schtasks /change /disable failed ({disabled.returncode}): "
            f"{(disabled.stderr or disabled.stdout or '').strip()[:200]} — the run is ALREADY "
            f"RUNNING and its handle is at {run_dir / RUN_JSON_NAME}, so the task was NOT deleted "
            f"(that would abort it). The one-shot trigger is still ARMED and will re-fire around "
            f"{when:%Y-%m-%d %H:%M}: disable or delete task {task!r} before then.",
            run=run,
        )

    return run


def load_run(run_id: str, *, repo_root: Path | None = None) -> RemoteRun:
    """Rehydrate a run handle, **bound to the requested id and its canonical location**.

    ``run.json`` is an on-disk file in a world-writable scratch tree, so nothing in it may be
    trusted to name what this process acts on. Checking ``task`` against ``task_name_for(run_id)``
    using two fields *from the same payload* is not enough: a self-consistent forgery passes, and
    an unvalidated ``run_dir`` lets a planted ``[wrapper] exit=0`` sentinel make :func:`poll_run`
    report ``finished`` — after which ``cleanup`` deletes a **peer agent's** ``/IT`` task
    mid-launch, the exact shared-rig clobber this module exists to prevent.

    So the requested id is authoritative: the payload's ``run_id``/``task`` must equal what was
    asked for, and ``run_dir`` is **recomputed** from the canonical root rather than read.
    """
    root = (repo_root or harness_repo_root()).resolve()
    requested = validate_run_component("run id", run_id)
    run_dir = root.joinpath(*RUN_DIR_RELPATH, requested)
    payload = run_dir / RUN_JSON_NAME
    if not payload.is_file():
        raise RemoteLaunchError(f"no such remote run: {payload}")
    # The payload lives in a writable scratch tree, so treat it as untrusted INPUT, not as a
    # trusted structure: a truncated or hand-edited file must surface as the module's own error
    # (which the CLI turns into a clean exit 3), never as a JSONDecodeError/KeyError traceback.
    try:
        run = RemoteRun.from_dict(json.loads(payload.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RemoteLaunchError(
            f"unreadable run payload {payload}: {type(exc).__name__}: {exc}"
        ) from exc
    expected_task = task_name_for(requested)
    if run.run_id != requested:
        raise RemoteLaunchError(
            f"{payload} declares run_id {run.run_id!r} but was loaded as {requested!r} — "
            "refusing to act on a payload that names a different run"
        )
    if run.task != expected_task:
        raise RemoteLaunchError(
            f"{payload} declares task {run.task!r}, expected {expected_task!r} — "
            "refusing to act on a task this run id does not own"
        )
    # Recompute rather than trust: a payload-supplied run_dir could point at a planted sentinel.
    return replace(run, run_dir=str(run_dir))


#: Cap on how much of a log is read to satisfy a tail. A drive stage writes megabytes of relay
#: chatter to stderr, so reading whole files would make every poll scale with log size.
_TAIL_MAX_BYTES = 256 * 1024


def _tail(path: Path, lines: int) -> list[str]:
    """Last ``lines`` lines of a log, reading only the tail of the file.

    ``lines <= 0`` means **no tail** — it previously returned the *entire* file, and
    :func:`cleanup_run` calls :func:`poll_run` with ``tail=0``, so a cleanup could load and
    JSON-print megabytes of sidecar logs.
    """
    if lines <= 0:
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - _TAIL_MAX_BYTES)
            fh.seek(start)
            blob = fh.read()
    except OSError:
        return []
    text = blob.decode("utf-8", errors="replace")
    rows = text.splitlines()
    if start > 0 and len(rows) > 1:
        # The seek can land mid-line (and mid-codepoint), so drop that partial first row — but
        # ONLY when another row survives it. A chunk containing no newline at all (one very long
        # log line) is entirely "partial", and dropping it would report an empty tail for a
        # non-empty log, hiding exactly the diagnostics a poll is for.
        rows = rows[1:]
    return rows[-lines:]


def poll_run(run: RemoteRun, *, tail: int = 30) -> dict[str, Any]:
    """Read-only status: task fields, wrapper exit, log tails, ``acs.exe`` liveness, rig owner.

    Never touches AC and never deletes the task — a poll must be safe to run in a tight loop.
    """
    queried = _run(["schtasks", "/query", "/tn", run.task, "/fo", "list", "/v"])
    # Single sentinel reader: a permission/sharing error on wrapper.log must not abort a poll (and
    # therefore cleanup, which polls first) with a traceback.
    exit_code = _sentinel_exit_code(run.run_id)
    fields = parse_task_status(queried.stdout)
    # Same snapshot the fields below are reported from — a second query would both double the
    # subprocess cost per poll and let the reported status disagree with the verdict beside it.
    verified, verified_reason = evaluate_deletion(
        sentinel_exit_code=exit_code,
        query_rc=queried.returncode,
        fields=fields,
        run_id=run.run_id,
    )
    acs = _run(["tasklist", "/fi", "imagename eq acs.exe", "/nh"])
    return {
        "run_id": run.run_id,
        "task": run.task,
        "task_query_rc": queried.returncode,
        **fields,
        # `finished` is the RAW sentinel signal, kept for diagnosis. `verified_complete` is the
        # strict one (sentinel + known-dead status + a Last Result showing it actually ran) and is
        # what anything acting on the run must use — a peer can write into the scratch tree.
        "finished": exit_code is not None,
        "verified_complete": verified,
        "verified_reason": verified_reason,
        "exit_code": exit_code,
        "acs_running": "acs.exe" in acs.stdout.lower(),
        "rig_lock_owner": read_rig_session_owner(default_rig_session_lock_path()),
        "stdout_tail": _tail(run.directory / STDOUT_NAME, tail),
        "stderr_tail": _tail(run.directory / STDERR_NAME, min(tail, 10)),
    }


def wait_for_run(
    run: RemoteRun,
    *,
    timeout_s: float,
    interval_s: float = 30.0,
    sleep=time.sleep,  # noqa: ANN001 - injectable clock for tests
    monotonic=time.monotonic,  # noqa: ANN001
) -> dict[str, Any]:
    """Block until the wrapper writes its exit sentinel, or the bounded deadline passes.

    Completion is the same strict predicate :func:`cleanup_run` and :func:`reap_tasks` use, not the
    bare presence of an exit sentinel.

    The wait is bounded on purpose: when the run never starts the sentinel never appears, and an
    unbounded loop would hang forever with no diagnosis.
    """
    for label, value in (("timeout_s", timeout_s), ("interval_s", interval_s)):
        # argparse's `type=float` happily accepts `inf` and `nan`. With `inf` the deadline is never
        # reached, so the wait is unbounded — precisely the hang this function exists to prevent;
        # with `nan` every comparison is False and the sleep collapses toward a busy spin.
        if not math.isfinite(value) or value < 0:
            raise RemoteLaunchError(
                f"{label} must be a finite, non-negative number (got {value!r})"
            )
    deadline = monotonic() + timeout_s
    while True:
        status = poll_run(run)
        # NOT `finished`: that is the raw sentinel, which a peer sharing this rig's writable
        # .scratch tree can plant — making an unattended `start --wait-timeout-s` exit 0 while the
        # /IT task is still launching. cleanup/reap already refuse that; the wait must too.
        if status["verified_complete"]:
            return status
        if monotonic() >= deadline:
            status["timed_out"] = True
            return status
        sleep(min(interval_s, max(0.0, deadline - monotonic())))


def _discard_control_dir(run_id: str) -> None:
    """Remove a run's control directory once its task is gone.

    Run ids are unique per attempt, so without this every single run permanently leaks a folder
    (control file + sentinel) into the user's profile.
    """
    try:
        control = control_dir_for(run_id)
    except RemoteLaunchError:
        return  # unvalidatable id — nothing of ours to remove
    # Delete only the two files this module writes, then rmdir. A recursive delete would remove
    # peer-planted content in a directory this module itself documents as peer-writable, and
    # `ignore_errors=True` would swallow the very failure that means the leak is still there.
    for name in (CONTROL_NAME, SENTINEL_NAME):
        with contextlib.suppress(FileNotFoundError):
            (control / name).unlink()
    with contextlib.suppress(FileNotFoundError, OSError):
        control.rmdir()  # refuses if anything unexpected remains — deliberately not forced


def _await_deletion_verdict(
    name: str,
    run_id: str,
    *,
    attempts: int = 4,
    delay_s: float = 2.0,
    sleep=time.sleep,  # noqa: ANN001 - injectable clock for tests
) -> tuple[bool, str]:
    """:func:`task_deletion_verdict` with a short retry for the end-of-wrapper race.

    Immediately after ``wait_for_run`` returns, the sentinel exists but Task Scheduler may still
    report ``Running`` for a moment while it reaps the wrapper. That is a legitimate transient, not
    a live peer — so retry briefly rather than refusing a caller who did everything right.
    """
    reason = ""
    for attempt in range(attempts):
        ok, reason = task_deletion_verdict(name, run_id)
        if ok:
            return True, ""
        if attempt < attempts - 1:
            sleep(delay_s)
    return False, reason


def cleanup_run(run: RemoteRun, *, force: bool = False) -> dict[str, Any]:
    """Delete the task once the wrapper has logged its exit code.

    Refuses on an unfinished run unless ``force``: ``/run`` is asynchronous, so deleting the task
    definition early can cancel a start that has not spawned yet, and it removes the only ``Status``
    handle while the run is still launching.
    """
    # The task name comes off disk (`run.json`), which a peer session or a stray edit can change.
    # Deleting whatever name it holds would let this reap another agent's task on the shared rig and
    # drop its Status handle mid-run, so bind the name to the run id before touching schtasks.
    expected = task_name_for(run.run_id)
    if run.task != expected:
        raise RemoteLaunchError(
            f"refusing to delete task {run.task!r}: it does not match this run id "
            f"(expected {expected!r}) — run.json may have been edited or points at a peer's task"
        )
    status = poll_run(run, tail=0)
    if not force:
        # Historically this required only the exit sentinel, which made it the WEAKER path than
        # reap despite the docs claiming the reverse: wrapper.log lives in the same agent-writable
        # tree run.json does, so a planted sentinel while the task was still Running would delete a
        # live /IT task and kill its console-session process tree. One shared rule now.
        ok, reason = _await_deletion_verdict(run.task, run.run_id)
        if not ok:
            return {"deleted": False, "reason": reason, **status}
    deleted = _run(["schtasks", "/delete", "/tn", run.task, "/f"])
    if deleted.returncode == 0:
        _discard_control_dir(run.run_id)
    return {"deleted": deleted.returncode == 0, "delete_rc": deleted.returncode, **status}


def list_stale_tasks() -> list[str]:
    """Task names this module owns that are still registered. Read-only — see :func:`reap_tasks`.

    Raises rather than returning an empty list when the query fails: an empty result is what an
    operator reads as "nothing left behind", so silently returning it on a failed ``schtasks`` call
    would let ``reap`` exit 0 with live registrations still on the rig.
    """
    queried = _run(["schtasks", "/query", "/fo", "list"])
    if queried.returncode != 0:
        raise RemoteLaunchError(
            f"schtasks /query failed (rc={queried.returncode}): "
            f"{(queried.stderr or queried.stdout or '').strip()[:200]} — refusing to report an "
            "empty task list, which would read as 'nothing left behind'"
        )
    names: list[str] = []
    for line in queried.stdout.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "taskname":
            name = value.strip().lstrip("\\")
            if name.startswith(TASK_PREFIX):
                names.append(name)
    return names


#: Task states that are known NOT to be mid-launch. Everything else — ``Running``, ``Queued``, an
#: unparseable status, or a failed query — is treated as possibly-live and skipped. ``Ready`` is in
#: this set only as a *secondary* signal: it is emphatically **not** proof of completion (see
#: :func:`reap_tasks`), which is why the sentinel check below is the primary gate.
_KNOWN_DEAD_TASK_STATES = {"ready", "disabled"}
#: ``Last Result`` values from ``schtasks``. ``Ready`` alone cannot distinguish "finished" from
#: "created but never started", so the *result* code separates them: a never-run task reports
#: ``SCHED_S_TASK_HAS_NOT_YET_RUN``. (``267009`` — currently running — was observed live on this
#: rig mid-drive.) Deliberately NOT compared against the wrapper's own exit code: the wrapper's
#: last command is ``echo``, so ``Last Result`` can be 0 while the harness rc was not.
SCHED_S_TASK_HAS_NOT_YET_RUN = 267011
SCHED_S_TASK_IS_CURRENTLY_RUNNING = 267009
#: `Last Result` values in 0x41300-0x41308 are Task Scheduler STATUS codes, not process exit codes.
#: Rejecting only "not yet run" and "currently running" left SCHED_S_TASK_READY (267008),
#: SCHED_S_TASK_DISABLED (267010) and the rest reading as "the payload ran and finished" — so the
#: third gate never actually proved execution. Anything in this range fails closed.
_SCHED_STATUS_RESULT_RANGE = range(0x41300, 0x41309)


def sentinel_path_for(run_id: str) -> Path:
    """Exit-sentinel path for a run id, outside the shared scratch tree."""
    return control_dir_for(run_id) / SENTINEL_NAME


def _sentinel_exit_code(run_id: str) -> int | None:
    """The recorded exit code for a run, or ``None`` when it has not finished.

    Keyed by **run id**, not by a directory: the sentinel lives in the control directory, so taking
    a log path here was structurally misleading — it made a global status check look local, and
    forced :func:`reap_tasks` to synthesise a fake path inside its own checkout to reap a peer's
    task.
    """
    sentinel = sentinel_path_for(run_id)
    try:
        if not sentinel.is_file():
            return None
        text = sentinel.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # A transient IO/permission failure must not abort a reap pass with a traceback (main()
        # only catches RemoteLaunchError). Unreadable == unproven == fail closed: the caller then
        # skips this task, which is the safe direction.
        return None
    return parse_sentinel(text)


def evaluate_deletion(
    *, sentinel_exit_code: int | None, query_rc: int, fields: dict[str, str], run_id: str
) -> tuple[bool, str]:
    """The deletion rule as a **pure** function over one already-taken snapshot.

    Split out from :func:`task_deletion_verdict` so a caller that has already queried the task and
    read the sentinel — :func:`poll_run` — reuses that snapshot instead of taking a second one. Two
    snapshots meant two ``schtasks`` subprocesses per poll *and*, worse, a reported
    ``status``/``last_result`` that could disagree with the verdict computed beside it.
    """
    if sentinel_exit_code is None:
        # Name the file actually consulted. The sentinel moved out of the log directory when the
        # control plane left `.scratch`; reporting the old path would send an operator to inspect a
        # file this check never reads — the exact class of misleading diagnostic being fixed here.
        return (
            False,
            f"no exit sentinel at {sentinel_path_for(run_id)} — may still be launching",
        )
    if query_rc != 0:
        return False, f"status query failed (rc={query_rc}) — failing closed"
    state = fields.get("status", "").strip().lower()
    if state not in _KNOWN_DEAD_TASK_STATES:
        return False, f"status {state!r} is not a known non-live state — failing closed"
    raw_result = fields.get("last_result", "").strip()
    try:
        last_result = int(raw_result, 0)
    except ValueError:
        return False, f"last result {raw_result!r} unreadable — failing closed"
    if last_result == SCHED_S_TASK_HAS_NOT_YET_RUN:
        return False, "task has not yet run (pre-spawn Ready window) — refusing to cancel a launch"
    if last_result == SCHED_S_TASK_IS_CURRENTLY_RUNNING:
        return False, "last result says the task is currently running — refusing to cancel it"
    if last_result in _SCHED_STATUS_RESULT_RANGE:
        return False, (
            f"last result 0x{last_result:X} is a Task Scheduler status code, not a process exit "
            "code — the payload's own completion is unproven, failing closed"
        )
    if last_result < 0:
        return False, (
            f"last result {last_result} is a launch failure (e.g. 0x{last_result & 0xFFFFFFFF:X}), "
            "so the payload never ran — failing closed"
        )
    if last_result != sentinel_exit_code:
        # Task Scheduler's Last Result is now the shim's own process exit code, which the shim sets
        # equal to the value it records. They can only disagree if something other than the shim
        # wrote the sentinel. (The old `.cmd` wrapper ended in `echo`, so this cross-check was not
        # available then; with the Python shim it is, and it binds the file to an off-disk signal.)
        return False, (
            f"exit sentinel says {sentinel_exit_code} but Task Scheduler's last result is "
            f"{last_result} — the sentinel was not written by this run's shim, failing closed"
        )
    return True, ""


def task_deletion_verdict(name: str, run_id: str) -> tuple[bool, str]:
    """May this task be deleted? Returns ``(ok, reason_when_not)``. **Fails closed.**

    Both :func:`cleanup_run` and :func:`reap_tasks` go through here so there is exactly one rule,
    and it is the strict one. Three independent things must all hold:

    1. **The wrapper wrote its exit sentinel.** ``schtasks /run`` is asynchronous, so nothing about
       the task's own state proves the run reached its end.
    2. **The task reports a known non-live status.** An unreadable, missing, or unrecognised status
       is *not* permission — a guard that fail-opens on a transient query failure removes a live
       peer task at the one moment the evidence is missing.
    3. **The task has actually executed.** ``Ready`` covers *both* the pre-spawn window and
       completion, so a sentinel planted in the writable scratch tree during the pre-spawn window
       would otherwise authorise deleting a peer's task before it ever ran.
    """
    exit_code = _sentinel_exit_code(run_id)
    if exit_code is None:
        # Short-circuit: no sentinel is already dispositive, so skip the subprocess entirely. This
        # is the common case while a run is in flight, and reap calls it once per registered task.
        return evaluate_deletion(sentinel_exit_code=None, query_rc=0, fields={}, run_id=run_id)
    queried = _run(["schtasks", "/query", "/tn", name, "/fo", "list", "/v"])
    return evaluate_deletion(
        sentinel_exit_code=exit_code,
        query_rc=queried.returncode,
        fields=parse_task_status(queried.stdout),
        run_id=run_id,
    )


def _run_id_for_task(name: str) -> str | None:
    """Run id behind a task name, or ``None`` when the name is not ours.

    Returns the id rather than a directory: reaping a peer's task must not depend on any path
    inside *this* checkout.
    """
    if not name.startswith(TASK_PREFIX):
        return None
    run_id = name[len(TASK_PREFIX) :]
    try:
        return validate_run_component("run id", run_id)
    except RemoteLaunchError:
        return None


def reap_tasks(*, force: bool = False) -> dict[str, Any]:
    """Delete still-registered tasks this module owns, using :func:`cleanup_run`'s own rule.

    ``list`` deliberately only reports; this is the command that actually removes them. A session
    that dies before ``cleanup`` leaves an accumulating registration behind, and without this the
    operator falls back to raw ``schtasks /delete`` — the hand-run path this module retires.

    The threat model is *two agents, one rig*, so this must obey exactly the rule
    :func:`cleanup_run` encodes and no weaker one:

    * **``Status: Ready`` is not completion.** ``schtasks /run`` is asynchronous, so a task reads
      ``Ready`` in the window between ``/create`` and ``/run``, and again after ``/run`` until the
      wrapper actually spawns. Deleting during either window cancels a peer's start and drops the
      only ``Status`` handle. The **exit sentinel** under the canonical
      ``.scratch/harness-remote/<run id>/`` — derived from the task name, never from an on-disk
      payload — is the authority, exactly as in :func:`cleanup_run`.
    * **Unknown status fails closed.** If ``/query`` errors, returns nothing, or yields a status
      this module does not recognise, the task is skipped rather than deleted. A guard that
      fail-*opens* on a transient query failure is worse than none: it silently removes a live peer
      task at the one moment the evidence is missing.

    ``force`` overrides both, and every skip is reported rather than silently swallowed.
    """
    results: dict[str, Any] = {}
    for name in list_stale_tasks():
        if not force:
            run_id = _run_id_for_task(name)
            if run_id is None:
                results[name] = {"deleted": False, "skipped": "task name is not a valid run id"}
                continue
            ok, reason = task_deletion_verdict(name, run_id)
            if not ok:
                results[name] = {"deleted": False, "skipped": reason}
                continue
        deleted = _run(["schtasks", "/delete", "/tn", name, "/f"])
        if deleted.returncode == 0 and name.startswith(TASK_PREFIX):
            _discard_control_dir(name[len(TASK_PREFIX) :])
        results[name] = {"deleted": deleted.returncode == 0, "rc": deleted.returncode}
    return {"reaped": results, "remaining": list_stale_tasks()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.ac_harness.remote_launcher",
        description=(
            "Run a harness command in the rig's console session from an off-rig SSH login (#697). "
            "Diagnosis of why this is needed: docs/10_Development/18_Autonomous_Harness.md."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create + run a console-session task for a harness argv")
    start.add_argument(
        "--label",
        default="harness",
        help="run-id prefix (letters/digits/._- only); e.g. alien-529-911-magione",
    )
    start.add_argument(
        "--wait-timeout-s",
        type=float,
        default=None,
        help="block until the wrapper exits (bounded); omit to return immediately",
    )
    start.add_argument(
        "--keep-task",
        action="store_true",
        help="do not delete the task after a completed --wait-timeout-s run",
    )
    start.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help=(
            "harness argv after `--`, without the interpreter (e.g. -m "
            "tools.ac_harness.auto_alien --car … --track …). {run_id}/{run_dir} are substituted, "
            "so --evidence-dir .scratch/harness-evidence/{run_id} correlates payload with transport"
        ),
    )

    for name, help_text in (
        ("poll", "read-only status for a run id"),
        ("cleanup", "delete the task for a finished run id"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("run_id")
        if name == "poll":
            cmd.add_argument("--tail", type=int, default=30)
        else:
            cmd.add_argument(
                "--force", action="store_true", help="delete even without the exit sentinel"
            )

    wait = sub.add_parser("wait", help="block (bounded) until a run writes its exit sentinel")
    wait.add_argument("run_id")
    wait.add_argument("--timeout-s", type=float, default=3 * 60 * 60)
    wait.add_argument("--interval-s", type=float, default=30.0)

    sub.add_parser("list", help="list this module's still-registered tasks (read-only)")
    reap = sub.add_parser(
        "reap", help="DELETE still-registered tasks this module owns (skips in-flight ones)"
    )
    reap.add_argument(
        "--force",
        action="store_true",
        help="delete without the sentinel/status checks — cancels a live launch, possibly a peer's",
    )
    return p


def _strip_separator(argv: list[str]) -> list[str]:
    return argv[1:] if argv and argv[0] == "--" else argv


def main(raw_args: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(raw_args)
    try:
        if args.command == "start":
            harness_argv = _strip_separator(list(args.argv))
            if not harness_argv:
                raise RemoteLaunchError("no harness argv given (pass it after `--`)")
            run = start_run(harness_argv, label=args.label)
            print(json.dumps(run.to_dict(), indent=2))
            if args.wait_timeout_s is None:
                return 0
            status = wait_for_run(run, timeout_s=args.wait_timeout_s)
            print(json.dumps(status, indent=2, default=str))
            if status.get("timed_out"):
                return 2
            rc = 0 if status.get("exit_code") == 0 else 1
            if not args.keep_task:
                cleaned = cleanup_run(run)
                print(json.dumps(cleaned, indent=2, default=str))
                # A refused or failed cleanup leaves a live task registration behind. On the
                # unattended path that must be visible in the exit code, exactly as the standalone
                # cleanup command reports it.
                if not cleaned.get("deleted") or cleaned.get("delete_rc", 0) != 0:
                    rc = rc or 1
            return rc
        if args.command == "poll":
            print(
                json.dumps(poll_run(load_run(args.run_id), tail=args.tail), indent=2, default=str)
            )
            return 0
        if args.command == "wait":
            status = wait_for_run(
                load_run(args.run_id), timeout_s=args.timeout_s, interval_s=args.interval_s
            )
            print(json.dumps(status, indent=2, default=str))
            return 2 if status.get("timed_out") else (0 if status.get("exit_code") == 0 else 1)
        if args.command == "cleanup":
            outcome = cleanup_run(load_run(args.run_id), force=args.force)
            print(json.dumps(outcome, indent=2, default=str))
            # A refusal ("still launching", "status unknown") and a failed `schtasks /delete` are
            # both outcomes automation must be able to see from the exit code alone.
            if not outcome.get("deleted") or outcome.get("delete_rc", 0) != 0:
                return 1
            return 0
        if args.command == "list":
            print(json.dumps(list_stale_tasks(), indent=2))
            return 0
        if args.command == "reap":
            outcome = reap_tasks(force=args.force)
            print(json.dumps(outcome, indent=2, default=str))
            return 0 if not outcome["remaining"] else 1
    except RemoteLaunchError as exc:
        # Emit the handle on stdout even on the error path when the payload is live, so automation
        # parsing JSON can still poll/wait/cleanup instead of scraping prose from stderr.
        if getattr(exc, "run", None) is not None:
            print(json.dumps(exc.run.to_dict(), indent=2))
        print(f"remote-launcher: {exc}", file=sys.stderr)
        return 3
    return 3


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())
