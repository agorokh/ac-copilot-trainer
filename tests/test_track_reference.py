"""Tests for the per-corner track reference envelope (tools.ai_sidecar.track_reference)."""

from __future__ import annotations

import math

from tools.ai_sidecar.lap_dynamics import LapTrace
from tools.ai_sidecar.track_reference import (
    add_corpus_lap,
    build_references,
    score_lap,
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
