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
    A long computation walks through code (RIP wanders); a tight loop pins RIP inside a small
    window across the whole sampling interval (the render packet is the independent progress
    check: a converging loop would let it advance).
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

import argparse
import ctypes
import glob
import json
import math
import os
import re
import subprocess
import sys
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
            "the hottest sampled thread is not consuming CPU, so nothing in the process is "
            "spinning hard enough to explain a wedge — the stalled path is WAITING, not "
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
            f"the hottest sampled thread burns CPU while the render packet never advances, and "
            f"its RIP stays inside a {span}-byte window across the sampling interval. Two "
            "residuals remain: (1) RIP locality alone cannot rule out a finite loop longer than "
            "that interval — the independent progress check is the render packet itself, which a "
            "converging loop would let advance; (2) S1/S2 sample the *hottest* thread, not a "
            "render-identified one, so a busy physics worker (physics keeps advancing under the "
            "#627 §2 signature) can supply both signals while the renderer is merely blocked — "
            "confirm the sampled thread's stack is render-side before treating this as the #627 "
            "livelock, or re-run against a render-stack TID. No sample shows progress: a tight "
            "loop with no observed convergence (re-run to confirm).",
        )
    return (
        ForensicVerdict.LONG_COMPUTATION,
        f"the hottest sampled thread burns CPU but RIP wanders across {span} bytes — that "
        "thread is walking through code, so this is a long finite computation rather than a "
        "tight loop (same hottest-thread residual as LIVELOCK_CONFIRMED).",
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


def parse_rip(raw: str) -> int | None:
    """First RIP register value in cdb output, or ``None`` when absent or unparseable.

    Single source of truth for the regex match, backtick strip, and hex conversion — the
    backtick form must be normalized *before* ``int(..., 16)`` or a matched address raises
    ``ValueError`` and aborts the whole capture.
    """
    match = _RIP_RE.search(raw)
    if match is None:
        return None
    try:
        return int(match.group(1).replace("`", ""), 16)
    except ValueError:
        return None


#: Token ``cdb_snapshot`` prints (via ``.printf``) immediately after the thread switch, carrying
#: the *actual* current OS thread id — the only proof the register/stack dump ran on the requested
#: thread. A failed ``~~[0xTID]s`` does not abort the ``-c`` script: cdb continues in the default
#: context (thread index 0, parked in an ntdll wait) and still prints registers, so without this
#: marker a wrong-thread RIP parses as real evidence and recreates the parked-thread misdiagnosis.
_TID_MARKER = "AC_TID"

#: Exact marker-value capture. A substring test would accept a requested tid that is a hex prefix
#: of the actual thread (``AC_TID=1a2b`` contains ``ac_tid=1a``), re-admitting the wrong-thread
#: transcript the marker exists to reject.
_TID_RE = re.compile(rf"{_TID_MARKER}=([0-9a-f]+)", re.IGNORECASE)


def selected_tid_confirmed(raw: str, tid: int) -> bool:
    """True only when the cdb transcript's post-switch marker names the requested OS thread."""
    match = _TID_RE.search(raw)
    return match is not None and int(match.group(1), 16) == tid


#: ``lm`` module-list header. The snapshot script runs ``r; k; lm; qd`` and the stack collector
#: must STOP here: the module listing names every loaded module — ``d3d11``, ``dxgi``,
#: ``nvwgf2um`` are loaded in ANY AC process — so letting it ride in the "stack" text would make
#: the render-hint match true for every candidate thread and neuter the render-TID preference
#: entirely (#647 review P1).
_LM_HEADER_RE = re.compile(r"^\s*start\s+end\s+module name\s*$", re.IGNORECASE)


def extract_stack(raw: str) -> str:
    """The ``k`` call-stack frames from a cdb transcript — and ONLY those.

    Collection starts at the ``k`` header (``#`` / ``Child-SP``), stops at the ``lm`` module-list
    header, and caps at ~30 frames so the sample stays a stack, not a transcript.
    """
    stack_lines: list[str] = []
    grabbing = False
    for line in raw.splitlines():
        if _LM_HEADER_RE.match(line):
            break
        if line.strip().startswith("#") or "Child-SP" in line:
            grabbing = True
        if grabbing and line.strip():
            stack_lines.append(line.rstrip())
        if grabbing and len(stack_lines) > 30:
            break
    return "\n".join(stack_lines)


def find_cdb() -> Path | None:  # pragma: no cover - rig-only
    """Locate ``cdb.exe`` without pinning a WinDbg version (a store update breaks a pinned path).

    Preference order (#630 Part G — the middle rung is what the rig actually has):

    1. The Windows Kits debugger — a plain executable with no package ACLs.
    2. The Store WinDbg's **app-execution alias** (``%LOCALAPPDATA%\\Microsoft\\WindowsApps\\
       cdbX64.exe``) — Windows creates it precisely so normal processes can launch the packaged
       binary. On this rig the SDK is installed WITHOUT the Debuggers feature and the package
       directory is ACL-opaque, so the alias is the only working entry point; the Part G
       self-test read 0 confirmed RIPs before this rung existed.
    3. The raw ``WindowsApps`` package glob — last because ``CreateProcess`` on it commonly fails
       package ACLs for a normal operator.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    candidates: list[str] = [
        r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
    ]
    if local_appdata:
        candidates.append(str(Path(local_appdata) / "Microsoft" / "WindowsApps" / "cdbX64.exe"))
    candidates.append(r"C:\Program Files\WindowsApps\Microsoft.WinDbg_*\amd64\cdb.exe")
    for pattern in candidates:
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
    """Cycles/second per thread over ``window_s``, hottest first.

    The hottest row is a *candidate* for S2, not a proof of render-thread identity. Under the
    #627 §2 wedge signature physics keeps advancing, so a legitimate physics worker can outrank a
    blocked renderer; the stack from :func:`cdb_snapshot` is what ties the candidate to (or rules
    it out of) the render path before :func:`classify_forensics` is trusted as a #627 livelock.

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


#: How long the best-effort thaw attach may run. Short on purpose — a stuck thaw must not
#: re-block the operator for the full sampling budget.
_THAW_TIMEOUT_S = 15.0


def thaw_cdb_command(cdb: Path, pid: int) -> list[str]:
    """Command that attaches noninvasively and immediately detaches (``qd``).

    Used after a timed-out primary attach: ``subprocess.run`` kills ``cdb`` before the trailing
    ``qd`` of the sampling script can run, and a killed ``-pv`` session does not reliably clear the
    suspend counts it applied. A follow-up ``qd`` is the cheapest way to thaw without becoming the
    process's debugger (which would risk terminating the evidence on detach).
    """
    return [str(cdb), "-pv", "-p", str(pid), "-c", "qd"]


def best_effort_thaw(cdb: Path, pid: int, *, timeout: float = _THAW_TIMEOUT_S) -> str:
    """Best-effort thaw of ``pid`` after a failed noninvasive attach. Never raises.

    Returns a short status token for the sample's ``raw`` field so a log can show whether the
    thaw was attempted and whether it completed. A zero exit is required for ``thaw=ok`` —
    ``subprocess.run`` returns normally on a nonzero exit, and treating that as success would
    claim the process was resumed when ``qd`` may never have run. Failures are otherwise
    swallowed: the capture already failed, and a second exception here would only hide that fact.
    """
    try:
        proc = subprocess.run(
            thaw_cdb_command(cdb, pid),
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return "thaw=timeout"
    except OSError as exc:
        return f"thaw=failed:{exc}"
    if proc.returncode != 0:
        # Keep the token short (it rides in RipSample.raw) but include enough of stderr that a
        # log shows *why* the thaw did not complete.
        err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
        if len(err) > 160:
            err = err[:157] + "..."
        detail = f" rc={proc.returncode}" + (f" err={err}" if err else "")
        return f"thaw=failed:{detail.strip()}"
    return "thaw=ok"


def cdb_snapshot(
    pid: int, *, tid: int, timeout: float = 90.0
) -> RipSample:  # pragma: no cover - rig-only
    """One NONINVASIVE register+stack snapshot of ``tid``.

    ``-pv`` attaches without becoming the process's debugger, so detaching cannot terminate it —
    the wedged process is irreplaceable evidence. ``tid`` is required and must be the OS thread id
    of the *hot* thread — the first row of :func:`sample_cycles`. There is no safe default:
    ``~0s`` selects thread *index* 0, which in ``acs.exe`` is parked in an ntdll wait while the hot
    thread is elsewhere, so a default would combine a parked thread's RIPs with the hot thread's
    CPU reading and fabricate both false livelocks and false long computations. The post-switch
    :data:`_TID_MARKER` line is checked before any parsing, because a failed thread switch does
    not abort the ``-c`` script — an unconfirmed transcript yields ``rip=None`` so the verdict
    stays at INCONCLUSIVE rather than convicting a parked thread.

    On ``TimeoutExpired``, :func:`best_effort_thaw` runs before returning: the primary ``-c`` script
    ends with ``qd``, but a hard-killed ``cdb`` never reaches it, and suspend counts can stick.
    """
    cdb = find_cdb()
    if cdb is None:
        return RipSample(time.time(), None, "", "cdb.exe not found")
    select = f"~~[0x{tid:x}]s"
    command = [
        str(cdb),
        "-pv",
        "-p",
        str(pid),
        "-c",
        f'{select}; .printf "{_TID_MARKER}=%x\\n", @$tid; r; k; lm; qd',
    ]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
        raw = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        thaw_status = best_effort_thaw(cdb, pid)
        return RipSample(time.time(), None, "", f"cdb timed out; {thaw_status}")
    except OSError as exc:
        # The binary can vanish or refuse CreateProcess (WindowsApps ACLs) between the glob and
        # exec — degrade to INCONCLUSIVE like every other capture failure, never crash the run.
        return RipSample(time.time(), None, "", f"cdb failed to start: {exc}")
    if not selected_tid_confirmed(raw, tid):
        return RipSample(time.time(), None, "", raw)
    return RipSample(time.time(), parse_rip(raw), extract_stack(raw), raw)


# --------------------------------------------------------------------------------------
# Part G (#630) — the runnable capture driver: S1 → TID selection → S2 → S3 → verdict.
# The evidence path used to live only in a bespoke .scratch harness, so during a real
# freeze the operator had to rebuild it from the module docstring. The decision helpers
# below are pure and unit-tested off-rig; ``main`` is the rig-only assembly.
# --------------------------------------------------------------------------------------

#: substrings that identify a RENDER-side stack. The #627 §2 signature keeps physics ADVANCING,
#: so a legitimately busy physics worker can outrank a wedged (or blocked) renderer on cycles
#: alone — S2 must target a render-stack thread when one is visible among the hot candidates.
RENDER_STACK_HINTS: tuple[str, ...] = (
    "accrenderingadv",  # CSP's renderer (OriginalFilename accRenderingAdv.dll)
    "dwrite",  # the same module's on-disk alias in the game folder (#627 §3.5 caveat)
    "d3d11",
    "dxgi",
    "nvwgf2um",  # NVIDIA D3D UMD
)


def select_capture_tid(candidates: Sequence[tuple[int, str]]) -> tuple[int, str]:
    """Pick the S2 target from ``(tid, stack_text)`` candidates ordered hottest-first.

    Prefers the hottest thread whose sampled stack shows the render path
    (:data:`RENDER_STACK_HINTS`) over the merely hottest thread — the residual explicitly
    flagged in :func:`classify_forensics`'s LIVELOCK reading. Falls back to the hottest
    candidate when no stack matches (an unconfirmed cdb transcript has an empty stack and
    simply never matches). Returns the tid plus a human-readable selection reason that the
    capture record carries, so a later reader can audit *why* this thread was diagnosed.
    """
    if not candidates:
        raise ValueError("candidates must not be empty")
    for tid, stack in candidates:
        lowered = stack.lower()
        matched = [hint for hint in RENDER_STACK_HINTS if hint in lowered]
        if matched:
            return tid, f"render-stack hint(s) {matched} in sampled stack"
    return candidates[0][0], "hottest thread (no render-stack hint in any sampled candidate stack)"


@dataclass(frozen=True)
class S3Result:
    """The #627 §2 discriminator evaluated over a capture's shared-memory observations."""

    gfx_static: bool
    phys_advancing: bool
    acs_alive_throughout: bool
    gfx_readings: tuple[int, ...]
    phys_readings: tuple[int, ...]

    @property
    def sufficient(self) -> bool:
        """Whether the discriminator can be claimed at all (two comparable readings per stream)."""
        return len(self.gfx_readings) >= 2 and len(self.phys_readings) >= 2


def s3_gate(s3: S3Result) -> tuple[str, str] | None:
    """Why S3 forbids classification, as ``(verdict_token, rationale)`` — or ``None`` when it may.

    Two distinct refusals (#647 review P1 — ``acs_alive_throughout`` must actually gate):

    * **insufficient** — fewer than two live-correlated readings per stream: nothing to compare.
    * **liveness gap** — enough readings, but the target pid was NOT alive across the whole
      capture. The retained readings then straddle a process exit/restart, and ``gfx_static`` +
      ``phys_advancing`` computed across two different process generations (or a corpse gap) can
      fabricate the exact wedge signature this instrument exists to prove. Mixed-generation
      evidence is corrupted evidence — no verdict.
    """
    if not s3.sufficient:
        return (
            "capture_failed_insufficient_s3",
            "fewer than two live-correlated readings per shared-memory stream — the §2 "
            "discriminator cannot be claimed (dead process, unreadable sections, or the "
            "§7.1 corpse guard discarded every sample). No verdict.",
        )
    if not s3.acs_alive_throughout:
        return (
            "capture_failed_liveness_gap",
            "the target pid was not alive at every observation — the retained readings straddle "
            "a process exit/restart, so the packet comparison may mix process generations and "
            "fabricate (or mask) the wedge signature. Re-run against a continuously-live pid. "
            "No verdict.",
        )
    return None


def evaluate_s3(samples: Sequence[tuple[int | None, int | None, bool]]) -> S3Result:
    """Evaluate ``(gfx_packet, phys_packet, acs_alive)`` observations. Pure — no I/O.

    Trap §7.1 corpse guard: a reading taken while ``acs.exe`` is NOT alive is **discarded**, not
    compared — ``acpmf_*`` sections outlive their creator, so a dead sim's pinned packet would
    read exactly like a wedge. ``gfx_static`` requires every retained graphics reading identical;
    any advance (or a regression = replaced session) means the session moved and the wedge claim
    dies. ``phys_advancing`` requires every ADJACENT retained pair to strictly increase — a
    regression mid-stream is a section/session reset, not advancement.
    """
    gfx: list[int] = []
    phys: list[int] = []
    alive_flags: list[bool] = []
    for gfx_packet, phys_packet, acs_alive in samples:
        alive_flags.append(acs_alive)
        if not acs_alive:
            continue
        if gfx_packet is not None:
            gfx.append(gfx_packet)
        if phys_packet is not None:
            phys.append(phys_packet)
    return S3Result(
        gfx_static=len(gfx) >= 2 and len(set(gfx)) == 1,
        # STRICTLY monotonic across every adjacent retained pair — an endpoint-only comparison
        # would read a regression like 100, 5, 200 (a section/session reset) as "advancing" and
        # let a discontinuous stream contribute the wedge signature (#647 review round 2).
        phys_advancing=len(phys) >= 2
        and all(later > earlier for earlier, later in zip(phys, phys[1:], strict=False)),
        acs_alive_throughout=bool(alive_flags) and all(alive_flags),
        gfx_readings=tuple(gfx),
        phys_readings=tuple(phys),
    )


def build_capture_record(
    *,
    pid: int,
    tid: int | None,
    tid_reason: str,
    cycles_rows: Sequence[dict],
    candidate_stacks: Sequence[tuple[int, str]],
    rips: Sequence[int],
    s3: S3Result,
    verdict: str,
    rationale: str,
    started_at_utc: str,
    elapsed_s: float,
) -> dict:
    """Assemble the machine-readable capture record (#627 §9.2 sibling for forensics runs).

    Everything a later reader needs to re-derive — or dispute — the verdict rides in the record:
    the raw signals, the thread-selection reason, and the RIP set itself (hex, so it can be diffed
    against a disassembly without re-parsing decimal).
    """
    return {
        "schema": "freeze-forensics-capture/v1",
        "started_at_utc": started_at_utc,
        "elapsed_s": round(elapsed_s, 3),
        "pid": pid,
        "selected_tid": tid,
        "tid_selection_reason": tid_reason,
        "cycles_top": [
            {"tid": row["tid"], "cycles_per_s": round(row["cycles_per_s"], 1)}
            for row in list(cycles_rows)[:10]
        ],
        "candidate_stack_heads": [
            {"tid": candidate_tid, "stack_head": stack.splitlines()[:6]}
            for candidate_tid, stack in candidate_stacks
        ],
        "rips_hex": [hex(rip) for rip in rips],
        "rip_span_bytes": rip_span(list(rips)),
        "s3": {
            "gfx_static": s3.gfx_static,
            "phys_advancing": s3.phys_advancing,
            "acs_alive_throughout": s3.acs_alive_throughout,
            "gfx_readings": list(s3.gfx_readings),
            "phys_readings": list(s3.phys_readings),
            "sufficient": s3.sufficient,
        },
        "verdict": verdict,
        "rationale": rationale,
    }


#: ``GetExitCodeProcess`` sentinel for a process that has not exited.
_STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_alive(pid: int) -> bool:  # pragma: no cover - rig-only
    """Whether the SPECIFIC target process is alive.

    An image-name check cannot bind evidence to one process generation (#647 review P1):
    ``acs.exe`` restarting mid-capture yields a same-named process whose readings must not be
    mixed with the wedged generation's. Open the pid itself and ask.
    """
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD(0)
        if not k.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        k.CloseHandle(handle)


def _read_s3_once(pid: int) -> tuple[int | None, int | None, bool]:  # pragma: no cover - rig-only
    """One correlated ``(gfx_packet, phys_packet, target_alive)`` observation.

    Liveness of the TARGET PID (not the image name — #647 review P1) is read immediately BEFORE
    **and re-checked AFTER** the shared-memory reads (#647 review round 2): the target can exit
    between the pre-check and the reads, in which case the persistent ``acpmf_*`` corpse would be
    returned as a live-correlated observation. A reading only counts as alive when the target was
    alive on both sides of it, so the §7.1 corpse guard in :func:`evaluate_s3` can trust the flag.
    """
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable

    alive_before = _pid_alive(pid)
    gfx: int | None = None
    phys: int | None = None
    try:
        reader = SharedMemoryReader(with_physics=True)
    except (SharedMemoryUnavailable, OSError):
        return None, None, alive_before and _pid_alive(pid)
    try:
        graphics = reader.read_graphics()
        physics = reader.read_physics()
        gfx = graphics.packet_id
        phys = physics.packet_id if physics else None
    except (SharedMemoryUnavailable, OSError):
        pass
    finally:
        reader.close()
    return gfx, phys, alive_before and _pid_alive(pid)


def _acs_pids() -> frozenset[int]:  # pragma: no cover - rig-only
    """Every running ``acs.exe`` pid (empty on enumeration failure)."""
    from tools.ac_harness.entry_launcher import running_process_ids

    try:
        return frozenset(running_process_ids("acs.exe", strict=True))
    except OSError:
        return frozenset()


def _acs_pid() -> int | None:  # pragma: no cover - rig-only
    # ``running_process_ids`` returns an unordered frozenset — it is not subscriptable, and
    # ``min`` keeps the pick deterministic if more than one acs.exe is somehow present
    # (#647 review round 2: ``pids[0]`` crashed the default no---pid path with a TypeError).
    pids = _acs_pids()
    return min(pids) if pids else None


def _self_test() -> int:  # pragma: no cover - rig-only
    """Validate the instrument against a known ground-truth spinner before trusting it.

    This is the check that caught the instrument reading **0 cycles/s on a deliberate spinner**
    (the venv ``python.exe`` shim re-spawns the real interpreter as a child, so sampling the
    ``Popen`` pid measured a parked launcher). The worker prints its OWN pid, which resolves the
    shim trap by construction. S1 must see the spin; S2 passes when >=2 confirmed RIP reads land
    (a Python bytecode loop does not guarantee a <4 KiB C-level window, so span is reported, not
    asserted).
    """
    spinner = "import os\nprint(os.getpid(), flush=True)\nwhile True:\n    pass\n"
    proc = subprocess.Popen([sys.executable, "-c", spinner], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        worker_pid = int(proc.stdout.readline().strip())
        print(f"self-test: spinner worker pid {worker_pid} (Popen pid {proc.pid})")
        rows = sample_cycles(worker_pid, 2.0)
        if not rows or rows[0]["cycles_per_s"] < DEFAULT_BURNING_CYCLES_PER_S:
            observed = rows[0]["cycles_per_s"] if rows else 0.0
            print(
                "SELF-TEST FAIL (S1): a deliberate spinner read "
                f"{observed:.3g} cycles/s — the instrument would call a spin a block. "
                "Do not trust a capture from this machine state."
            )
            return 1
        hot = rows[0]
        print(f"self-test: S1 OK — hottest tid {hot['tid']} at {hot['cycles_per_s']:.3g} cycles/s")
        rips: list[int] = []
        for _ in range(2):
            snapshot = cdb_snapshot(worker_pid, tid=hot["tid"], timeout=60.0)
            if snapshot.rip is not None:
                rips.append(snapshot.rip)
        span = rip_span(rips)
        if span is None:
            print(
                "SELF-TEST FAIL (S2): fewer than 2 confirmed RIP reads "
                f"({len(rips)}) — cdb missing or the thread-switch marker never confirmed. "
                "S1 is validated; RIP sampling is NOT."
            )
            return 1
        print(
            f"self-test: S2 OK — {len(rips)} confirmed RIP reads, span {span} bytes (informational)"
        )
        print("SELF-TEST OK: S1 spin detection and S2 RIP plumbing validated against ground truth")
        return 0
    finally:
        proc.kill()


def _repo_checkout_root() -> Path:
    """The checkout this module runs from — a FIXED approved output root, unlike the CWD.

    Anchoring on the module's own location (``tools/ac_harness/`` → two parents up) keeps the
    ``.scratch`` capture-artifact workflow working from any invocation directory, while an
    arbitrary caller CWD is never trusted as a write root (same boundary as PR #646's launcher
    fix — a CWD root is caller-controlled and therefore no boundary at all).
    """
    return Path(__file__).resolve().parents[2]


def _resolve_record_path(raw: Path, approved_roots: Sequence[Path]) -> Path:
    """Resolve the ``--json`` destination and require it inside an approved output root.

    #647 review: an absolute path or ``..`` traversal would let this rig tool create parent
    directories and overwrite arbitrary writable locations. Approved roots are the per-user
    Harness root (rig lock / presets) and the repo checkout root (gitignored ``.scratch``
    capture artifacts). A relative path still resolves against the caller's CWD — but it only
    passes when that resolution lands inside a fixed root.
    """
    resolved = raw.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved = resolved.resolve(strict=False)
    for root in approved_roots:
        anchored = root.resolve(strict=False)
        if resolved == anchored or anchored in resolved.parents:
            return resolved
    raise ValueError(
        f"--json destination {resolved} is outside every approved output root "
        f"({', '.join(str(root) for root in approved_roots)})"
    )


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and >= 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _write_record(record: dict, path: Path) -> None:  # pragma: no cover - rig-only
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"record -> {path}")
    except OSError as exc:
        print(f"WARNING: could not write capture record {path}: {exc}")


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only entrypoint
    parser = argparse.ArgumentParser(
        description=(
            "Freeze forensics capture (#627 §6.1): decide whether a wedged acs.exe is spinning, "
            "blocked, or still computing — S1 cycle sampling, S2 noninvasive RIP snapshots, "
            "S3 packet discriminator with the §7.1 corpse guard."
        )
    )
    parser.add_argument(
        "--pid",
        type=_positive_int,
        default=None,
        help="target acs.exe pid (default: discover; a non-acs pid is rejected because S3 reads "
        "AC's global shared memory)",
    )
    parser.add_argument(
        "--cycles-window",
        type=_positive_float,
        default=5.0,
        help="S1 sampling window seconds (default 5; must be > 0 — a near-zero window turns "
        "incidental cycle increments into an arbitrary burning-CPU rate)",
    )
    parser.add_argument(
        "--rip-samples",
        type=_non_negative_int,
        default=3,
        help="S2 snapshots of the selected thread (default 3)",
    )
    parser.add_argument(
        "--rip-interval",
        type=_non_negative_float,
        default=10.0,
        help="seconds between S2 snapshots (default 10; wandering needs time to show)",
    )
    parser.add_argument(
        "--candidates",
        type=_positive_int,
        default=3,
        help="hot threads whose stacks are inspected for render-path hints (default 3)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_path",
        help="also write the machine-readable capture record to this path",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="validate S1/S2 against a deliberate spinner and exit (no acs.exe involved)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    if args.json_path is not None:
        from tools.ac_harness.rig_lock import default_rig_session_lock_path

        try:
            args.json_path = _resolve_record_path(
                args.json_path,
                approved_roots=(default_rig_session_lock_path().parent, _repo_checkout_root()),
            )
        except ValueError as exc:
            print(f"CAPTURE ABORTED: {exc}")
            return 2

    started_wall = time.time()
    started = time.monotonic()
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall))

    if args.pid is not None:
        # S3 always reads AC's GLOBAL acpmf sections, so all three signals must describe the
        # same process (#647 review round 2): sampling an unrelated busy pid's S1/S2 next to a
        # wedged AC's S3 would fabricate an "ACS livelock" out of two different processes.
        # Instrument validation against a non-AC process is --self-test's job.
        if args.pid not in _acs_pids():
            print(
                f"CAPTURE ABORTED: --pid {args.pid} is not a running acs.exe process — S3 reads "
                "AC's global acpmf sections, so S1/S2/S3 must describe the same process "
                "(use --self-test to validate the instrument against a synthetic spinner)"
            )
            return 2
        pid = args.pid
    else:
        pid = _acs_pid()
    if pid is None:
        print("CAPTURE FAILED: no acs.exe process found")
        return 2

    s3_samples: list[tuple[int | None, int | None, bool]] = [_read_s3_once(pid)]
    print(f"capture: pid {pid}; S1 cycle sampling over {args.cycles_window:.1f}s ...")
    rows = sample_cycles(pid, args.cycles_window)
    if not rows:
        print("CAPTURE FAILED: no thread cycle data (process gone or access denied)")
        return 2
    s3_samples.append(_read_s3_once(pid))

    candidate_stacks: list[tuple[int, str]] = []
    candidate_rips: dict[int, list[int]] = {}
    for row in rows[: args.candidates]:
        snapshot = cdb_snapshot(pid, tid=row["tid"])
        candidate_stacks.append((row["tid"], snapshot.stack))
        if snapshot.rip is not None:
            candidate_rips.setdefault(row["tid"], []).append(snapshot.rip)
        s3_samples.append(_read_s3_once(pid))
    tid, tid_reason = select_capture_tid(candidate_stacks)
    hot_cycles = next(row["cycles_per_s"] for row in rows if row["tid"] == tid)
    print(f"capture: selected tid {tid} ({tid_reason}); {hot_cycles:.3g} cycles/s")

    rips: list[int] = list(candidate_rips.get(tid, []))
    for index in range(args.rip_samples):
        if index or rips:
            time.sleep(args.rip_interval)
        snapshot = cdb_snapshot(pid, tid=tid)
        if snapshot.rip is not None:
            rips.append(snapshot.rip)
        else:
            note = snapshot.raw if len(snapshot.raw) < 120 else snapshot.raw[:117] + "..."
            print(f"capture: S2 snapshot {index + 1} unconfirmed/unreadable ({note})")
        s3_samples.append(_read_s3_once(pid))

    s3 = evaluate_s3(s3_samples)
    refusal = s3_gate(s3)
    if refusal is not None:
        verdict_token, refusal_rationale = refusal
        record = build_capture_record(
            pid=pid,
            tid=tid,
            tid_reason=tid_reason,
            cycles_rows=rows,
            candidate_stacks=candidate_stacks,
            rips=rips,
            s3=s3,
            verdict=verdict_token,
            rationale=refusal_rationale,
            started_at_utc=started_utc,
            elapsed_s=time.monotonic() - started,
        )
        print(json.dumps(record, indent=2))
        if args.json_path is not None:
            _write_record(record, args.json_path)
        return 2

    verdict, rationale = classify_forensics(
        burning_cpu=hot_cycles >= DEFAULT_BURNING_CYCLES_PER_S,
        gfx_static=s3.gfx_static,
        phys_advancing=s3.phys_advancing,
        rips=rips,
    )
    record = build_capture_record(
        pid=pid,
        tid=tid,
        tid_reason=tid_reason,
        cycles_rows=rows,
        candidate_stacks=candidate_stacks,
        rips=rips,
        s3=s3,
        verdict=str(verdict),
        rationale=rationale,
        started_at_utc=started_utc,
        elapsed_s=time.monotonic() - started,
    )
    print(json.dumps(record, indent=2))
    if args.json_path is not None:
        _write_record(record, args.json_path)
    print(f"VERDICT: {verdict} — {rationale}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
