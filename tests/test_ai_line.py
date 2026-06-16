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
    """A tight corner should brake earlier (lower target) than a straight at the same speed."""
    straight = PurePursuit(_straight_line_along_x(), target_speed_kmh=90.0)
    curve = PurePursuit(_right_turn_line(), target_speed_kmh=90.0, min_corner_speed_kmh=45.0)
    # At the same actual speed just below the cap, the curve's target is lower, so it asks for
    # less gas (or brake) than the straight in the bend region.
    s_out = straight.control((10.0, 5.0, 0.0), (1.0, 0.0, 0.0), speed_kmh=80.0)
    c_out = curve.control((44.0, 5.0, 18.0), (0.0, 0.0, 1.0), speed_kmh=80.0)
    assert c_out.gas <= s_out.gas


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
