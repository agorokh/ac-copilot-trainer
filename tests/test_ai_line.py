"""Pure unit tests for the racing-line parser + pure-pursuit controller.

No Assetto Corsa, no mmap, no filesystem track data: the binary parser is exercised against
a synthetic ``fast_lane.ai`` buffer assembled at the documented version-7 offsets, and the
controller against synthetic straight / curved lines built in memory. This mirrors the #175
shared-memory oracle's split — the pure halves are CI-verifiable on any OS.

The controller's coordinate convention (asserted here so it cannot silently flip):
``(x, y, z)`` with ``y`` vertical; pursuit runs in the ``(x, z)`` ground plane; ``steer > 0``
aims the car to its right.
"""

from __future__ import annotations

import struct

import pytest

from tools.ac_harness.ai_line import (
    ControlOutput,
    PurePursuit,
    load_ai_line,
)


# --------------------------------------------------------------------------- fixtures
def _straight_line_along_x(n: int = 50, step: float = 2.0) -> list[tuple[float, float, float]]:
    """A flat straight running in +x at constant z=0, y=5 (ground height)."""
    return [(i * step, 5.0, 0.0) for i in range(n)]


def _right_turn_line() -> list[tuple[float, float, float]]:
    """A line that goes +x then curves toward +z (a right-hand turn for a +x-facing car)."""
    pts: list[tuple[float, float, float]] = [(i * 2.0, 5.0, 0.0) for i in range(20)]
    # quarter arc bending toward +z
    import math

    cx, cz = pts[-1][0], pts[-1][2] + 20.0  # arc centre to the car's right (+z)
    for k in range(1, 25):
        ang = -math.pi / 2 + (math.pi / 2) * (k / 25)
        pts.append((cx + 20.0 * math.cos(ang), 5.0, cz + 20.0 * math.sin(ang)))
    return pts


def _closed_loop_square(side: float = 10.0) -> list[tuple[float, float, float]]:
    """A 4-point CLOSED circuit: a ``side``×``side`` square on the ground plane (y=5).

    Unlike ``_straight_line_along_x`` / ``_right_turn_line`` (both OPEN), this is a genuine
    closed loop. The controller treats the line as cyclic — the implicit last->first segment
    closes it — so this fixture is what exercises the wrap paths the open fixtures never reach:
    the closing entry in ``_seg_len``, the ``% n`` wrap in ``_advance``, and ``_curvature_ahead``
    detecting a corner that lies across the start/finish line. With ``side=10`` the corners are
    at (0,0)->(10,0)->(10,10)->(0,10) in the (x, z) plane and every segment is exactly ``side`` m.
    """
    return [(0.0, 5.0, 0.0), (side, 5.0, 0.0), (side, 5.0, side), (0.0, 5.0, side)]


def _fast_lane_bytes(points: list[tuple[float, float, float]]) -> bytes:
    """Assemble a minimal but structurally valid version-7 fast_lane.ai buffer.

    Header (version=7, count, lapTime=0, sampleCount=0) + count*20-byte points
    (x,y,z float, length float, id int32). No extra/grid block is needed: the parser only
    reads the header and the main point block.
    """
    buf = bytearray()
    buf += struct.pack("<4i", 7, len(points), 0, 0)
    length = 0.0
    prev: tuple[float, float, float] | None = None
    for i, (x, y, z) in enumerate(points):
        if prev is not None:
            import math

            length += math.dist((x, y, z), prev)
        buf += struct.pack("<3f", x, y, z)
        buf += struct.pack("<f", length)
        buf += struct.pack("<i", i)
        prev = (x, y, z)
    return bytes(buf)


# --------------------------------------------------------------------------- parser
def test_load_ai_line_round_trips_positions(tmp_path):
    pts = [(1.0, 5.0, 2.0), (3.0, 5.0, 4.0), (5.0, 5.0, 6.0)]
    path = tmp_path / "fast_lane.ai"
    path.write_bytes(_fast_lane_bytes(pts))

    loaded = load_ai_line(path)

    assert len(loaded) == 3
    for got, want in zip(loaded, pts, strict=True):
        assert got == pytest.approx(want)


def test_load_ai_line_accepts_str_path(tmp_path):
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 1.0)]
    path = tmp_path / "fast_lane.ai"
    path.write_bytes(_fast_lane_bytes(pts))
    assert len(load_ai_line(str(path))) == 2


def test_load_ai_line_rejects_short_file(tmp_path):
    path = tmp_path / "fast_lane.ai"
    path.write_bytes(b"\x07\x00\x00")  # < 16-byte header
    with pytest.raises(ValueError, match="too short"):
        load_ai_line(path)


def test_load_ai_line_rejects_non_positive_count(tmp_path):
    path = tmp_path / "fast_lane.ai"
    path.write_bytes(struct.pack("<4i", 7, 0, 0, 0))
    with pytest.raises(ValueError, match="non-positive point count"):
        load_ai_line(path)


def test_load_ai_line_rejects_count_overflowing_file(tmp_path):
    # count claims 1000 points but the file only carries the header.
    path = tmp_path / "fast_lane.ai"
    path.write_bytes(struct.pack("<4i", 7, 1000, 0, 0))
    with pytest.raises(ValueError, match="does not fit the file"):
        load_ai_line(path)


def test_load_ai_line_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ai_line(tmp_path / "nope.ai")


# --------------------------------------------------------------------------- construction
def test_pure_pursuit_requires_two_points():
    with pytest.raises(ValueError, match="at least 2"):
        PurePursuit([(0.0, 0.0, 0.0)])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"lookahead_m": 0.0}, "lookahead_m"),
        ({"target_speed_kmh": -1.0}, "speed caps"),
        ({"min_corner_speed_kmh": 200.0}, "cannot exceed"),
        ({"wheelbase_m": 0.0}, "must be > 0"),
    ],
)
def test_pure_pursuit_validates_params(kwargs, match):
    with pytest.raises(ValueError, match=match):
        PurePursuit(_straight_line_along_x(), **kwargs)


# --------------------------------------------------------------------------- steering sign
def test_steer_zero_on_straight_when_aligned():
    pp = PurePursuit(_straight_line_along_x())
    # car on the line, facing +x: aim point is dead ahead -> no steer.
    out = pp.control(position_xyz=(10.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=50.0)
    assert isinstance(out, ControlOutput)
    assert out.steer == pytest.approx(0.0, abs=1e-6)


def test_steer_right_when_offset_left_of_line():
    """Car is displaced to -z (its left) of a +x line; correcting back is a right turn."""
    pp = PurePursuit(_straight_line_along_x())
    out = pp.control(position_xyz=(10.0, 5.0, -3.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=50.0)
    # aim point is at z=0 (to the car's right, +z) -> steer > 0.
    assert out.steer > 0.0


def test_steer_left_when_offset_right_of_line():
    pp = PurePursuit(_straight_line_along_x())
    out = pp.control(position_xyz=(10.0, 5.0, 3.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=50.0)
    assert out.steer < 0.0


def test_steer_sign_consistent_for_right_hand_curve():
    """Driving a line that bends toward +z should command a positive (right) steer."""
    pp = PurePursuit(_right_turn_line(), lookahead_m=10.0)
    # place the car partway down the straight, aligned +x, just before the bend.
    out = pp.control(position_xyz=(34.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=50.0)
    assert out.steer > 0.0


def test_steer_clamped_to_unit_range():
    pp = PurePursuit(_right_turn_line(), lookahead_m=4.0, max_steer_curvature=0.01)
    out = pp.control(position_xyz=(34.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=50.0)
    assert -1.0 <= out.steer <= 1.0


def test_aim_point_behind_commands_full_lock():
    """If the look-ahead point is behind the car (facing backward), steer saturates."""
    pp = PurePursuit(_straight_line_along_x())
    # facing -x while the aim point is ahead in +x -> forward_offset < 0 -> full lock.
    out = pp.control(position_xyz=(10.0, 5.0, -1.0), look_dir_xyz=(-1.0, 0.0, 0.0), speed_kmh=10.0)
    assert abs(out.steer) == pytest.approx(1.0)


def test_zero_heading_creeps_forward():
    pp = PurePursuit(_straight_line_along_x())
    out = pp.control(position_xyz=(0.0, 5.0, 0.0), look_dir_xyz=(0.0, 0.0, 0.0), speed_kmh=0.0)
    assert out.gas > 0.0
    assert out.brake == 0.0
    assert out.steer == 0.0


# --------------------------------------------------------------------------- longitudinal
def test_throttle_when_below_target_on_straight():
    pp = PurePursuit(_straight_line_along_x(), target_speed_kmh=90.0)
    out = pp.control(position_xyz=(10.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=20.0)
    assert out.gas > 0.0
    assert out.brake == 0.0


def test_brake_when_over_target_on_straight():
    pp = PurePursuit(_straight_line_along_x(), target_speed_kmh=80.0)
    out = pp.control(position_xyz=(10.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=120.0)
    assert out.brake > 0.0
    assert out.gas == 0.0


def test_gas_and_brake_never_both_active():
    pp = PurePursuit(_right_turn_line())
    for speed in (0.0, 30.0, 60.0, 90.0, 130.0):
        out = pp.control(
            position_xyz=(20.0, 5.0, 0.0), look_dir_xyz=(1.0, 0.0, 0.0), speed_kmh=speed
        )
        assert out.gas == 0.0 or out.brake == 0.0
        assert 0.0 <= out.gas <= 1.0
        assert 0.0 <= out.brake <= 1.0


def test_corner_lowers_target_speed_vs_straight():
    """A tight corner must brake earlier (lower target) than a straight at the same speed.

    Two things this test guards against (both real defects a prior version had — Bugbot/Sourcery):
    (1) the car is placed MID-BEND, not at the arc tail where the curvature look-ahead runs off the
    open synthetic line and reads ~0 (making the corner invisible); (2) the assertion is STRICT
    ``<`` so deleting the corner-braking term would FAIL it, instead of passing on a 0.5==0.5 tie.
    A small ``curvature_lookahead_m`` keeps the window inside the short synthetic arc.
    """
    curve_line = _right_turn_line()
    straight = PurePursuit(_straight_line_along_x(), target_speed_kmh=90.0)
    curve = PurePursuit(
        curve_line, target_speed_kmh=90.0, min_corner_speed_kmh=45.0, curvature_lookahead_m=8.0
    )
    mid = curve_line[28]  # a point in the middle of the quarter-arc (indices 20..43)
    s_out = straight.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), speed_kmh=80.0)
    c_out = curve.control((mid[0], 5.0, mid[2]), (0.0, 0.0, 1.0), speed_kmh=80.0)
    assert c_out.gas < s_out.gas


# --------------------------------------------------------------------------- closed loop (cyclic)
# The controller's docstrings (and EPIC #154 driving a real lap) treat the racing line as a
# CLOSED circuit: ``_seg_len`` includes the last->first closing segment and ``_advance`` wraps
# ``% n`` so the look-ahead crosses start/finish. The open fixtures above never make any of that
# fire (their wrap only triggered incidentally, on an artificial 60 m closing segment, where the
# curvature collapsed to 0). These tests pin the cyclic behaviour directly on a 4-point square.
def test_seg_len_includes_closing_segment():
    """``_seg_len`` closes the loop: a 4-point square has 4 segments (not 3), each one side long.

    ``_seg_len[i]`` is the length of ``point[i] -> point[(i + 1) % n]``, so the final entry is
    the last->first closing segment that an open line would omit. For a 10 m square every side —
    including the closing left edge (0,10)->(0,0) — is 10 m, so the cyclic perimeter is 40 m.
    """
    pp = PurePursuit(_closed_loop_square(side=10.0))
    assert len(pp._seg_len) == 4
    for seg in pp._seg_len:
        assert seg == pytest.approx(10.0)


def test_advance_wraps_across_start_finish():
    """``_advance`` walks the cyclic line and wraps past index 0 at the start/finish line.

    Square perimeter = 40 m (4 × 10 m). Walking from index 0:
      * 25 m -> index 3 (third corner; no wrap yet)
      * 35 m -> index 0 (walked 0->1->2->3->0: the look-ahead crossed start/finish)
    From index 3 a 5 m step lands on index 0 via the closing segment. A budget beyond one full
    perimeter (45 m > 40 m) hits the one-lap guard and returns the point just behind the start
    (``(start + n - 1) % n``) rather than looping forever — the degenerate/over-budget backstop.
    """
    pp = PurePursuit(_closed_loop_square(side=10.0))
    assert pp._advance(0, 25.0) == 3
    assert pp._advance(0, 35.0) == 0  # wrapped across start/finish
    assert pp._advance(3, 5.0) == 0  # closing segment wraps to the start
    assert pp._advance(0, 45.0) == 3  # > perimeter -> one-lap fallback, never an infinite loop


def test_curvature_ahead_sees_corner_across_wrap():
    """Curvature look-ahead detects a corner whose window straddles the start/finish line.

    From index 3 the default 30 m curvature window walks 3->0->1->2 (mid = ``_advance(3, 15)`` = 1,
    end = ``_advance(3, 30)`` = 2), so the three sample points (p0=idx3, p1=idx1, p2=idx2) bracket a
    corner that sits *across* index 0. A non-cyclic ``_advance`` would instead clamp mid and end at
    the last index (3 == start), collapsing the in-vector to zero so ``_curvature_ahead`` returns
    0.0 — i.e. a non-zero result here is only possible because the look-ahead wraps. Hand value:
    turn = atan2(100, -100) = 3π/4 over arc = √200 + 10 ≈ 24.14 m, giving ≈ 0.0976 m⁻¹.
    """
    pp = PurePursuit(_closed_loop_square(side=10.0))
    curv = pp._curvature_ahead(3)
    assert curv > 0.0  # the corner across start/finish is seen, not masked as a straight
    assert curv == pytest.approx(0.0976, abs=1e-3)


def test_control_output_unpacks_as_tuple():
    pp = PurePursuit(_straight_line_along_x())
    gas, brake, steer = pp.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), speed_kmh=50.0)
    assert (gas, brake, steer) == (
        pytest.approx(pp.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), 50.0).gas),
        pytest.approx(pp.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), 50.0).brake),
        pytest.approx(pp.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), 50.0).steer),
    )


# --------------------------------------------------------------------------- nearest / determinism
def test_nearest_index_picks_closest_point():
    pp = PurePursuit(_straight_line_along_x(step=2.0))  # points at x = 0,2,4,...
    assert pp.nearest_index((9.0, 0.0)) == 4  # x=8 (index 4) is closest to 9
    assert pp.nearest_index((0.1, 0.0)) == 0


def test_control_is_deterministic():
    pp = PurePursuit(_right_turn_line())
    a = pp.control((20.0, 5.0, 1.0), (1.0, 0.0, 0.0), speed_kmh=55.0)
    b = pp.control((20.0, 5.0, 1.0), (1.0, 0.0, 0.0), speed_kmh=55.0)
    assert a == b
