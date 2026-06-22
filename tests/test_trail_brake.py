"""Tests for the trail-braking technique analyzer (tools.ai_sidecar.trail_brake)."""

from __future__ import annotations

from tools.ai_sidecar.lap_dynamics import LapTrace
from tools.ai_sidecar.trail_brake import analyze_trail_braking, trail_braking_from_lap_archive


def _lap(brake: list[float], steer: list[float]) -> LapTrace:
    """A minimal LapTrace with controlled brake/steer over an evenly-splined lap."""
    n = len(brake)
    spline = [i / (n - 1) for i in range(n)]
    zeros = [0.0] * n
    return LapTrace(
        spline=spline,
        t_s=[float(i) for i in range(n)],
        v_ms=[50.0] * n,
        brake=brake,
        throttle=zeros,
        steer=steer,
        gear=[4.0] * n,
        x=zeros,
        z=zeros,
    )


def _one(brake, steer, *, apex):
    n = len(brake)
    return analyze_trail_braking(_lap(brake, steer), corners=[(0, apex, n - 1)])[0]


def test_good_trail_brake():
    n = 20
    brake = [max(0.0, 0.90 - 0.08 * i) for i in range(n)]  # smooth taper, off ~index 10
    steer = [0.30 if i >= 6 else 0.0 for i in range(n)]  # steering loads up into the corner
    f = _one(brake, steer, apex=12)
    assert f.classification == "good_trail_brake"
    assert f.trail_overlap >= 0.30
    assert f.release_abruptness < 0.40


def test_brakes_early_then_coasts():
    n = 20
    brake = [0.8 if i <= 5 else 0.0 for i in range(n)]  # done braking by index 5
    steer = [0.0] * n  # straight-line braking, no overlap
    f = _one(brake, steer, apex=15)  # apex far after brake-off
    assert f.classification == "brakes_early_then_coasts"
    assert f.brake_off_rel < -0.15


def test_trails_too_deep():
    n = 20
    # smooth taper that stays on the brakes past the apex (released ~index 13, apex 10)
    brake = [max(0.0, 0.60 - 0.04 * i) for i in range(n)]
    steer = [0.30 if i >= 6 else 0.0 for i in range(n)]
    f = _one(brake, steer, apex=10)
    assert f.classification == "trails_too_deep"
    assert f.brake_off_rel > 0.10
    assert f.release_abruptness < 0.40  # smooth taper, not a cliff


def test_abrupt_release():
    n = 20
    brake = [0.8 if i <= 9 else 0.0 for i in range(n)]  # high then instantly zero
    steer = [0.30 if i >= 5 else 0.0 for i in range(n)]
    f = _one(brake, steer, apex=12)
    assert f.classification == "abrupt_release"
    assert f.release_abruptness >= 0.40


def test_straight_braking_not_early():
    n = 20
    # brakes in a straight line (no steer overlap) but releases close to the apex (not early)
    brake = [0.7 if i <= 10 else 0.0 for i in range(n)]
    steer = [0.0] * n
    f = _one(brake, steer, apex=12)
    assert f.classification == "straight_braking"


def test_no_braking():
    n = 20
    f = _one([0.0] * n, [0.30 if i >= 6 else 0.0 for i in range(n)], apex=10)
    assert f.classification == "no_braking"
    assert f.brake_off_rel is None
    assert f.trail_overlap == 0.0


def test_corner_indices_are_zero_based_and_ordered():
    n = 30
    brake = [0.0] * n
    steer = [0.0] * n
    out = analyze_trail_braking(_lap(brake, steer), corners=[(0, 5, 9), (10, 15, 19), (20, 25, 29)])
    assert [f.corner for f in out] == [0, 1, 2]


def test_from_archive_returns_none_without_trace():
    assert trail_braking_from_lap_archive({}) is None
