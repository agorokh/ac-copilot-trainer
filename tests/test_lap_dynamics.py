"""Tests for per-corner driving signatures (tools.ai_sidecar.lap_dynamics)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tools.ai_sidecar.lap_dynamics import (
    corner_signatures,
    lap_trace_from_archive,
    segment_corners,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_corner_archive(
    *,
    radius: float = 30.0,
    ds: float = 2.0,
    n_pre: int = 40,
    n_arc: int = 30,
    n_post: int = 40,
    v_straight: float = 55.0,
    v_apex: float = 25.0,
    turn_sign: float = 1.0,
) -> dict:
    """Synthesize a straight→single-corner→straight lap archive (one clean apex)."""
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [turn_sign / radius] * n_arc + [0.0] * n_post
    # integrate heading + position
    theta = 0.0
    x, z = 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    # speed: hold, decel into arc, hold through apex, accel out
    decel_start, apex_i, accel_end = 25, n_pre + n_arc // 2, n_pre + n_arc + 5
    v = []
    for i in range(n):
        if i < decel_start:
            v.append(v_straight)
        elif i < apex_i:
            frac = (i - decel_start) / max(1, apex_i - decel_start)
            v.append(v_straight + (v_apex - v_straight) * frac)
        elif i < accel_end:
            frac = (i - apex_i) / max(1, accel_end - apex_i)
            v.append(v_apex + (v_straight - v_apex) * frac)
        else:
            v.append(v_straight)
    brake = [0.8 if decel_start <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [turn_sign * 0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    gear = [4] * n
    # cumulative time (ms) and spline
    t_ms = [0.0]
    for i in range(1, n):
        vavg = max(0.5, 0.5 * (v[i] + v[i - 1]))
        t_ms.append(t_ms[-1] + ds / vavg * 1000.0)
    total = ds * (n - 1)
    spline = [(ds * i) / total for i in range(n)]
    fields = ["spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz"]
    samples = [
        [
            spline[i],
            v[i] * 3.6,
            t_ms[i],
            throttle[i],
            brake[i],
            steer[i],
            gear[i],
            xs[i],
            0.0,
            zs[i],
        ]
        for i in range(n)
    ]
    return {
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap": {"lap_ms": int(t_ms[-1]), "is_valid": True},
        "trace": {"samples_count": n, "fields": fields, "samples": samples},
    }


# --- channel derivation -----------------------------------------------------
def test_lap_trace_basic_channels():
    lap = lap_trace_from_archive(_make_corner_archive())
    assert len(lap) == 110
    assert lap.car_id == "ks_porsche_911_gt3_r_2016"
    assert max(lap.v_kmh) == pytest.approx(55.0 * 3.6, rel=1e-3)
    # braking shows up as negative long_g, acceleration as positive
    assert min(lap.long_g) < -0.1
    assert max(lap.long_g) > 0.1


def test_lat_g_peaks_in_corner():
    lap = lap_trace_from_archive(_make_corner_archive(radius=30.0, v_apex=25.0))
    # apex v=25 m/s, kappa=1/30 -> lat_g ~= 25^2/30/9.81 ~= 2.1 g
    assert max(abs(g) for g in lap.lat_g) > 1.5


def test_missing_position_raises():
    bad = {"trace": {"fields": ["spline", "speed"], "samples": [[0.0, 100.0]]}}
    with pytest.raises(ValueError, match="position"):
        lap_trace_from_archive(bad)


def test_empty_trace_raises():
    with pytest.raises(ValueError):
        lap_trace_from_archive({"trace": {"fields": [], "samples": []}})


def test_time_fallback_when_no_ems():
    arch = _make_corner_archive()
    # drop the eMs channel
    fi = arch["trace"]["fields"].index("eMs")
    arch["trace"]["fields"].pop(fi)
    for row in arch["trace"]["samples"]:
        row.pop(fi)
    lap = lap_trace_from_archive(arch)
    assert lap.t_s[-1] > lap.t_s[0]  # monotonic time reconstructed from distance/speed


# --- segmentation + signatures ----------------------------------------------
def test_segments_single_corner():
    lap = lap_trace_from_archive(_make_corner_archive())
    corners = segment_corners(lap)
    assert len(corners) == 1
    entry_i, apex_i, exit_i = corners[0]
    assert entry_i < apex_i < exit_i


def test_signature_apex_is_speed_minimum():
    lap = lap_trace_from_archive(_make_corner_archive(v_apex=25.0))
    sig = corner_signatures(lap)[0]
    assert sig.min_speed_kmh == pytest.approx(25.0 * 3.6, abs=8.0)
    assert sig.min_speed_kmh < sig.entry_speed_kmh
    assert sig.min_speed_kmh < sig.exit_speed_kmh


def test_signature_brake_before_apex_throttle_after():
    lap = lap_trace_from_archive(_make_corner_archive())
    sig = corner_signatures(lap)[0]
    assert sig.brake_point_spline is not None
    assert sig.brake_point_spline < sig.apex_spline
    assert sig.brake_to_apex_m is not None and sig.brake_to_apex_m > 0
    assert sig.throttle_on_spline is not None
    assert sig.throttle_on_spline > sig.apex_spline


def test_signature_direction_follows_steer_sign():
    right = corner_signatures(lap_trace_from_archive(_make_corner_archive(turn_sign=1.0)))[0]
    left = corner_signatures(lap_trace_from_archive(_make_corner_archive(turn_sign=-1.0)))[0]
    assert right.direction == "right"
    assert left.direction == "left"


def test_signature_peak_g_reasonable():
    lap = lap_trace_from_archive(_make_corner_archive())
    sig = corner_signatures(lap)[0]
    assert sig.peak_lat_g > 1.0
    assert sig.peak_brake_g > 0.0  # decel detected as braking g
    assert sig.peak_accel_g > 0.0  # exit acceleration detected


def test_trail_brake_detected_when_braking_into_steer():
    # extend braking to overlap the steering region -> trail-brake fraction > 0
    arch = _make_corner_archive()
    fields = arch["trace"]["fields"]
    bi, si = fields.index("brake"), fields.index("steer")
    for row in arch["trace"]["samples"]:
        if abs(row[si]) > 0.05:  # while steering, keep some brake on (trail)
            row[bi] = max(row[bi], 0.3)
    lap = lap_trace_from_archive(arch)
    sig = corner_signatures(lap)[0]
    assert sig.trail_brake_frac > 0.0


def test_real_fixture_too_short_yields_no_corners():
    archive = json.loads((FIXTURES / "lap_archive_valid.json").read_text(encoding="utf-8"))
    lap = lap_trace_from_archive(archive)
    # 3-sample fixture: loader works, but too short to segment corners
    assert len(lap) == 3
    assert segment_corners(lap) == []
