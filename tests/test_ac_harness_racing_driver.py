"""Tests for the EPIC #154 Part G racing driver (#241) — pure speed-profile control."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from tools.ac_harness.lap_driver import PHASE_LAP
from tools.ac_harness.racing_driver import RacingDriver, load_speed_profile


def _straight_line(n: int, ds: float = 5.0) -> list[tuple[float, float, float]]:
    return [(i * ds, 0.0, 0.0) for i in range(n)]


def _ai_blob(speeds: list[float]) -> bytes:
    """Build a minimal version-7 fast_lane.ai with the given per-point speeds in the extra block."""
    n = len(speeds)
    out = bytearray(struct.pack("<4i", 7, n, 0, 0))
    for i in range(n):  # main points: x,y,z,length,id
        out += struct.pack("<3f f i", float(i * 5), 0.0, 0.0, float(i * 5), i)
    out += struct.pack("<i", n)  # extraCount
    for s in speeds:  # AiPointExtra: speed@0 + 17 filler floats = 72 bytes
        out += struct.pack("<f", s) + struct.pack("<17f", *([0.0] * 17))
    return bytes(out)


def test_load_speed_profile_parses_extra_speeds(tmp_path: Path):
    speeds = [10.0, 20.0, 60.0, 5.0, 40.0]
    f = tmp_path / "fast_lane.ai"
    f.write_bytes(_ai_blob(speeds))
    assert load_speed_profile(f) == pytest.approx(speeds)


def test_load_speed_profile_rejects_bad_extra_count(tmp_path: Path):
    blob = bytearray(_ai_blob([10.0, 20.0]))
    # corrupt the extraCount int32 (right after the 2 main points).
    struct.pack_into("<i", blob, 16 + 2 * 20, 99)
    f = tmp_path / "bad.ai"
    f.write_bytes(bytes(blob))
    with pytest.raises(ValueError, match="AiPointExtra count"):
        load_speed_profile(f)


def test_backward_pass_creates_a_braking_point_before_a_slow_corner():
    # Flat-fast profile with one very slow "corner" point: the backward pass must pull the speeds
    # BEFORE it down (so the car brakes early), ramping up away from the corner.
    n = 40
    line = _straight_line(n, ds=5.0)
    speeds = [80.0] * n
    speeds[30] = 8.0  # a slow corner at index 30 (m/s)
    d = RacingDriver(line, speeds, pace=1.0, max_speed_kmh=400.0, brake_g=1.0)
    # profile is in m/s; points approaching 30 must decrease toward it.
    assert d.profile[30] == pytest.approx(8.0, abs=0.5)
    assert d.profile[29] > d.profile[30]
    assert d.profile[27] > d.profile[29]  # ramps up as you get further before the corner
    assert d.profile[25] < 80.0  # the high straight speed was pulled down by the upcoming corner


def test_backward_pass_wraps_cyclically_around_slow_corner_at_start():
    # Slow corner at index 0: backward pass wraps so speeds at the end of the lap are also capped.
    n = 40
    line = _straight_line(n, ds=5.0)
    speeds = [80.0] * n
    speeds[0] = 8.0
    d = RacingDriver(line, speeds, pace=1.0, max_speed_kmh=400.0, brake_g=1.0)
    assert d.profile[0] == pytest.approx(8.0, abs=0.5)
    assert d.profile[-1] < 80.0
    assert d.profile[-1] > d.profile[0]
    assert d.profile[-2] > d.profile[-1]


def test_longitudinal_brakes_hard_when_well_over_target():
    line = _straight_line(20)
    d = RacingDriver(line, [30.0] * 20, pace=1.0, max_speed_kmh=400.0, brake_g=5.0)  # ~flat 30 m/s
    # car at 30 m/s wanting ~14 m/s (50 km/h target) -> way over -> hard brake.
    d.profile = [14.0] * 20
    gas, brake = d._longitudinal(5, speed_kmh=30 * 3.6, steer=0.0)
    assert gas == 0.0
    assert brake > 0.9  # hard braking


def test_longitudinal_throttles_when_under_target():
    line = _straight_line(20)
    d = RacingDriver(line, [60.0] * 20, pace=1.0, max_speed_kmh=400.0, brake_g=5.0)
    d.profile = [40.0] * 20
    gas, brake = d._longitudinal(5, speed_kmh=10 * 3.6, steer=0.0)
    assert brake == 0.0
    assert gas > 0.5


def test_trail_braking_releases_brake_with_steering():
    line = _straight_line(20)
    d = RacingDriver(line, [30.0] * 20, pace=1.0, max_speed_kmh=400.0, brake_g=5.0)
    d.profile = [14.0] * 20
    _, brake_straight = d._longitudinal(5, 30 * 3.6, steer=0.0)
    _, brake_turning = d._longitudinal(5, 30 * 3.6, steer=0.8)
    assert brake_turning < brake_straight  # trail braking bleeds brake off under steering
    assert brake_turning > 0.0  # but never fully off mid-corner


def test_traction_lifts_throttle_with_steering():
    line = _straight_line(20)
    d = RacingDriver(line, [60.0] * 20, pace=1.0, max_speed_kmh=400.0, brake_g=5.0)
    d.profile = [40.0] * 20
    gas_straight, _ = d._longitudinal(5, 10 * 3.6, steer=0.0)
    gas_turning, _ = d._longitudinal(5, 10 * 3.6, steer=0.8)
    assert gas_turning < gas_straight  # traction-limited throttle when cornering


def test_gear_pulse_shifts_out_of_neutral_then_up_then_down():
    d = RacingDriver(_straight_line(10), [40.0] * 10, max_speed_kmh=200.0)
    assert d._gear_pulse(900, 1, 0.0, 1.0) == (True, False)  # out of neutral
    assert d._gear_pulse(8000, 3, 90.0, 5.0) == (True, False)  # up past rpm_up
    assert d._gear_pulse(3000, 4, 90.0, 9.0) == (False, True)  # down past rpm_dn


def test_default_upshift_fires_below_first_gear_rev_limiter():
    # Live on the GT3 R, 1st gear's rev limiter plateaus at ~7400 rpm. If the shift point sits ABOVE
    # it, the car bounces off the limiter stuck in 1st (observed) — the default must be below it.
    d = RacingDriver(_straight_line(10), [80.0] * 10, max_speed_kmh=200.0)
    assert d.rpm_up < 7400
    assert d._gear_pulse(7100, 2, 70.0, 1.0) == (True, False)  # upshifts before the limiter
    assert d.max_gear >= 7  # reaches 6th (AC gear 7)


def test_step_out_phase_clamps_then_transitions_to_lap():
    line = _straight_line(30)
    d = RacingDriver(
        line, [40.0] * 30, max_speed_kmh=120.0, merge_distance_m=9.0, merge_speed_kmh=12.0
    )
    # On the line (dist 0) and above merge speed -> transitions OUT->LAP; LAP commands racing
    # longitudinal (here under target -> throttle).
    frame = d.step((10.0, 0.0, 0.0), (1.0, 0.0, 0.0), speed_kmh=40.0, rpm=5000, gear=3, now=1.0)
    assert d.phase == PHASE_LAP
    assert frame.phase == PHASE_LAP


def test_step_lap_phase_brakes_over_profile():
    line = _straight_line(30)
    d = RacingDriver(line, [12.0] * 30, pace=1.0, max_speed_kmh=120.0, brake_g=5.0)
    d.phase = PHASE_LAP
    # 110 km/h on a 12 m/s (~43 km/h) profile -> braking.
    frame = d.step((10.0, 0.0, 0.0), (1.0, 0.0, 0.0), speed_kmh=110.0, rpm=6000, gear=4, now=1.0)
    assert frame.brake > 0.0
    assert frame.gas == 0.0


def test_constructor_validates():
    line = _straight_line(10)
    with pytest.raises(ValueError, match="length mismatch"):
        RacingDriver(line, [40.0] * 9)
    with pytest.raises(ValueError, match="pace"):
        RacingDriver(line, [40.0] * 10, pace=1.5)
    with pytest.raises(ValueError, match="min_speed_kmh"):
        RacingDriver(line, [40.0] * 10, max_speed_kmh=30.0, min_speed_kmh=40.0)
