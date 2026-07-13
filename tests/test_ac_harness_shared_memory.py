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
    PHYSICS_FINAL_FF_MIN_BYTES,
    PHYSICS_FINAL_FF_OFFSET,
    PHYSICS_MAP_BYTES,
    PHYSICS_MIN_BYTES,
    PHYSICS_PACKET_ID_OFFSET,
    AcGameStatus,
    DrivingEntryDetector,
    GraphicsSnapshot,
    PhysicsSnapshot,
    SharedMemoryUnavailable,
    open_shared_memory,
    parse_final_ff,
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
    ("raw", "expected"),
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
# With a physics page present, the detector requires an *observed* packetId CHANGE before a
# frame counts as "clear" (one sample can't tell advancing from frozen). So the first observe
# is a baseline (never clear) and N consecutive clears need N+1 advancing observes.
def _phys(packet_id: int) -> PhysicsSnapshot:
    return PhysicsSnapshot(packet_id=packet_id)


def test_detector_declares_driving_after_required_consecutive_clears():
    det = DrivingEntryDetector(required_live_reads=5)
    det.observe(_g(AcGameStatus.LIVE), _phys(0), now=0.0)  # baseline: no change observed yet
    assert det.consecutive_clear_reads == 0
    now, pkt = 0.0, 0
    for _ in range(5):
        now += 0.03
        pkt += 1
        det.observe(_g(AcGameStatus.LIVE), _phys(pkt), now=now)  # each advances the packet
    assert det.consecutive_clear_reads == 5
    assert det.driving is True


def test_detector_one_short_of_threshold_is_not_driving():
    det = DrivingEntryDetector(required_live_reads=5)
    det.observe(_g(AcGameStatus.LIVE), _phys(0), now=0.0)  # baseline
    now, pkt = 0.0, 0
    for _ in range(4):  # one advancing clear short of the threshold
        now += 0.03
        pkt += 1
        det.observe(_g(AcGameStatus.LIVE), _phys(pkt), now=now)
    assert det.consecutive_clear_reads == 4
    assert det.driving is False


def test_detector_never_drives_while_in_pit():
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    for i in range(10):
        det.observe(_g(AcGameStatus.LIVE, in_pit=True), _phys(i), now=now)
        now += 0.03
    assert det.driving is False


def test_detector_never_drives_while_paused():
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    for i in range(10):
        det.observe(_g(AcGameStatus.PAUSE), _phys(i), now=now)
        now += 0.03
    assert det.driving is False


def test_detector_resets_consecutive_on_interruption():
    det = DrivingEntryDetector(required_live_reads=5)
    det.observe(_g(AcGameStatus.LIVE), _phys(0), now=0.0)  # baseline
    now, pkt = 0.0, 0
    for _ in range(3):
        now += 0.03
        pkt += 1
        det.observe(_g(AcGameStatus.LIVE), _phys(pkt), now=now)
    assert det.consecutive_clear_reads == 3
    # A single in-pit frame (e.g. respawn to pits) resets the accumulator.
    det.observe(_g(AcGameStatus.LIVE, in_pit=True), _phys(pkt + 1), now=now + 0.03)
    assert det.consecutive_clear_reads == 0
    assert det.driving is False


def test_detector_stagnant_physics_blocks_driving_even_when_status_live():
    # AC sometimes leaves Status==LIVE on a frozen frame; once advancement HAS been seen, a
    # freeze past the window must veto "driving" (CM's documented packetId-stagnation trick).
    det = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, _phys(1), now=0.0)  # baseline
    det.observe(g, _phys(2), now=0.03)  # advanced -> clear, change @0.03
    assert det.consecutive_clear_reads == 1
    det.observe(g, _phys(2), now=0.10)  # frozen 0.07s > 0.05 -> stagnant, not clear
    assert det.consecutive_clear_reads == 0
    assert det.driving is False


def test_detector_advancing_physics_recovers_after_a_freeze():
    # Non-vacuous: advance -> freeze (stagnant, resets) -> advance again (recovers to driving).
    det = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, _phys(1), now=0.0)  # baseline
    det.observe(g, _phys(2), now=0.03)  # clear=1
    det.observe(g, _phys(2), now=0.10)  # frozen -> stagnant -> reset to 0
    assert det.consecutive_clear_reads == 0
    det.observe(g, _phys(3), now=0.11)  # advances again -> clear=1
    det.observe(g, _phys(4), now=0.13)  # clear=2 -> driving
    assert det.driving is True


def test_detector_never_declares_driving_on_frozen_first_physics_even_with_fast_poll():
    # Regression (review finding): if AC is LIVE-but-stalled before the first read and we poll
    # FASTER than the stagnation window, a packet that has NEVER advanced must never count as
    # clear — otherwise required_live_reads frozen frames inside the window declare false driving.
    det = DrivingEntryDetector(required_live_reads=5, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)  # status LIVE, not in pit, but physics frozen at one value
    now = 0.0
    for _ in range(12):  # 12 reads at 10ms << 50ms window
        det.observe(g, _phys(7), now=now)
        now += 0.01
    assert det.consecutive_clear_reads == 0
    assert det.driving is False


def test_detector_tolerates_missing_physics_page():
    # If only the graphics page maps, the stagnation guard is skipped and the detector relies
    # on status + pit alone (so the first read can already be clear).
    det = DrivingEntryDetector(required_live_reads=3)
    now = 0.0
    for _ in range(3):
        det.observe(_g(AcGameStatus.LIVE), None, now=now)
        now += 0.5  # large gaps must not trip stagnation when physics is absent
    assert det.driving is True


def test_detector_tolerates_physics_becoming_unavailable():
    # Regression (review finding): physics present -> driving, then the physics page disappears.
    # A stale last-change timestamp must NOT wedge the detector into false stagnation.
    det = DrivingEntryDetector(required_live_reads=3, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, _phys(1), now=0.0)  # baseline
    det.observe(g, _phys(2), now=0.03)  # clear=1
    det.observe(g, _phys(3), now=0.06)  # clear=2
    det.observe(g, _phys(4), now=0.09)  # clear=3 -> driving
    assert det.driving is True
    det.observe(g, None, now=0.50)  # physics gone, huge gap; must stay clear via status+pit
    assert det.driving is True


def test_detector_stagnation_boundary_is_inclusive():
    # Elapsed == stagnation_seconds still counts as advancing (<=); just over it stagnates.
    at_boundary = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    g = _g(AcGameStatus.LIVE)
    at_boundary.observe(g, _phys(1), now=0.0)  # baseline
    at_boundary.observe(g, _phys(2), now=0.10)  # advanced -> clear, change @0.10
    at_boundary.observe(g, _phys(2), now=0.15)  # frozen exactly 0.05 later -> still advancing
    assert at_boundary.driving is True

    just_over = DrivingEntryDetector(required_live_reads=2, stagnation_seconds=0.05)
    just_over.observe(g, _phys(1), now=0.0)
    just_over.observe(g, _phys(2), now=0.10)
    just_over.observe(g, _phys(2), now=0.1501)  # 0.0501 > 0.05 -> stagnant
    assert just_over.driving is False


def test_detector_drives_after_baseline_then_change():
    det = DrivingEntryDetector(required_live_reads=1)
    g = _g(AcGameStatus.LIVE)
    det.observe(g, _phys(1), now=0.0)  # baseline (not clear yet)
    assert det.driving is False
    det.observe(g, _phys(2), now=0.03)  # advances -> clear=1 -> driving
    assert det.driving is True


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"required_live_reads": 0}, "required_live_reads must be >= 1"),
        ({"stagnation_seconds": 0.0}, "stagnation_seconds must be > 0"),
    ],
)
def test_detector_validates_constructor_args(kwargs: dict, match: str):
    with pytest.raises(ValueError, match=match):
        DrivingEntryDetector(**kwargs)


# --------------------------------------------------------------------------- opener guard
@pytest.mark.skipif(sys.platform == "win32", reason="off-Windows guard only meaningful off Windows")
def test_open_shared_memory_raises_off_windows():
    with pytest.raises(SharedMemoryUnavailable, match="Windows-only"):
        open_shared_memory("acpmf_graphics", 256)


# --------------------------------------------------------------------------- finalFF decode (#533)
def _physics_ff_bytes(final_ff: float, *, size: int = PHYSICS_FINAL_FF_MIN_BYTES) -> bytes:
    """Build an acpmf_physics buffer carrying finalFF at its documented offset (308)."""
    buf = bytearray(size)
    struct.pack_into("<f", buf, PHYSICS_FINAL_FF_OFFSET, final_ff)
    return bytes(buf)


def test_final_ff_constants_are_consistent():
    # finalFF is the last field the harness decodes; the mapped page must cover it.
    assert PHYSICS_FINAL_FF_OFFSET == 308
    assert PHYSICS_FINAL_FF_MIN_BYTES == PHYSICS_FINAL_FF_OFFSET + 4
    assert PHYSICS_MAP_BYTES >= PHYSICS_FINAL_FF_MIN_BYTES


@pytest.mark.parametrize("value", [0.0, 0.25, -0.5, 0.9, 1.0, -1.0])
def test_parse_final_ff_decodes_at_offset_308(value: float):
    decoded = parse_final_ff(_physics_ff_bytes(value))
    assert decoded == pytest.approx(value, abs=1e-6)


def test_parse_final_ff_rejects_short_buffer():
    with pytest.raises(ValueError, match="too short for finalFF"):
        parse_final_ff(bytes(PHYSICS_FINAL_FF_MIN_BYTES - 1))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_parse_final_ff_rejects_non_finite(bad: float):
    with pytest.raises(ValueError, match="non-finite"):
        parse_final_ff(_physics_ff_bytes(bad))


def test_parse_final_ff_does_not_clamp_out_of_range():
    # A magnitude >1 must be surfaced (evidence the offset is wrong), not silently clamped.
    assert parse_final_ff(_physics_ff_bytes(2.5)) == pytest.approx(2.5, abs=1e-6)
