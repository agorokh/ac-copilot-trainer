"""Pure unit tests for the AC shared-memory oracle (EPIC #154 L2 detect half).

These exercise the platform-independent halves of ``tools/ac_harness/shared_memory.py``:
the byte parsers and the :class:`DrivingEntryDetector` state machine. No Assetto Corsa, no
Windows, no mmap — synthetic buffers built at the exact documented struct offsets, and an
injected clock so the stagnation guard is deterministic. The Windows mmap opener is only
checked for its clean off-Windows failure (the live mmap path is validated on the rig via
the module's live-probe).
"""

from __future__ import annotations

import struct
import sys

import pytest

from tools.ac_harness.shared_memory import (
    GRAPHICS_IS_IN_PIT_OFFSET,
    GRAPHICS_MIN_BYTES,
    GRAPHICS_PACKET_ID_OFFSET,
    GRAPHICS_STATUS_OFFSET,
    PHYSICS_MIN_BYTES,
    PHYSICS_PACKET_ID_OFFSET,
    AcGameStatus,
    DrivingEntryDetector,
    GraphicsSnapshot,
    PhysicsSnapshot,
    SharedMemoryUnavailable,
    open_shared_memory,
    parse_graphics,
    parse_physics,
)


# --------------------------------------------------------------------------- helpers
def _graphics_bytes(*, packet_id: int, status: int, is_in_pit: bool) -> bytes:
    """Build an acpmf_graphics buffer with the three decoded fields at their real offsets."""
    buf = bytearray(GRAPHICS_MIN_BYTES)
    struct.pack_into("<i", buf, GRAPHICS_PACKET_ID_OFFSET, packet_id)
    struct.pack_into("<i", buf, GRAPHICS_STATUS_OFFSET, status)
    struct.pack_into("<i", buf, GRAPHICS_IS_IN_PIT_OFFSET, 1 if is_in_pit else 0)
    return bytes(buf)


def _physics_bytes(packet_id: int) -> bytes:
    buf = bytearray(PHYSICS_MIN_BYTES)
    struct.pack_into("<i", buf, PHYSICS_PACKET_ID_OFFSET, packet_id)
    return bytes(buf)


def _g(status: AcGameStatus, *, in_pit: bool = False, packet_id: int = 0) -> GraphicsSnapshot:
    return GraphicsSnapshot(packet_id=packet_id, status=status, is_in_pit=in_pit)


# --------------------------------------------------------------------------- parsers
def test_parse_graphics_decodes_fields_at_documented_offsets():
    snap = parse_graphics(_graphics_bytes(packet_id=4242, status=2, is_in_pit=False))
    assert snap.packet_id == 4242
    assert snap.status is AcGameStatus.LIVE
    assert snap.is_in_pit is False
    assert snap.is_live is True


def test_parse_graphics_decodes_in_pit_true():
    snap = parse_graphics(_graphics_bytes(packet_id=1, status=3, is_in_pit=True))
    assert snap.status is AcGameStatus.PAUSE
    assert snap.is_in_pit is True
    assert snap.is_live is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, AcGameStatus.OFF),
        (1, AcGameStatus.REPLAY),
        (2, AcGameStatus.LIVE),
        (3, AcGameStatus.PAUSE),
    ],
)
def test_parse_graphics_status_enum_mapping(raw: int, expected: AcGameStatus):
    snap = parse_graphics(_graphics_bytes(packet_id=0, status=raw, is_in_pit=False))
    assert snap.status is expected


def test_parse_graphics_unknown_status_kept_as_raw_int():
    # A future/unknown status must not crash the parser; it is kept as a raw int and
    # treated as "not LIVE" downstream.
    snap = parse_graphics(_graphics_bytes(packet_id=0, status=99, is_in_pit=False))
    assert snap.status == 99
    assert snap.is_live is False


def test_parse_graphics_rejects_short_buffer():
    with pytest.raises(ValueError, match="acpmf_graphics buffer too short"):
        parse_graphics(b"\x00" * (GRAPHICS_MIN_BYTES - 1))


def test_parse_physics_decodes_packet_id():
    assert parse_physics(_physics_bytes(777)).packet_id == 777


def test_parse_physics_rejects_short_buffer():
    with pytest.raises(ValueError, match="acpmf_physics buffer too short"):
        parse_physics(b"\x00" * (PHYSICS_MIN_BYTES - 1))


# --------------------------------------------------------------------------- detector
def test_detector_declares_driving_after_required_consecutive_reads():
    det = DrivingEntryDetector(required_live_reads=5)
    now = 0.0
    for i in range(4):  # one short of the threshold
        det.observe(_g(AcGameStatus.LIVE), PhysicsSnapshot(packet_id=i), now=now)
        now += 0.03
        assert det.driving is False
    det.observe(_g(AcGameStatus.LIVE), PhysicsSnapshot(packet_id=99), now=now)
    assert det.consecutive_clear_reads == 5
    assert det.driving is True


def test_detector_never_drives_while_in_pit():
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    for i in range(10):
        det.observe(_g(AcGameStatus.LIVE, in_pit=True), PhysicsSnapshot(packet_id=i), now=now)
        now += 0.03
    assert det.driving is False
    # LIVE and physics advancing, just in the pit box -> not "stuck in menu".
    assert det.stuck_in_menu(_g(AcGameStatus.LIVE, in_pit=True), now=now) is False


def test_detector_never_drives_while_paused_and_reports_stuck():
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    g = _g(AcGameStatus.PAUSE)
    for i in range(10):
        det.observe(g, PhysicsSnapshot(packet_id=i), now=now)
        now += 0.03
    assert det.driving is False
    assert det.stuck_in_menu(g, now=now) is True  # not LIVE -> stuck


def test_detector_resets_consecutive_on_interruption():
    det = DrivingEntryDetector(required_live_reads=5)
    now = 0.0
    for i in range(3):
        det.observe(_g(AcGameStatus.LIVE), PhysicsSnapshot(packet_id=i), now=now)
        now += 0.03
    assert det.consecutive_clear_reads == 3
    # A single in-pit frame (e.g. respawn to pits) resets the accumulator.
    det.observe(_g(AcGameStatus.LIVE, in_pit=True), PhysicsSnapshot(packet_id=3), now=now)
    assert det.consecutive_clear_reads == 0
    assert det.driving is False


def test_detector_stagnant_physics_blocks_driving_even_when_status_live():
    # AC sometimes leaves Status==LIVE on a frozen frame; the packetId-stagnation guard
    # (CM's documented trick) must veto "driving" in that case.
    det = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, PhysicsSnapshot(packet_id=1), now=0.0)  # clear=1, last change @0.0
    det.observe(g, PhysicsSnapshot(packet_id=1), now=0.10)  # frozen 0.10s > 0.05 -> not clear
    assert det.consecutive_clear_reads == 0
    assert det.driving is False
    assert det.stuck_in_menu(g, now=0.10) is True


def test_detector_advancing_physics_is_not_stagnant():
    det = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, PhysicsSnapshot(packet_id=1), now=0.0)
    det.observe(g, PhysicsSnapshot(packet_id=2), now=0.10)  # advanced -> change time updated
    assert det.driving is True


def test_detector_tolerates_missing_physics_page():
    # If only the graphics page maps, the stagnation guard is skipped and the detector
    # relies on status + pit state alone.
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    for _ in range(3):
        det.observe(_g(AcGameStatus.LIVE), None, now=now)
        now += 0.5  # large gaps must not trip stagnation when physics is absent
    assert det.driving is True


def test_detector_stuck_false_once_driving():
    det = DrivingEntryDetector(required_live_reads=1)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, PhysicsSnapshot(packet_id=1), now=0.0)
    assert det.driving is True
    assert det.stuck_in_menu(g, now=0.0) is False


@pytest.mark.parametrize("kwargs", [{"required_live_reads": 0}, {"stagnation_seconds": 0.0}])
def test_detector_validates_constructor_args(kwargs: dict):
    with pytest.raises(ValueError):
        DrivingEntryDetector(**kwargs)


# --------------------------------------------------------------------------- opener guard
@pytest.mark.skipif(sys.platform == "win32", reason="off-Windows guard only meaningful off Windows")
def test_open_shared_memory_raises_off_windows():
    with pytest.raises(SharedMemoryUnavailable, match="Windows-only"):
        open_shared_memory("acpmf_graphics", 256)
