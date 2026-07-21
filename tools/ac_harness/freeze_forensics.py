"""Decide what a wedged ``acs.exe`` is actually doing: spinning, blocked, or still working.

#627 §6.1 blocks the upstream CSP bug report on one question — is the wedge a **livelock** (a
data-dependent loop that never converges) or something else? A single memory dump cannot answer it:
a thread moving very fast in a circle and a thread grinding through a long computation look
identical at one instant. The council's answer was "take two 4.8 GB dumps 10 s apart and diff
thread 0" — expensive, and it still only gives two points.

This module answers it from three cheap, independent signals:

``S1`` ``QueryThreadCycleTime`` per thread → **burning CPU vs blocked**. A blocked thread accrues
    ~0 cycles; a spinning one accrues ~a full core. This alone kills the deadlock explanation.
``S2`` RIP sampled from repeated NONINVASIVE ``cdb`` attaches → **tight loop vs long computation**.
    A long computation walks through code (RIP wanders); a tight loop pins RIP inside a few dozen
    bytes indefinitely.
``S3`` ``acpmf_graphics`` vs ``acpmf_physics`` packet ids, with an ``acs.exe`` liveness check →
    the #627 §2 discriminator, and the guard against trap §7.1 (shared-memory sections outlive
    ``acs.exe``, so a dead sim reads identical to a wedged one without the process check).

The decision over those signals is :func:`classify_forensics` — pure, so every branch is unit
tested off-rig. Collection is Windows/rig-only.

Two lessons from the 2026-07-19 session are encoded as explicit verdicts, because both were
mistakes made in practice:

* A session whose graphics packet ADVANCED during the diagnosis had recovered — it was a transient
  init stall, not a terminal wedge. Reported as ``NOT_WEDGED`` rather than quietly analysed. (I
  called such a trial a confirmed spin before reading the artifact; it was not.)
* Fewer than two successful RIP reads carries no information about wandering, so it must not fall
  through to ``LONG_COMPUTATION`` — the one verdict that would wrongly kill the livelock
  hypothesis. Reported as ``INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES``.
"""

from __future__ import annotations

import ctypes
import glob
import re
import subprocess
import time
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

#: cycles/second above which a thread counts as burning CPU. A modern core retires on the order of
#: 1e9 cycles/s, so a spin pins ~one core; an idle/blocked thread accrues essentially none.
DEFAULT_BURNING_CYCLES_PER_S = 2e8
#: RIP spread (bytes) within which the sampled instruction pointer counts as a tight loop rather
#: than a computation walking through code.
DEFAULT_TIGHT_LOOP_BYTES = 4096
#: RIP reads needed before "wandering" can be claimed at all.
MIN_RIP_SAMPLES = 2


class ForensicVerdict(StrEnum):
    """What the three signals together prove about a wedged process."""

    LIVELOCK_CONFIRMED = "livelock_confirmed"
    LONG_COMPUTATION = "long_computation"
    BLOCKED_NOT_SPIN = "blocked_not_spin"
    NOT_WEDGED = "not_wedged"
    NOT_RENDER_WEDGE = "not_render_wedge"
    INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES = "inconclusive_insufficient_rip_samples"


def classify_forensics(
    *,
    burning_cpu: bool,
    gfx_static: bool,
    phys_advancing: bool,
    rips: Sequence[int],
    tight_loop_bytes: int = DEFAULT_TIGHT_LOOP_BYTES,
) -> tuple[ForensicVerdict, str]:
    """Decide the verdict from the three signals. Pure — no I/O, no clock.

    The order of these checks is the whole design: each one rules out a cheaper explanation before
    the more expensive claim is allowed.

    ``rips`` is the observed instruction pointers themselves, not a pre-computed count and span.
    Passing those two separately made an inconsistent state representable — a caller could report
    "2 samples" with a ``None`` span, which fell through to ``LONG_COMPUTATION``, the single verdict
    that must never be reached without evidence. Deriving both here makes that unrepresentable.
    """
    observed = list(rips)
    span = rip_span(observed)
    if not gfx_static:
        return (
            ForensicVerdict.NOT_WEDGED,
            "the render packet ADVANCED during the diagnosis, so the session recovered — this was "
            "a transient stall, not a terminal wedge. Nothing here supports a livelock claim.",
        )
    if not phys_advancing:
        return (
            ForensicVerdict.NOT_RENDER_WEDGE,
            "graphics and physics are BOTH stopped. A #627 §2 render wedge keeps physics "
            "advancing, so this is a pause, a fully stopped sim, or a dead process — not a "
            "render-thread wedge.",
        )
    if not burning_cpu:
        return (
            ForensicVerdict.BLOCKED_NOT_SPIN,
            "the hottest thread is not consuming CPU, so the main thread is WAITING, not "
            "spinning. That is a block/deadlock — a different bug from the livelock hypothesis.",
        )
    if span is None:
        return (
            ForensicVerdict.INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES,
            f"only {len(observed)} RIP sample(s) were read (need >={MIN_RIP_SAMPLES}). CPU "
            "is burning, but spin-vs-long-computation cannot be decided: one sample carries no "
            "information about wandering. Re-run the capture against the still-live process.",
        )
    if span < tight_loop_bytes:
        return (
            ForensicVerdict.LIVELOCK_CONFIRMED,
            f"the main thread burns CPU while the render packet never advances, and RIP stays "
            f"inside a {span}-byte window across the sampling interval. A thread cannot "
            "be waiting with RIP on moving code: this is a tight loop that is not converging.",
        )
    return (
        ForensicVerdict.LONG_COMPUTATION,
        f"CPU is burning but RIP wanders across {span} bytes — the thread is walking "
        "through code, so this is a long finite computation rather than a tight loop.",
    )


def rip_span(rips: list[int]) -> int | None:
    """Spread of the observed instruction pointers, or ``None`` below the evidence threshold."""
    if len(rips) < MIN_RIP_SAMPLES:
        return None
    return max(rips) - min(rips)


# --------------------------------------------------------------------------------------
# Collection (Windows/rig-only).
# --------------------------------------------------------------------------------------

TH32CS_SNAPTHREAD = 0x00000004
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

#: WinDbg/cdb print 64-bit addresses either flat or with a backtick separator
#: (``rip=00007ff6`00001234``). Missing the backtick form would yield zero parsed RIPs and
#: silently degrade every diagnosis to INCONCLUSIVE.
_RIP_RE = re.compile(r"rip=([0-9a-f`]{16,17})", re.IGNORECASE)


def find_cdb() -> Path | None:  # pragma: no cover - rig-only
    """Locate ``cdb.exe`` without pinning a WinDbg version (a store update breaks a pinned path)."""
    for pattern in (
        r"C:\Program Files\WindowsApps\Microsoft.WinDbg_*\amd64\cdb.exe",
        r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return Path(hits[-1])
    return None


class _THREADENTRY32(ctypes.Structure):  # pragma: no cover - rig-only
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
    ]


def _kernel32():  # pragma: no cover - rig-only
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    k.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    k.OpenThread.restype = wintypes.HANDLE
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.QueryThreadCycleTime.restype = wintypes.BOOL
    k.QueryThreadCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def thread_ids(pid: int) -> list[int]:  # pragma: no cover - rig-only
    """Every thread id owned by ``pid``, in enumeration order."""
    k = _kernel32()
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        out: list[int] = []
        if not k.Thread32First(snap, ctypes.byref(entry)):
            return out
        while True:
            if entry.th32OwnerProcessID == pid:
                out.append(entry.th32ThreadID)
            if not k.Thread32Next(snap, ctypes.byref(entry)):
                break
        return out
    finally:
        k.CloseHandle(snap)


def sample_cycles(pid: int, window_s: float = 5.0) -> list[dict]:  # pragma: no cover - rig-only
    """Cycles/second per thread over ``window_s``, hottest first. The spin shows as one hot thread.

    NOTE for anyone validating this against a fixture: a Python venv launcher (``.venv\\Scripts\\
    python.exe``) re-spawns the real interpreter as a CHILD, so sampling the pid ``Popen`` returns
    measures a parked shim and reads 0 cycles/s. Resolve to the worker pid first. ``acs.exe`` has
    no such shim.
    """
    k = _kernel32()

    def cycles(tid: int) -> int | None:
        handle = k.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, tid)
        if not handle:
            return None
        try:
            value = ctypes.c_ulonglong(0)
            if not k.QueryThreadCycleTime(handle, ctypes.byref(value)):
                return None
            return value.value
        finally:
            k.CloseHandle(handle)

    tids = thread_ids(pid)
    first = {t: cycles(t) for t in tids}
    started = time.monotonic()
    time.sleep(window_s)
    elapsed = time.monotonic() - started

    rows: list[dict] = []
    for tid in tids:
        before, after = first.get(tid), cycles(tid)
        if before is None or after is None:
            continue
        rows.append({"tid": tid, "cycles_per_s": (after - before) / elapsed})
    rows.sort(key=lambda row: row["cycles_per_s"], reverse=True)
    return rows


@dataclass
class RipSample:
    """One noninvasive register/stack snapshot."""

    at: float
    rip: int | None
    stack: str
    raw: str = field(repr=False, default="")


def cdb_snapshot(
    pid: int, *, tid: int | None = None, timeout: float = 90.0
) -> RipSample:  # pragma: no cover - rig-only
    """One NONINVASIVE register+stack snapshot of ``tid``.

    ``-pv`` attaches without becoming the process's debugger, so detaching cannot terminate it —
    the wedged process is irreplaceable evidence. ``tid`` selects by OS thread id
    (``~~[0xTID]s``): ``~0s`` selects thread *index* 0, which in ``acs.exe`` is parked in an ntdll
    wait while the hot thread is elsewhere, making RIP appear to wander across gigabytes and
    misreporting a real livelock as a long computation.
    """
    cdb = find_cdb()
    if cdb is None:
        return RipSample(time.time(), None, "", "cdb.exe not found")
    select = f"~~[0x{tid:x}]s" if tid is not None else "~0s"
    command = [str(cdb), "-pv", "-p", str(pid), "-c", f"{select}; r; k; lm; qd"]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
        raw = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return RipSample(time.time(), None, "", "cdb timed out")
    match = _RIP_RE.search(raw)
    stack_lines: list[str] = []
    grabbing = False
    for line in raw.splitlines():
        if line.strip().startswith("#") or "Child-SP" in line:
            grabbing = True
        if grabbing and line.strip():
            stack_lines.append(line.rstrip())
        if grabbing and len(stack_lines) > 30:
            break
    return RipSample(
        time.time(), int(match.group(1), 16) if match else None, "\n".join(stack_lines), raw
    )
