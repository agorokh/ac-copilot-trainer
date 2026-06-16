"""Pure-logic tests for :mod:`tools.ac_harness.lap_driver` (no mmap, no AC, no real clock).

Mirrors ``test_ai_line`` / ``test_custom_ai``: feed :meth:`LapDriver.step` synthetic poses + a
monotonic ``now`` and assert the phase machine, gear pulses, OUT-phase shaping, position-return
lap detection, and stuck/recovery signalling.
"""

from __future__ import annotations

import pytest

from tools.ac_harness.lap_driver import PHASE_LAP, PHASE_OUT, LapDriver

# A simple straight racing line down +z (the controller only does planar (x, z) geometry).
STRAIGHT_LINE = [(0.0, 0.0, float(z)) for z in range(0, 400, 2)]


def _driver(**kw) -> LapDriver:
    return LapDriver(STRAIGHT_LINE, **kw)


def test_starts_in_out_phase() -> None:
    assert _driver().phase == PHASE_OUT


def test_out_phase_clamps_steer_and_floors_gas() -> None:
    d = _driver(out_steer_clamp=0.35, out_gas=0.30)
    # Car far off the line (x=40) so pure pursuit wants a big steer; OUT must clamp it.
    f = d.step((40.0, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=5.0, rpm=3000, gear=2, now=0.0)
    assert f.phase == PHASE_OUT
    assert abs(f.steer) <= 0.35 + 1e-9
    assert f.gas >= 0.30 - 1e-9
    assert f.brake == 0.0


def test_merges_out_to_lap_when_close_and_fast() -> None:
    d = _driver(merge_distance_m=9.0, merge_speed_kmh=10.0)
    # On the line (x~0), moving: should switch to LAP.
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.1)
    assert f.phase == PHASE_LAP


def test_no_merge_when_close_but_too_slow() -> None:
    d = _driver(merge_distance_m=9.0, merge_speed_kmh=10.0)
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=4.0, rpm=1200, gear=2, now=0.1)
    assert f.phase == PHASE_OUT


def test_shift_out_of_neutral() -> None:
    # gear 1 == NEUTRAL in AC encoding -> must request an up-shift toward 1st (gear 2).
    d = _driver()
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=0.0, rpm=900, gear=1, now=0.0)
    assert f.gear_up is True
    assert f.gear_dn is False


def test_upshift_above_rpm_then_cooldown_blocks_second() -> None:
    d = _driver(rpm_up=7800.0, max_gear=4, shift_cooldown_s=0.35)
    f1 = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=60.0, rpm=8200, gear=2, now=1.0)
    assert f1.gear_up is True
    # within cooldown -> no second shift even though rpm still high
    f2 = d.step((0.5, 0.0, 52.0), (0.0, 0.0, 1.0), speed_kmh=61.0, rpm=8200, gear=3, now=1.1)
    assert f2.gear_up is False
    # after cooldown -> shifts again
    f3 = d.step((0.5, 0.0, 54.0), (0.0, 0.0, 1.0), speed_kmh=62.0, rpm=8200, gear=3, now=1.6)
    assert f3.gear_up is True


def test_no_upshift_at_max_gear() -> None:
    d = _driver(rpm_up=7800.0, max_gear=3)
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=60.0, rpm=8200, gear=3, now=2.0)
    assert f.gear_up is False


def test_downshift_below_rpm_when_rolling() -> None:
    d = _driver(rpm_dn=3200.0)
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=30.0, rpm=2800, gear=3, now=3.0)
    assert f.gear_dn is True
    assert f.gear_up is False


def test_no_downshift_in_first_gear() -> None:
    d = _driver(rpm_dn=3200.0)
    f = d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=10.0, rpm=2000, gear=2, now=3.0)
    assert f.gear_dn is False


def test_stuck_triggers_recovery_after_threshold() -> None:
    d = _driver(stuck_speed_kmh=3.0, stuck_seconds=5.0)
    # Pinned against something: slow while asking for throttle (gas>0.4 via OUT floor).
    pose = ((5.0, 0.0, 10.0), (0.0, 0.0, 1.0))
    f0 = d.step(*pose, speed_kmh=0.0, rpm=4000, gear=2, now=0.0)
    assert f0.needs_recovery is False
    f1 = d.step(*pose, speed_kmh=0.0, rpm=4000, gear=2, now=4.9)
    assert f1.needs_recovery is False
    f2 = d.step(*pose, speed_kmh=0.0, rpm=4000, gear=2, now=5.2)
    assert f2.needs_recovery is True


def test_recovery_clears_when_moving_again() -> None:
    d = _driver(stuck_seconds=5.0)
    pose = ((5.0, 0.0, 10.0), (0.0, 0.0, 1.0))
    d.step(*pose, speed_kmh=0.0, rpm=4000, gear=2, now=0.0)
    moving = d.step(*pose, speed_kmh=30.0, rpm=4000, gear=2, now=3.0)
    assert moving.needs_recovery is False
    # clock advances past the original threshold but the stuck timer was reset
    again = d.step(*pose, speed_kmh=0.0, rpm=4000, gear=2, now=6.0)
    assert again.needs_recovery is False


def test_on_recovery_resets_to_out_phase() -> None:
    d = _driver()
    d.step((0.5, 0.0, 50.0), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.1)
    assert d.phase == PHASE_LAP
    d.on_recovery()
    assert d.phase == PHASE_OUT


def test_position_return_lap_detection() -> None:
    # Small min_lap + radius so we can close a lap with a short synthetic path.
    d = _driver(min_lap_m=30.0, return_radius_m=3.0, merge_distance_m=50.0, merge_speed_kmh=1.0)
    # First LAP-phase frame anchors the lap at the car's position.
    f = d.step((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.0)
    assert f.phase == PHASE_LAP and f.lap_completed is False
    # Drive out ~40 m down +z (no closure: too far from anchor).
    seen_completed = False
    for i, z in enumerate(range(2, 42, 2), start=1):
        fr = d.step(
            (0.0, 0.0, float(z)), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.1 * i
        )
        assert fr.lap_completed is False
    # Now travel back to within the return radius of the anchor (0,0): lap closes once distance
    # travelled has exceeded min_lap_m (we've covered ~40 out + ~40 back > 30).
    n = 50
    for z in range(40, -2, -2):
        n += 1
        fr = d.step(
            (0.0, 0.0, float(z)), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.1 * n
        )
        if fr.lap_completed:
            seen_completed = True
            break
    assert seen_completed


def test_lap_not_counted_in_out_phase() -> None:
    # In OUT phase, lap_completed is always False regardless of motion.
    d = _driver(min_lap_m=1.0, return_radius_m=100.0, merge_distance_m=0.0)  # never merges
    f = d.step((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), speed_kmh=42.0, rpm=3800, gear=2, now=0.0)
    assert f.phase == PHASE_OUT
    assert f.lap_completed is False


def test_steer_sign_matches_pure_pursuit_right_positive() -> None:
    # PurePursuit defines right_unit = (-fwd_z, fwd_x); for fwd=+z that is -x, so the car's right
    # is the -x side. A car at x=+3 facing +z has the line (x=0) on its right -> steer > 0 (right);
    # a car at x=-3 has it on its left -> steer < 0. (Verified live: steer>0 turns the car right.)
    d_right = _driver(merge_distance_m=100.0, merge_speed_kmh=1.0)
    f_right = d_right.step(
        (3.0, 0.0, 10.0), (0.0, 0.0, 1.0), speed_kmh=40.0, rpm=3800, gear=2, now=0.0
    )
    assert f_right.phase == PHASE_LAP
    assert f_right.steer > 0.0

    d_left = _driver(merge_distance_m=100.0, merge_speed_kmh=1.0)
    f_left = d_left.step(
        (-3.0, 0.0, 10.0), (0.0, 0.0, 1.0), speed_kmh=40.0, rpm=3800, gear=2, now=0.0
    )
    assert f_left.steer < 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
