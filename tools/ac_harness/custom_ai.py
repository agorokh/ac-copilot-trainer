"""CSP Custom-AI external-control mmap writer + reader (EPIC #154 — autonomous drive).

This is the **actuator** half of the autonomous self-test: it drives car 0 in Assetto
Corsa with no human at the wheel by writing to CSP's *Custom AI* external-control shared
memory at ~333 Hz, and reads back the car's state so the L1.5 probe + shared-memory oracle
can verify the drive. Source: ``cup.acstuff.club/docs/csp/other-things/custom-ai``; full
notes in the vault under
``docs/01_Vault/AcCopilotTrainer/03_Investigations/csp-custom-ai-mmap-interface-2026-06-16.md``.

The interface is three Windows named shared-memory sections, parametrised by car index
``<N>`` (``0`` == the player car):

* ``AcTools.CSP.NewBehaviour.CustomAI.CarControls<N>.v0`` — WRITE. The external app
  **creates** this section; that creation is the signal that hijacks the car. CSP responds
  by creating the matching ``Car<N>.v0`` read section (so a non-``None`` :meth:`read_car_data`
  is the confirmation that CSP accepted the hijack).
* ``AcTools.CSP.NewBehaviour.CustomAI.Car<N>.v0`` — READ. Car telemetry, created by CSP.
* ``AcTools.CSP.NewBehaviour.CustomAI.SimState.v0`` — pause / restart / collision control.

The CRITICAL design split (so CI on any OS can verify the byte layout with zero AC / zero
Windows): the dataclasses and ``pack`` / ``parse`` helpers are **pure** ``struct`` code,
importable and testable everywhere. The Windows-only ctypes mmap plumbing
(:class:`CustomAIController`, :class:`SimStateController`) is pragma-guarded.

OFFSETS — LIVE-VERIFIED 2026-06-16 (Magione, Porsche 911 GT3 R, CSP Custom AI hijack of car 0).
The control offsets we actually drive with (gas@0, brake@4, clutch@8, steer@12, gear_up@20,
gear_dn@21, autoclutch_on_start@41, autoclutch_on_change@42, teleport_to@40) and the Car<N>
read offsets (gear@28, rpm@32, speed_kmh@36, look@64, position@88) were confirmed against
``acpmf_physics`` ground truth and by observing the car drive a full clean lap. Two caveats from
that verification: (1) **``spline_position``** is now read at the LIVE-PROBED offset 240 (the old
doc-extracted 448 read garbage); it tracks lap progress 0..1 but stays OFF the drive path — lap
progress uses ``acpmf_graphics`` ``normalizedCarPosition`` / position-return — so a residual error
here cannot affect driving. (2) The engine only drives the wheels when the car is
in a real gear (AC ``gear`` encoding: **0=Reverse, 1=NEUTRAL, 2=1st**) AND ``autoclutch_on_start``
+ ``autoclutch_on_change`` are set; a manually-written clutch value FIGHTS the autoclutch and kills
drive, so leave ``clutch`` at 0. See the vault investigation
``03_Investigations/autonomous-drive-live-verified-2026-06-16.md``. Offsets not on the drive path
(DRS/KERS/teleport_pos/teleport_dir/autoshift, and the full Car<N> wheel/damage block) remain
doc-extracted (``VERIFY LIVE``) until exercised.

ctypes discipline (the #175 oracle's hard-won lesson): every kernel32 call has
``restype`` and ``argtypes`` declared, or a 64-bit handle / pointer silently overflows the
default C ``int`` and raises ``OverflowError``. Section names are wide strings
(``c_wchar_p``). For WRITING a *new* section we use ``CreateFileMappingW`` (the controls
section must exist for CSP to notice it) rather than ``OpenFileMappingW``; the read side
opens-existing-only so it returns ``None`` until CSP has created ``Car<N>.v0``.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

# Reuse the canonical exception from the read-side oracle rather than defining a second,
# distinct class: a caller catching ``SharedMemoryUnavailable`` around either the reader or
# this writer then catches both. (Two same-named classes from two modules silently fail to
# match across an ``except`` boundary — the #175 footgun in a different guise.)
from tools.ac_harness.shared_memory import SharedMemoryUnavailable

# ---------------------------------------------------------------------------
# Section-name templates. ``<N>`` is the car index; 0 == the player car. The external app
# CREATES CarControls<N>; CSP creates Car<N> in response. SimState is a single global.
# ---------------------------------------------------------------------------
CAR_CONTROLS_NAME_TEMPLATE = "AcTools.CSP.NewBehaviour.CustomAI.CarControls{index}.v0"
CAR_DATA_NAME_TEMPLATE = "AcTools.CSP.NewBehaviour.CustomAI.Car{index}.v0"
SIM_STATE_NAME = "AcTools.CSP.NewBehaviour.CustomAI.SimState.v0"

# ---------------------------------------------------------------------------
# cai_car_controls layout (WRITE — what we feed CSP to drive the car).  VERIFY LIVE: every
# offset below is doc-extracted from the Custom AI page and UNCONFIRMED against a live CSP
# build. We allocate a generous, zero-filled buffer (CONTROLS_BUFFER_BYTES) so that fields
# we do not set read as 0/false and an offset that is slightly off cannot run past the map.
# ---------------------------------------------------------------------------
CTRL_GAS_OFFSET = 0  # f32, 0..1            VERIFY LIVE
CTRL_BRAKE_OFFSET = 4  # f32, 0..1          VERIFY LIVE
CTRL_CLUTCH_OFFSET = 8  # f32, 0..1         VERIFY LIVE
CTRL_STEER_OFFSET = 12  # f32, -1..1        VERIFY LIVE
# handbrake: UNVERIFIED — the doc lists it as a BOOL in the bool group (after kers), not an f32 at
# 16, so bytes 16..19 are doc-unconfirmed. We always write 0.0 (handbrake unused), which drove for
# hours with no ill effect, so the current pack is empirically harmless; but VERIFY this offset (or
# rewire to the bool field) before ever commanding a non-zero handbrake.  VERIFY LIVE
CTRL_HANDBRAKE_OFFSET = 16  # f32, 0..1     VERIFY LIVE (write 0.0 only; see note)
CTRL_GEAR_UP_OFFSET = 20  # bool (1 byte)   VERIFY LIVE
CTRL_GEAR_DN_OFFSET = 21  # bool (1 byte)   VERIFY LIVE
CTRL_DRS_OFFSET = 22  # bool (1 byte)       VERIFY LIVE
CTRL_KERS_OFFSET = 23  # bool (1 byte)      VERIFY LIVE
CTRL_TELEPORT_TO_OFFSET = 40  # byte: 0=none, 1=pits, 2=custom (teleport_pos/dir)  VERIFY LIVE
CTRL_AUTOCLUTCH_ON_START_OFFSET = 41  # bool (1 byte)   VERIFY LIVE
CTRL_AUTOCLUTCH_ON_CHANGE_OFFSET = 42  # bool (1 byte)  VERIFY LIVE
CTRL_AUTOBLIP_OFFSET = 43  # bool (1 byte)              VERIFY LIVE
CTRL_TELEPORT_POS_OFFSET = 44  # float3 (x, y, z)       VERIFY LIVE
CTRL_TELEPORT_DIR_OFFSET = 56  # float3 (x, y, z)       VERIFY LIVE
CTRL_AUTOSHIFT_ACTIVE_OFFSET = 68  # bool (1 byte)      VERIFY LIVE

# teleport_to byte values.
TELEPORT_NONE = 0
TELEPORT_TO_PITS = 1
TELEPORT_TO_CUSTOM = 2

# Generous zero-filled buffer for the controls section (doc recommends >= the struct size;
# 256 bytes leaves headroom past autoshift_active@68 for any field we have not modelled).
CONTROLS_BUFFER_BYTES = 256

# ---------------------------------------------------------------------------
# cai_car_data layout (READ — car state CSP publishes for the hijacked car).  VERIFY LIVE:
# doc-extracted, UNCONFIRMED. We map CAR_DATA_BUFFER_BYTES and parse only the fields the
# harness needs; the rest of the documented struct (wheels[4], damage, lap times, …) is left
# unparsed until a live build confirms the layout.
# ---------------------------------------------------------------------------
DATA_PACKET_ID_OFFSET = 0  # i32                         VERIFY LIVE
DATA_GAS_OFFSET = 4  # f32                               VERIFY LIVE
DATA_BRAKE_OFFSET = 8  # f32                             VERIFY LIVE
DATA_CLUTCH_OFFSET = 12  # f32                           VERIFY LIVE
DATA_STEER_OFFSET = 16  # f32 (degrees)                  VERIFY LIVE
DATA_HANDBRAKE_OFFSET = 20  # f32                        VERIFY LIVE
DATA_FUEL_OFFSET = 24  # f32                             VERIFY LIVE
DATA_GEAR_OFFSET = 28  # i32                             VERIFY LIVE
DATA_RPM_OFFSET = 32  # f32                              VERIFY LIVE
DATA_SPEED_KMH_OFFSET = 36  # f32                        VERIFY LIVE
DATA_VELOCITY_OFFSET = 40  # float3                      VERIFY LIVE
DATA_LOOK_OFFSET = 64  # float3 (forward unit vector)    VERIFY LIVE
DATA_POSITION_OFFSET = 88  # float3 (world x, y, z)      VERIFY LIVE
DATA_SPLINE_POSITION_OFFSET = 240  # f32, 0..1 around the lap. LIVE-PROBED 2026-06-16: 448 (the
# old doc-extracted guess) read garbage (-5..+10); offset 240 tracks lap progress monotonically
# (0.00 -> 0.24 over a quarter-lap drive). Offsets 360/480 alias the same value. Full 0->1->wrap
# range not yet exercised, and it stays OFF the drive path (lap progress uses position-return), so
# a residual error here cannot affect driving.

# Bytes that must be readable to decode every field we parse. position@88 (+12) is the furthest
# *control* field; spline_position@240 (+4) sets the floor. Keep a generous margin.
CAR_DATA_MIN_BYTES = DATA_SPLINE_POSITION_OFFSET + 4  # 244
# Doc says allocate 512 to read the full struct; we map that so an offset that is slightly
# off (pre-verification) still lands inside the mapped view rather than over-reading.
CAR_DATA_BUFFER_BYTES = 512

# ---------------------------------------------------------------------------
# SimState layout (sim control).  VERIFY LIVE.
#   bool pause@0, bool restart_session@1, bool disable_collisions@2, byte extra_sleep_ms@3
# ---------------------------------------------------------------------------
SIM_PAUSE_OFFSET = 0  # bool (1 byte)               VERIFY LIVE
SIM_RESTART_SESSION_OFFSET = 1  # bool (1 byte)      VERIFY LIVE
SIM_DISABLE_COLLISIONS_OFFSET = 2  # bool (1 byte)   VERIFY LIVE
SIM_EXTRA_SLEEP_MS_OFFSET = 3  # byte                VERIFY LIVE
SIM_STATE_BUFFER_BYTES = 16  # tiny struct; map a small zero-filled buffer


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to ``[low, high]``.

    CSP applies controls verbatim; an out-of-range gas/steer would be undefined behaviour
    for the physics, so we clamp at the boundary the same way an in-game axis would saturate.
    """
    return low if value < low else high if value > high else value


@dataclass(frozen=True)
class CarControls:
    """The control inputs we write to ``CarControls<N>`` to drive the car.

    Floats are saturating (gas/brake/clutch/handbrake to ``0..1``, steer to ``-1..1``) so a
    caller passing a slightly out-of-range value gets the same clamped behaviour a physical
    axis would. ``teleport_to`` selects pits (:data:`TELEPORT_TO_PITS`) or a custom position
    (:data:`TELEPORT_TO_CUSTOM`, using ``teleport_pos``); ``teleport_pos`` is ignored unless
    ``teleport_to == TELEPORT_TO_CUSTOM``.
    """

    gas: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    steer: float = 0.0
    handbrake: float = 0.0
    gear_up: bool = False
    gear_dn: bool = False
    autoclutch_on_start: bool = False
    autoclutch_on_change: bool = False
    teleport_to: int = TELEPORT_NONE
    teleport_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    teleport_dir: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def pack(self) -> bytes:
        """Serialise into a zero-filled :data:`CONTROLS_BUFFER_BYTES` buffer at the offsets.

        Every byte not written by a field stays 0 (the buffer is zero-filled), so unset
        controls — clutch, the autoclutch/autoblip flags, teleport_dir — read as 0/false on
        the CSP side. Floats are little-endian (Windows x86-64); bools are a single ``0x01`` /
        ``0x00`` byte.
        """
        buf = bytearray(CONTROLS_BUFFER_BYTES)
        struct.pack_into("<f", buf, CTRL_GAS_OFFSET, _clamp(self.gas, 0.0, 1.0))
        struct.pack_into("<f", buf, CTRL_BRAKE_OFFSET, _clamp(self.brake, 0.0, 1.0))
        struct.pack_into("<f", buf, CTRL_CLUTCH_OFFSET, _clamp(self.clutch, 0.0, 1.0))
        struct.pack_into("<f", buf, CTRL_STEER_OFFSET, _clamp(self.steer, -1.0, 1.0))
        struct.pack_into("<f", buf, CTRL_HANDBRAKE_OFFSET, _clamp(self.handbrake, 0.0, 1.0))
        struct.pack_into("<?", buf, CTRL_GEAR_UP_OFFSET, self.gear_up)
        struct.pack_into("<?", buf, CTRL_GEAR_DN_OFFSET, self.gear_dn)
        struct.pack_into("<?", buf, CTRL_AUTOCLUTCH_ON_START_OFFSET, self.autoclutch_on_start)
        struct.pack_into("<?", buf, CTRL_AUTOCLUTCH_ON_CHANGE_OFFSET, self.autoclutch_on_change)
        struct.pack_into("<B", buf, CTRL_TELEPORT_TO_OFFSET, self.teleport_to & 0xFF)
        px, py, pz = self.teleport_pos
        struct.pack_into("<3f", buf, CTRL_TELEPORT_POS_OFFSET, px, py, pz)
        dx, dy, dz = self.teleport_dir
        struct.pack_into("<3f", buf, CTRL_TELEPORT_DIR_OFFSET, dx, dy, dz)
        return bytes(buf)


@dataclass(frozen=True)
class CarData:
    """The subset of ``Car<N>`` car-state fields the harness decodes (UNVERIFIED offsets)."""

    packet_id: int
    gear: int
    rpm: float
    speed_kmh: float
    position: tuple[float, float, float]
    look: tuple[float, float, float]
    spline_position: float

    def as_dict(self) -> dict[str, object]:
        """Flat dict for the L1.5 probe / diag (mirrors the WS-tap frame shape)."""
        return {
            "packet_id": self.packet_id,
            "gear": self.gear,
            "rpm": self.rpm,
            "speed_kmh": self.speed_kmh,
            "position": self.position,
            "look": self.look,
            "spline_position": self.spline_position,
        }


def parse_car_data(buf: bytes) -> CarData:
    """Decode a ``Car<N>`` byte buffer into a :class:`CarData` (pure, platform-independent).

    ``buf`` must be at least :data:`CAR_DATA_MIN_BYTES`. Integers/floats are little-endian
    (Windows x86-64). Offsets are UNVERIFIED — see the module docstring.
    """
    if len(buf) < CAR_DATA_MIN_BYTES:
        raise ValueError(f"cai_car_data buffer too short: {len(buf)} < {CAR_DATA_MIN_BYTES} bytes")
    packet_id = struct.unpack_from("<i", buf, DATA_PACKET_ID_OFFSET)[0]
    gear = struct.unpack_from("<i", buf, DATA_GEAR_OFFSET)[0]
    rpm = struct.unpack_from("<f", buf, DATA_RPM_OFFSET)[0]
    speed_kmh = struct.unpack_from("<f", buf, DATA_SPEED_KMH_OFFSET)[0]
    position = struct.unpack_from("<3f", buf, DATA_POSITION_OFFSET)
    look = struct.unpack_from("<3f", buf, DATA_LOOK_OFFSET)
    spline_position = struct.unpack_from("<f", buf, DATA_SPLINE_POSITION_OFFSET)[0]
    return CarData(
        packet_id=packet_id,
        gear=gear,
        rpm=rpm,
        speed_kmh=speed_kmh,
        position=position,
        look=look,
        spline_position=spline_position,
    )


@dataclass(frozen=True)
class SimState:
    """Sim-control flags written to the global ``SimState`` section."""

    pause: bool = False
    restart_session: bool = False
    disable_collisions: bool = False
    extra_sleep_ms: int = 0

    def pack(self) -> bytes:
        """Serialise into a zero-filled :data:`SIM_STATE_BUFFER_BYTES` buffer."""
        buf = bytearray(SIM_STATE_BUFFER_BYTES)
        struct.pack_into("<?", buf, SIM_PAUSE_OFFSET, self.pause)
        struct.pack_into("<?", buf, SIM_RESTART_SESSION_OFFSET, self.restart_session)
        struct.pack_into("<?", buf, SIM_DISABLE_COLLISIONS_OFFSET, self.disable_collisions)
        struct.pack_into("<B", buf, SIM_EXTRA_SLEEP_MS_OFFSET, self.extra_sleep_ms & 0xFF)
        return bytes(buf)


def _validate_car_index(car_index: int) -> int:
    """Reject a negative ``car_index`` early. Otherwise it silently produces an invalid section
    name (e.g. ``CarControls-1.v0``) that fails later in a non-obvious way (CodeRabbit)."""
    if car_index < 0:
        raise ValueError(f"car_index must be >= 0 (0 == player car), got {car_index}")
    return car_index


def car_controls_name(car_index: int) -> str:
    """Name of the WRITE (controls) section for ``car_index`` (0 == player)."""
    return CAR_CONTROLS_NAME_TEMPLATE.format(index=_validate_car_index(car_index))


def car_data_name(car_index: int) -> str:
    """Name of the READ (car-state) section CSP creates for ``car_index`` (0 == player)."""
    return CAR_DATA_NAME_TEMPLATE.format(index=_validate_car_index(car_index))


# ---------------------------------------------------------------------------
# Windows-only ctypes mmap plumbing (not exercised by CI; validated on the rig).
#
# WRITE side uses CreateFileMappingW(INVALID_HANDLE_VALUE, …) to CREATE a page-file-backed
# named section: CSP only hijacks the car once the CarControls<N> section EXISTS, so we must
# create it, not open it. READ side uses OpenFileMappingW (open-existing-only) so it returns
# None until CSP has created Car<N> in response — mirroring shared_memory.py's opener.
# ---------------------------------------------------------------------------
def _kernel32():  # pragma: no cover - rig-only
    """A kernel32 handle with ALL used functions' argtypes/restype declared.

    Mandatory on 64-bit: without argtypes ctypes defaults each argument to C ``int`` and a
    64-bit handle / mapped address overflows it (``OverflowError: int too long to convert``).
    ``restype = HANDLE / LPVOID`` (both ``c_void_p``) makes ctypes hand back a Python ``int``
    for a valid pointer and ``None`` for NULL, so ``if handle`` / ``if not address`` is the
    correct portable NULL check. Mirrors ``shared_memory._kernel32`` exactly, plus the
    create/write functions this module additionally needs.
    """
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    # CreateFileMappingW(hFile, lpAttributes, flProtect, dwMaxHi, dwMaxLo, lpName) -> HANDLE.
    k.CreateFileMappingW.restype = wintypes.HANDLE
    k.CreateFileMappingW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPCWSTR,
    ]
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


class _WritableSection:  # pragma: no cover - Windows ctypes view; validated on the rig
    """A read/write view of a Windows named section we CREATED (held until :meth:`close`)."""

    def __init__(self, handle: object, address: object, length: int) -> None:
        self._handle = handle
        self._address = address
        self._length = length

    def write(self, data: bytes) -> None:
        import ctypes

        if len(data) > self._length:
            raise ValueError(f"write {len(data)} > mapped {self._length} bytes")
        ctypes.memmove(self._address, data, len(data))

    def close(self) -> None:
        import ctypes

        if self._address is None and self._handle is None:
            return
        kernel32 = _kernel32()
        errors: list[str] = []
        if self._address is not None:
            if kernel32.UnmapViewOfFile(self._address):
                self._address = None
            else:
                errors.append(
                    "UnmapViewOfFile failed: "
                    f"WinError {getattr(ctypes, 'get_last_error', lambda: 0)()}"
                )
        if self._handle is not None:
            if kernel32.CloseHandle(self._handle):
                self._handle = None
            else:
                errors.append(
                    f"CloseHandle failed: WinError {getattr(ctypes, 'get_last_error', lambda: 0)()}"
                )
        if errors:
            raise OSError("; ".join(errors))


class _ReadableSection:  # pragma: no cover - Windows ctypes view; validated on the rig
    """A read view of an EXISTING Windows named section (held until :meth:`close`)."""

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
        import ctypes

        if self._address is None and self._handle is None:
            return
        kernel32 = _kernel32()
        errors: list[str] = []
        if self._address is not None:
            if kernel32.UnmapViewOfFile(self._address):
                self._address = None
            else:
                errors.append(
                    "UnmapViewOfFile failed: "
                    f"WinError {getattr(ctypes, 'get_last_error', lambda: 0)()}"
                )
        if self._handle is not None:
            if kernel32.CloseHandle(self._handle):
                self._handle = None
            else:
                errors.append(
                    f"CloseHandle failed: WinError {getattr(ctypes, 'get_last_error', lambda: 0)()}"
                )
        if errors:
            raise OSError("; ".join(errors))


def _create_writable_section(name: str, length: int) -> _WritableSection:  # pragma: no cover - rig
    """Create a new page-file-backed named section, mapped read/write (Windows only).

    ``INVALID_HANDLE_VALUE`` (-1) backs the section by the page file rather than a real file;
    ``PAGE_READWRITE`` (0x04) + ``FILE_MAP_WRITE`` (0x02) gives us a writable view. If the
    section already exists (e.g. a prior crashed run), ``CreateFileMappingW`` returns a handle
    to it — which is fine; we just remap and overwrite.
    """
    import ctypes

    if sys.platform != "win32":
        raise SharedMemoryUnavailable(
            f"Custom-AI section ({name!r}) is Windows-only; this is {sys.platform!r}"
        )
    invalid_handle_value = ctypes.c_void_p(-1)
    page_readwrite = 0x04
    file_map_write = 0x02
    kernel32 = _kernel32()

    handle = kernel32.CreateFileMappingW(
        invalid_handle_value, None, page_readwrite, 0, length, name
    )
    if not handle:
        raise SharedMemoryUnavailable(
            f"CreateFileMappingW failed for {name!r}: WinError {ctypes.get_last_error()}"
        )
    address = kernel32.MapViewOfFile(handle, file_map_write, 0, 0, length)
    if not address:
        err = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise SharedMemoryUnavailable(f"MapViewOfFile (write) failed for {name!r}: WinError {err}")
    return _WritableSection(handle, address, length)


def _open_readable_section(name: str, length: int) -> _ReadableSection | None:  # pragma: no cover
    """Open an EXISTING named section read-only, or return ``None`` if it does not exist.

    Tries the bare ``name`` then ``Local\\<name>`` (same logon-session namespace), mirroring
    ``shared_memory._win_open_existing``. Returns ``None`` (not raising) when the section is
    absent, because the Car<N> section legitimately does not exist until CSP has created it in
    response to our CarControls<N> — its absence is the "not hijacked yet" signal, not an
    error.
    """
    import ctypes

    if sys.platform != "win32":
        raise SharedMemoryUnavailable(
            f"Custom-AI section ({name!r}) is Windows-only; this is {sys.platform!r}"
        )
    file_map_read = 0x0004
    kernel32 = _kernel32()

    handle = None
    for tag in (name, f"Local\\{name}"):
        handle = kernel32.OpenFileMappingW(file_map_read, False, tag)
        if handle:
            break
    if not handle:
        return None  # CSP has not created Car<N> yet — not hijacked.
    address = kernel32.MapViewOfFile(handle, file_map_read, 0, 0, length)
    if not address:
        err = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise SharedMemoryUnavailable(f"MapViewOfFile (read) failed for {name!r}: WinError {err}")
    return _ReadableSection(handle, address, length)


class CustomAIController:  # pragma: no cover - Windows/rig-only; validated against live AC
    """Drives one car via the CSP Custom-AI mmap interface (Windows only).

    Constructing this CREATES the ``CarControls<N>`` section — the act that hijacks the car;
    keep the instance alive for the whole drive (closing it releases the section and hands the
    car back). :meth:`read_car_data` opens ``Car<N>`` lazily and returns ``None`` until CSP has
    created it (confirming the hijack landed). Context manager; releases both sections on exit.
    """

    def __init__(self, car_index: int = 0) -> None:
        self.car_index = car_index
        self._controls = _create_writable_section(
            car_controls_name(car_index), CONTROLS_BUFFER_BYTES
        )
        self._car_data: _ReadableSection | None = None

    def write_controls(
        self,
        gas: float,
        brake: float,
        steer: float,
        *,
        handbrake: float = 0.0,
        clutch: float = 0.0,
        gear_up: bool = False,
        gear_dn: bool = False,
        autoclutch_on_start: bool = False,
        autoclutch_on_change: bool = False,
    ) -> None:
        """Write one frame of controls. Call at ~333 Hz (≈3 ms) for smooth driving.

        ``autoclutch_on_start`` lets CSP manage the launch clutch from a standstill (without it the
        car-setup autoclutch holds the clutch disengaged and the engine free-revs with no drive);
        ``autoclutch_on_change`` does the same across gear changes.
        """
        controls = CarControls(
            gas=gas,
            brake=brake,
            steer=steer,
            handbrake=handbrake,
            clutch=clutch,
            gear_up=gear_up,
            gear_dn=gear_dn,
            autoclutch_on_start=autoclutch_on_start,
            autoclutch_on_change=autoclutch_on_change,
        )
        self._controls.write(controls.pack())

    def teleport_to_pits(self) -> None:
        """Write a one-frame teleport-to-pits command (``teleport_to == TELEPORT_TO_PITS``)."""
        self._controls.write(CarControls(teleport_to=TELEPORT_TO_PITS).pack())

    def teleport_to_custom(
        self,
        position: tuple[float, float, float],
        direction: tuple[float, float, float],
    ) -> None:
        """Write a one-frame custom teleport (``teleport_to == TELEPORT_TO_CUSTOM``).

        ``position`` is the world-space target (AC x, y-up, z); ``direction`` the facing unit
        vector. Offsets are doc-extracted (``teleport_pos@44``, ``teleport_dir@56`` — VERIFY LIVE);
        callers must verify the car actually moved (read back the position) rather than assume the
        command landed, and fall back to :meth:`teleport_to_pits` when it did not.
        """
        self._controls.write(
            CarControls(
                teleport_to=TELEPORT_TO_CUSTOM,
                teleport_pos=position,
                teleport_dir=direction,
            ).pack()
        )

    def read_car_data(self) -> dict[str, object] | None:
        """Read CSP's car-state for this car, or ``None`` until ``Car<N>`` exists (not hijacked).

        Opens the read section lazily on first success and caches it; while the section is
        absent it keeps returning ``None`` so a caller can poll for the hijack to land.
        """
        if self._car_data is None:
            self._car_data = _open_readable_section(
                car_data_name(self.car_index), CAR_DATA_BUFFER_BYTES
            )
            if self._car_data is None:
                return None
        return parse_car_data(self._car_data.read(CAR_DATA_MIN_BYTES)).as_dict()

    def close(self) -> None:
        """Release both sections — releasing ``CarControls<N>`` hands the car back to AC."""
        errors: list[BaseException] = []
        if self._car_data is not None:
            try:
                self._car_data.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._car_data = None
        try:
            self._controls.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            primary = errors[0]
            for secondary in errors[1:]:
                primary.add_note(f"additional close failure: {secondary}")
            raise primary

    def __enter__(self) -> CustomAIController:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class SimStateController:  # pragma: no cover - Windows/rig-only; validated against live AC
    """Pause / restart-session / disable-collisions via the global ``SimState`` section.

    Like :class:`CustomAIController`, constructing it CREATES the section; keep it alive while
    you need sim control. Context manager; releases the section on exit.
    """

    def __init__(self) -> None:
        self._section = _create_writable_section(SIM_STATE_NAME, SIM_STATE_BUFFER_BYTES)

    def write_state(
        self,
        *,
        pause: bool = False,
        restart_session: bool = False,
        disable_collisions: bool = False,
        extra_sleep_ms: int = 0,
    ) -> None:
        """Write the full SimState flag set in one frame."""
        self._section.write(
            SimState(
                pause=pause,
                restart_session=restart_session,
                disable_collisions=disable_collisions,
                extra_sleep_ms=extra_sleep_ms,
            ).pack()
        )

    def pause(self, paused: bool = True) -> None:
        """Pause (or unpause) the sim."""
        self.write_state(pause=paused)

    def restart_session(self) -> None:
        """Request a session restart (one-frame pulse)."""
        self.write_state(restart_session=True)

    def disable_collisions(self, disabled: bool = True) -> None:
        """Disable (or re-enable) collisions for the hijacked car."""
        self.write_state(disable_collisions=disabled)

    def close(self) -> None:
        self._section.close()

    def __enter__(self) -> SimStateController:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
