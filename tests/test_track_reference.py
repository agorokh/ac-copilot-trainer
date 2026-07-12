"""Tests for the per-corner track reference envelope (tools.ai_sidecar.track_reference)."""

from __future__ import annotations

import math

from tools.ai_sidecar.lap_dynamics import LapTrace
from tools.ai_sidecar.track_reference import (
    CornerReference,
    add_corpus_lap,
    build_references,
    score_lap,
    sustained_brake_onsets,
)


def _corner_lap(
    *, v_apex: float = 25.0, v_straight: float = 55.0, brake_from: int = 25
) -> LapTrace:
    """A straight→single-corner→straight LapTrace (one clean apex) at a given apex speed."""
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < brake_from:
            v.append(v_straight)
        elif i < apex_i:
            v.append(
                v_straight + (v_apex - v_straight) * (i - brake_from) / max(1, apex_i - brake_from)
            )
        elif i < n_pre + n_arc + 5:
            v.append(
                v_apex + (v_straight - v_apex) * (i - apex_i) / max(1, n_pre + n_arc + 5 - apex_i)
            )
        else:
            v.append(v_straight)
    brake = [0.8 if brake_from <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_s = [0.0]
    for i in range(1, n):
        t_s.append(t_s[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])))
    spline = [(ds * i) / (ds * (n - 1)) for i in range(n)]
    return LapTrace(
        spline=spline,
        t_s=t_s,
        v_ms=v,
        brake=brake,
        throttle=throttle,
        steer=steer,
        gear=[4] * n,
        x=xs,
        z=zs,
    )


def test_build_references_captures_optimal_apex():
    optimal = _corner_lap(v_apex=30.0)  # the GGV-optimal line carries 30 m/s = 108 km/h at apex
    refs = build_references(optimal)
    assert len(refs) == 1
    assert refs[0].optimal_apex_kmh == _approx_kmh(30.0)
    # with no corpus yet, the realistic target IS the GGV optimum
    assert refs[0].target_apex_kmh == refs[0].optimal_apex_kmh
    assert refs[0].best_observed_apex_kmh is None


def test_corpus_keeps_the_fastest_apex():
    refs = build_references(_corner_lap(v_apex=30.0))
    add_corpus_lap(refs, _corner_lap(v_apex=24.0))  # slow lap
    add_corpus_lap(refs, _corner_lap(v_apex=28.0))  # faster lap
    assert refs[0].best_observed_apex_kmh == _approx_kmh(28.0)
    assert refs[0].n_corpus == 2
    assert refs[0].target_apex_kmh == _approx_kmh(28.0)  # target is now the corpus best
    assert refs[0].best_brake_point_spline is not None


def test_partial_lap_does_not_reset_a_faster_best():
    refs = build_references(_corner_lap(v_apex=30.0))
    add_corpus_lap(refs, _corner_lap(v_apex=28.0))
    best_before = refs[0].best_observed_apex_kmh
    # a lap with NO samples in the corner window must not overwrite the best
    empty = LapTrace(
        [0.0, 0.001],
        [0.0, 0.1],
        [50.0, 50.0],
        [0, 0],
        [1, 1],
        [0, 0],
        [4, 4],
        [0.0, 1.0],
        [0.0, 0.0],
    )
    add_corpus_lap(refs, empty)
    assert refs[0].best_observed_apex_kmh == best_before


def test_score_lap_flags_apex_deficit_vs_target():
    refs = build_references(_corner_lap(v_apex=30.0))
    add_corpus_lap(refs, _corner_lap(v_apex=29.0))  # realistic best target ~104 km/h (29 m/s)
    driven = _corner_lap(v_apex=23.0)  # ~83 km/h apex → ~22 km/h under the target
    scores = score_lap(refs, driven)
    assert len(scores) == 1
    s = scores[0]
    assert s.deficit_to_target_kmh > 0
    assert any("under the best lap" in f for f in s.findings)
    assert "vs target" in s.headline


def test_score_lap_on_target_no_finding():
    refs = build_references(_corner_lap(v_apex=30.0))
    add_corpus_lap(refs, _corner_lap(v_apex=30.0))
    scores = score_lap(refs, _corner_lap(v_apex=30.0))
    assert scores[0].deficit_to_target_kmh < 2.0
    assert scores[0].findings == []
    assert "on target" in scores[0].headline


def _approx_kmh(v_ms: float) -> float:
    return round(v_ms * 3.6, 1)


# ---- issue #522: multi-zone brake marks -----------------------------------------------------


def _flat_trace(brake_by_spline: list[tuple[float, float]], *, n: int = 200) -> LapTrace:
    """A constant-speed straight-line LapTrace whose brake pedal follows ``brake_by_spline``
    ranges ``(lo, hi) -> 0.8`` (else 0), for exercising the brake-zone extraction directly."""
    spline = [i / (n - 1) for i in range(n)]

    def pedal(s: float) -> float:
        return 0.8 if any(lo <= s <= hi for lo, hi in brake_by_spline) else 0.0

    return LapTrace(
        spline=spline,
        t_s=[0.1 * i for i in range(n)],
        v_ms=[40.0] * n,
        brake=[pedal(s) for s in spline],
        throttle=[0.0] * n,
        steer=[0.0] * n,
        gear=[4] * n,
        x=[2.0 * i for i in range(n)],
        z=[0.0] * n,
    )


def test_sustained_brake_onsets_splits_distinct_zones():
    lap = _flat_trace([(0.30, 0.33), (0.40, 0.42)])
    onsets = sustained_brake_onsets(lap, 0.25, 0.50)
    assert len(onsets) == 2
    assert onsets[0] == _approx_spline(0.30)
    assert onsets[1] == _approx_spline(0.40)


def test_sustained_brake_onsets_filters_light_lifts_and_blips():
    lap = _flat_trace([(0.30, 0.33)])
    # a light lift (peak 0.2 < min_peak) between real zones is NOT a coachable mark
    lift = [0.2 if 0.40 <= s <= 0.42 else b for s, b in zip(lap.spline, lap.brake, strict=True)]
    lap2 = LapTrace(
        spline=lap.spline,
        t_s=lap.t_s,
        v_ms=lap.v_ms,
        brake=lift,
        throttle=lap.throttle,
        steer=lap.steer,
        gear=lap.gear,
        x=lap.x,
        z=lap.z,
    )
    onsets = sustained_brake_onsets(lap2, 0.25, 0.50)
    assert len(onsets) == 1 and onsets[0] == _approx_spline(0.30)
    # a single-sample blip is not a zone either (min_run)
    blip = list(lap.brake)
    blip[150] = 0.9  # isolated sample at spline ~0.754
    lap3 = LapTrace(
        spline=lap.spline,
        t_s=lap.t_s,
        v_ms=lap.v_ms,
        brake=blip,
        throttle=lap.throttle,
        steer=lap.steer,
        gear=lap.gear,
        x=lap.x,
        z=lap.z,
    )
    assert sustained_brake_onsets(lap3, 0.70, 0.80) == []


def test_add_corpus_lap_captures_every_zone_of_a_merged_window():
    """#522 coverage: a merged esses window holds several real brake zones — the best lap's
    EVERY sustained zone becomes a mark, with best_brake_point_spline staying the first."""
    ref = CornerReference(
        index=0, apex_spline=0.45, spline_lo=0.25, spline_hi=0.55, optimal_apex_kmh=90.0
    )
    lap = _flat_trace([(0.30, 0.33), (0.40, 0.42)])
    add_corpus_lap([ref], lap)
    assert len(ref.brake_marks) == 2
    assert ref.best_brake_point_spline == _approx_spline(ref.brake_marks[0])
    assert ref.brake_marks[0] == _approx_spline(0.30)
    assert ref.brake_marks[1] == _approx_spline(0.40)


def _approx_spline(x: float):
    import pytest

    return pytest.approx(x, abs=0.011)
