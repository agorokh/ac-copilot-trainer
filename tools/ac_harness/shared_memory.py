"""AC shared-memory oracle — on-track-entry detector (EPIC #154 L2 "shared-memory oracle").

This module answers, deterministically and Content-Manager-independently, the one
question the autonomous self-test harness needs before it can assert anything about a
drive: **"is car 0 actually on track and driving, or still sitting on the pre-drive
menu / in the pits?"**

Why this exists (research workflow ``wojtj94jq``, cross-confirmed against Content
Manager's open source — ``AcManager.Tools/GameProperties/ImmediateStart.cs`` and
``SharedMemory/AcSharedMemory.cs`` — and the CSP changelogs): the pre-drive menu-skip
is a *timing/state race*, not a setting. There is **no CSP/CM config knob** for it, and
whether the skip lands depends on prior pit state. CM's own reliable approach is to
*poll shared memory and watch for the* ``AC_STATUS`` *PAUSE(3)→LIVE(2) +* ``IsInPit``
*transition* rather than hope a single skip fires inside the new-menu readiness window.
This module is the harness-side version of that detector. It is:

* the **detect half** of a future deterministic detect-and-retry launcher, and
* the **L2 success oracle** the #154 decision already requires
  ("WS tap + shared-memory oracle + vision oracle").

Design split (so CI on the Mac can verify the logic with zero Assetto Corsa / Windows):

* :func:`parse_graphics` / :func:`parse_physics` — **pure** ``bytes`` → snapshot. Tested
  on any OS with synthetic buffers built at the exact documented offsets.
* :class:`DrivingEntryDetector` — a **pure** state machine mirroring CM's loop (LIVE and
  not-in-pit, sustained across N reads, with a physics-``packetId`` stagnation guard for
  the "AC forgot to set Pause" case CM documents). Tested with synthetic sequences and an
  injected clock.
* :func:`open_shared_memory` / :class:`SharedMemoryReader` — the **Windows-only** mmap
  plumbing, guarded so it raises a clear :class:`SharedMemoryUnavailable` off-Windows or
  when AC is not running. Not exercised by CI; validated on the rig via the live-probe.

Run the live-probe on the AC PC (stdlib-only, no ``lupa`` needed)::

    python tools/ac_harness/shared_memory.py            # poll until driving detected

It prints ``AC_STATUS`` / ``IsInPit`` / packetIds each poll so the ``IsInPit`` byte
offset can be confirmed on this CSP build (see :data:`GRAPHICS_IS_IN_PIT_OFFSET`).
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

# ---------------------------------------------------------------------------
# acpmf_graphics layout (classic Assetto Corsa SPageFileGraphic, Pack=4, CharSet=Unicode).
#
# Offsets cross-confirmed by two independent sources: Content Manager's
# AcManager.Tools/SharedMemory/AcSharedGraphics.cs and mdjarv/assettocorsasharedmemory.
# Only the prefix up to IsInPit is needed; the 15-wchar (30-byte) string fields are skipped
# by arithmetic, not parsed:
#   int   packetId          @ 0
#   int   status            @ 4   (AcGameStatus enum)
#   int   session           @ 8
#   wchar currentTime[15]   @ 12  (30 bytes)
#   wchar lastTime[15]      @ 42
#   wchar bestTime[15]      @ 72
#   wchar split[15]         @ 102
#   int   completedLaps     @ 132
#   int   position          @ 136
#   int   iCurrentTime      @ 140
#   int   iLastTime         @ 144
#   int   iBestTime         @ 148
#   float sessionTimeLeft   @ 152
#   float distanceTraveled  @ 156
#   int   isInPit           @ 160   <-- Win32 BOOL (4 bytes); nonzero == in pit
#
# IsInPit @ 160 is GROUNDED in those two sources but must be CONFIRMED ONCE on this CSP
# build via the live-probe — a CSP UI reskin or struct revision could shift it. It is a
# named constant precisely so that confirmation is a one-line change.
# ---------------------------------------------------------------------------
GRAPHICS_PACKET_ID_OFFSET = 0
GRAPHICS_STATUS_OFFSET = 4
GRAPHICS_IS_IN_PIT_OFFSET = 160
# Minimum bytes that must be readable to decode every field above (isInPit + its 4 bytes).
GRAPHICS_MIN_BYTES = GRAPHICS_IS_IN_PIT_OFFSET + 4  # 164

# acpmf_physics (SPageFilePhysics): the only field used here is the leading packetId,
# whose stagnation distinguishes a genuinely-live frame from a paused/menu frame that AC
# left flagged LIVE (AcSharedMemory.cs documents that AC "sometimes doesn't bother setting
# Status to Pause" and derives pause from packetId stagnation instead).
#   int packetId @ 0
PHYSICS_PACKET_ID_OFFSET = 0
PHYSICS_MIN_BYTES = PHYSICS_PACKET_ID_OFFSET + 4  # 4

# Windows named shared-memory objects created by acs.exe. AC creates them in the session
# namespace as ``Local\<name>``; a bare name resolves to ``Local\`` for processes in the
# same logon session, so the opener tries the bare name first then the explicit prefix.
SHM_GRAPHICS = "acpmf_graphics"
SHM_PHYSICS = "acpmf_physics"

# How many bytes of each section to map. The real sections are multiple KB; mapping a small
# safe prefix avoids over-mapping while covering every field we read.
GRAPHICS_MAP_BYTES = 256
PHYSICS_MAP_BYTES = 64


class AcGameStatus(IntEnum):
    """``AC_STATUS`` enum from ``acpmf_graphics`` (AcManager AcGameStatus.cs)."""

    OFF = 0
    REPLAY = 1
    LIVE = 2
    PAUSE = 3

    @classmethod
    def from_int(cls, value: int) -> AcGameStatus | int:
        """Map a raw int to the enum, returning the raw int if it is unknown.

        AC has only ever shipped 0..3, but a future build could add a value; returning the
        raw int keeps the detector from crashing on an unrecognized status (it will simply
        be treated as "not LIVE").
        """
        try:
            return cls(value)
        except ValueError:
            return value


@dataclass(frozen=True)
class GraphicsSnapshot:
    """The fields decoded from ``acpmf_graphics`` that the entry detector consumes."""

    packet_id: int
    status: AcGameStatus | int
    is_in_pit: bool

    @property
    def is_live(self) -> bool:
        return self.status == AcGameStatus.LIVE


@dataclass(frozen=True)
class PhysicsSnapshot:
    """The single ``acpmf_physics`` field used for the stagnation guard."""

    packet_id: int


class SharedMemoryUnavailable(RuntimeError):
    """Raised when AC shared memory cannot be opened (not Windows, or AC not running)."""


def parse_graphics(buf: bytes) -> GraphicsSnapshot:
    """Decode an ``acpmf_graphics`` byte buffer into a :class:`GraphicsSnapshot`.

    Pure and platform-independent. ``buf`` must be at least :data:`GRAPHICS_MIN_BYTES`.
    Integers are little-endian (Windows x86-64); ``isInPit`` is a 4-byte Win32 BOOL read as
    "nonzero == in pit".
    """
    if len(buf) < GRAPHICS_MIN_BYTES:
        raise ValueError(
            f"acpmf_graphics buffer too short: {len(buf)} < {GRAPHICS_MIN_BYTES} bytes"
        )
    packet_id = struct.unpack_from("<i", buf, GRAPHICS_PACKET_ID_OFFSET)[0]
    status_raw = struct.unpack_from("<i", buf, GRAPHICS_STATUS_OFFSET)[0]
    is_in_pit_raw = struct.unpack_from("<i", buf, GRAPHICS_IS_IN_PIT_OFFSET)[0]
    return GraphicsSnapshot(
        packet_id=packet_id,
        status=AcGameStatus.from_int(status_raw),
        is_in_pit=is_in_pit_raw != 0,
    )


def parse_physics(buf: bytes) -> PhysicsSnapshot:
    """Decode an ``acpmf_physics`` byte buffer into a :class:`PhysicsSnapshot` (pure)."""
    if len(buf) < PHYSICS_MIN_BYTES:
        raise ValueError(f"acpmf_physics buffer too short: {len(buf)} < {PHYSICS_MIN_BYTES} bytes")
    packet_id = struct.unpack_from("<i", buf, PHYSICS_PACKET_ID_OFFSET)[0]
    return PhysicsSnapshot(packet_id=packet_id)


class DrivingEntryDetector:
    """State machine that decides "car 0 is on track and driving" from shared-memory polls.

    Mirrors Content Manager's ``ImmediateStart.SetSharedListener`` loop shape: it requires
    ``status == LIVE`` and ``not is_in_pit`` to hold for ``required_live_reads`` consecutive
    polls (CM requires ``IsInPits == false`` on 6 reads before it stops re-issuing Drive)
    before declaring driving entered. It additionally guards against the documented case
    where AC stays flagged LIVE on a frozen frame: if the physics ``packet_id`` has not
    advanced for longer than ``stagnation_seconds``, the frame is treated as stalled (menu /
    pause) regardless of ``status``.

    The detector is pure — feed it snapshots via :meth:`observe` with an explicit ``now``
    (monotonic seconds). It never reads a clock itself, so tests are deterministic.
    """

    def __init__(
        self,
        *,
        required_live_reads: int = 5,
        stagnation_seconds: float = 0.05,
    ) -> None:
        if required_live_reads < 1:
            raise ValueError("required_live_reads must be >= 1")
        if stagnation_seconds <= 0:
            raise ValueError("stagnation_seconds must be > 0")
        self.required_live_reads = required_live_reads
        self.stagnation_seconds = stagnation_seconds
        self._consecutive_clear = 0
        self._last_physics_packet: int | None = None
        # Time of the last *observed* physics packetId change. None until a change has been
        # seen: a single sample is not evidence of advancement (a packet frozen on the
        # pre-drive menu reads as one unchanging value), so physics counts as "confirmed
        # advancing" only once it has actually moved — otherwise a fast poll could accumulate
        # required_live_reads frozen-but-LIVE frames inside the stagnation window and falsely
        # declare driving on a stalled sim.
        self._last_packet_change: float | None = None
        self._last_stuck = False

    @property
    def consecutive_clear_reads(self) -> int:
        """How many consecutive LIVE+not-pit+advancing polls have been seen (debug/probe)."""
        return self._consecutive_clear

    def _physics_advancing(self, now: float, physics_present: bool) -> bool:
        """Whether physics is confirmed advancing *this* frame.

        True when there is no physics page to gate on (``physics_present`` is False) — the
        detector then degrades to status+pit only, so a physics page that disappears
        mid-session cannot wedge the detector via a stale timestamp. When physics IS present
        it must have been observed to change at least once AND that change must be within
        ``stagnation_seconds``: a packet that has never moved, or has frozen past the window,
        is not advancing.
        """
        if not physics_present:
            return True
        if self._last_packet_change is None:
            return False
        return (now - self._last_packet_change) <= self.stagnation_seconds

    def observe(
        self,
        graphics: GraphicsSnapshot,
        physics: PhysicsSnapshot | None = None,
        *,
        now: float,
    ) -> None:
        """Feed one poll. ``physics`` may be ``None`` if only the graphics page mapped."""
        physics_present = physics is not None
        if physics_present:
            if self._last_physics_packet is None:
                # First physics sample: record the baseline but do NOT mark a change — one
                # sample cannot tell "advancing" from "frozen".
                self._last_physics_packet = physics.packet_id
            elif physics.packet_id != self._last_physics_packet:
                self._last_physics_packet = physics.packet_id
                self._last_packet_change = now
            # else: unchanged packet -> leave _last_packet_change so it can go stale.

        advancing = self._physics_advancing(now, physics_present)
        clear = graphics.is_live and not graphics.is_in_pit and advancing
        self._consecutive_clear = self._consecutive_clear + 1 if clear else 0
        # "Stuck" reflects THIS frame (for a future actuator's "re-issue Drive while stuck"):
        # not LIVE, or LIVE-but-physics-present-and-not-advancing (the frozen-menu case).
        self._last_stuck = (not graphics.is_live) or (physics_present and not advancing)

    @property
    def driving(self) -> bool:
        """True once LIVE+not-pit+advancing has held for ``required_live_reads`` polls."""
        return self._consecutive_clear >= self.required_live_reads

    @property
    def stuck_in_menu(self) -> bool:
        """True when the last observed frame looks like menu/pause/stall and we're not driving.

        Reflects the most recent :meth:`observe` (not a separately-passed frame) so it cannot
        disagree with the accumulator or use stale physics state. For a future detect-and-retry
        actuator ("re-issue Drive while stuck").
        """
        return not self.driving and self._last_stuck


# ---------------------------------------------------------------------------
# Windows-only shared-memory plumbing (not exercised by CI; validated on the rig).
#
# IMPORTANT: this uses ``OpenFileMappingW`` (open-EXISTING-only), NOT
# ``mmap.mmap(-1, …, tagname=…)``. The latter is page-file-backed and *creates* the named
# section if it does not exist — which would (a) silently read all-zeros when AC is down,
# defeating the "is acs.exe running?" check, and (b) risk pre-creating ``acpmf_graphics``
# before acs.exe and interfering with AC's own telemetry. Open-existing-only fails cleanly
# when AC is not running and never touches AC's section other than to read it.
# ---------------------------------------------------------------------------
def _kernel32():  # pragma: no cover - rig-only
    """A kernel32 handle with ALL used functions' argtypes/restype declared.

    Declaring argtypes is mandatory on 64-bit: without them ctypes defaults each argument to
    C ``int``, and passing a 64-bit pointer (HANDLE / mapped address) overflows it
    (``OverflowError: int too long to convert``) — which previously crashed ``close()`` and
    the error-path ``CloseHandle``. restype=HANDLE/LPVOID (both ``c_void_p``) also makes ctypes
    return a Python ``int`` for a valid pointer and ``None`` for NULL, so ``if handle`` /
    ``if not address`` is the correct, portable NULL check.
    """
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenFileMappingW.restype = wintypes.HANDLE
    k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.MapViewOfFile.restype = wintypes.LPVOID
    k.MapViewOfFile.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    k.UnmapViewOfFile.restype = wintypes.BOOL
    k.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


class _MappedSection:  # pragma: no cover - Windows ctypes view; validated on the rig
    """A read-only view of an existing Windows named section (held until :meth:`close`)."""

    def __init__(self, handle: object, address: object, length: int) -> None:
        self._handle = handle
        self._address = address
        self._length = length

    def read(self, n: int) -> bytes:
        import ctypes

        if n > self._length:
            raise ValueError(f"read {n} > mapped {self._length} bytes")
        return ctypes.string_at(self._address, n)

    def close(self) -> None:
        if self._address is None and self._handle is None:
            return
        kernel32 = _kernel32()
        if self._address is not None:
            kernel32.UnmapViewOfFile(self._address)
            self._address = None
        if self._handle is not None:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def open_shared_memory(name: str, length: int) -> _MappedSection:
    """Open an EXISTING AC named shared-memory section read-only (Windows only).

    Tries the bare ``name`` first (resolves to ``Local\\<name>`` in the same logon session)
    then the explicit ``Local\\<name>``. Raises :class:`SharedMemoryUnavailable` off-Windows
    or when the section does not exist (AC not running / not far enough into launch).
    """
    if sys.platform != "win32":
        raise SharedMemoryUnavailable(
            f"AC shared memory ({name!r}) is Windows-only; this is {sys.platform!r}"
        )
    return _win_open_existing(name, length)


def _win_open_existing(name: str, length: int) -> _MappedSection:  # pragma: no cover - rig-only
    """Windows ctypes ``OpenFileMappingW`` + ``MapViewOfFile`` (open-existing-only)."""
    import ctypes

    file_map_read = 0x0004
    kernel32 = _kernel32()

    handle = None
    for tag in (name, f"Local\\{name}"):
        handle = kernel32.OpenFileMappingW(file_map_read, False, tag)
        if handle:
            break
    if not handle:
        raise SharedMemoryUnavailable(
            f"AC shared memory {name!r} not found (is acs.exe running?); "
            f"WinError {ctypes.get_last_error()}"
        )
    address = kernel32.MapViewOfFile(handle, file_map_read, 0, 0, length)
    if not address:
        err = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise SharedMemoryUnavailable(f"MapViewOfFile failed for {name!r}: WinError {err}")
    return _MappedSection(handle, address, length)


class SharedMemoryReader:  # pragma: no cover - Windows/rig-only; validated via the live-probe
    """Holds the open graphics (+ optional physics) sections and reads fresh snapshots.

    Context manager; releases the sections on exit. Windows-only — constructing it
    off-Windows raises :class:`SharedMemoryUnavailable`.
    """

    def __init__(self, *, with_physics: bool = True) -> None:
        self._graphics = open_shared_memory(SHM_GRAPHICS, GRAPHICS_MAP_BYTES)
        self._physics: _MappedSection | None = None
        if with_physics:
            try:
                self._physics = open_shared_memory(SHM_PHYSICS, PHYSICS_MAP_BYTES)
            except SharedMemoryUnavailable:
                self._physics = None  # degrade gracefully; detector tolerates physics=None
            except BaseException:
                # Any unexpected failure opening physics must not leak the graphics handle.
                self._graphics.close()
                raise

    def read_graphics(self) -> GraphicsSnapshot:
        return parse_graphics(self._graphics.read(GRAPHICS_MIN_BYTES))

    def read_physics(self) -> PhysicsSnapshot | None:
        if self._physics is None:
            return None
        return parse_physics(self._physics.read(PHYSICS_MIN_BYTES))

    def close(self) -> None:
        for section in (self._graphics, self._physics):
            if section is not None:
                section.close()

    def __enter__(self) -> SharedMemoryReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _open_reader_with_retry(  # pragma: no cover - rig-only live-probe helper
    *, attempts: int, interval: float, clock: Callable[[], float], sleep: Callable[[float], None]
) -> SharedMemoryReader:
    """Retry-open the reader until acs.exe has created the sections (live-probe helper)."""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            return SharedMemoryReader()
        except SharedMemoryUnavailable as err:
            last_err = err
            sleep(interval)
    raise SharedMemoryUnavailable(
        f"AC shared memory not available after {attempts} attempts: {last_err}"
    )


def _live_probe(args: argparse.Namespace) -> int:  # pragma: no cover - rig-only entrypoint
    """Poll shared memory and print each frame until driving is detected (rig confirmation).

    This is the operator-grade verification surface: with AC on the pre-drive menu then
    driving, confirm ``status`` flips PAUSE(3)→LIVE(2) and ``is_in_pit`` flips True→False at
    offset :data:`GRAPHICS_IS_IN_PIT_OFFSET`.
    """
    clock = time.monotonic
    try:
        reader = _open_reader_with_retry(
            attempts=args.open_attempts, interval=args.interval, clock=clock, sleep=time.sleep
        )
    except SharedMemoryUnavailable as err:
        print(f"[probe] {err}", file=sys.stderr)
        return 2

    detector = DrivingEntryDetector(required_live_reads=args.required_reads)
    print(
        f"[probe] polling every {args.interval * 1000:.0f}ms; "
        f"need {args.required_reads} consecutive LIVE+not-pit reads; "
        f"IsInPit offset={GRAPHICS_IS_IN_PIT_OFFSET}",
        file=sys.stderr,
    )
    with reader:
        for i in range(args.max_polls):
            now = clock()
            g = reader.read_graphics()
            p = reader.read_physics()
            detector.observe(g, p, now=now)
            status_name = g.status.name if isinstance(g.status, AcGameStatus) else f"?{g.status}"
            print(
                f"[{i:4d}] status={status_name:<6} in_pit={g.is_in_pit!s:<5} "
                f"gfx_pkt={g.packet_id:<8} phys_pkt={(p.packet_id if p else '—'):<8} "
                f"clear={detector.consecutive_clear_reads}/{args.required_reads} "
                f"driving={detector.driving} stuck={detector.stuck_in_menu}"
            )
            if detector.driving:
                print("[probe] DRIVING DETECTED — on track, out of pits.", file=sys.stderr)
                return 0
            time.sleep(args.interval)
    print("[probe] max polls reached without detecting driving.", file=sys.stderr)
    return 1


def _build_arg_parser() -> argparse.ArgumentParser:  # pragma: no cover - rig-only CLI wiring
    p = argparse.ArgumentParser(description="AC shared-memory on-track-entry live-probe")
    p.add_argument("--interval", type=float, default=0.03, help="poll interval seconds")
    p.add_argument("--required-reads", type=int, default=5, help="consecutive LIVE+not-pit reads")
    p.add_argument("--max-polls", type=int, default=2000, help="max polls before giving up")
    p.add_argument("--open-attempts", type=int, default=200, help="retry-opens before giving up")
    return p


if __name__ == "__main__":  # pragma: no cover - rig-only live-probe entrypoint
    raise SystemExit(_live_probe(_build_arg_parser().parse_args()))
