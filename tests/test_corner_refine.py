"""Tests for the #582 L3 beyond-QSS per-corner refinement (corner_refine.py).

All synthetic and off-rig: kappa/seg arrays stand in for a track, a hand-built 30x10 km/h
uncertainty grid stands in for the #543 plant posterior. The load-bearing assertions mirror the
issue's acceptance criteria: boundary pinning, evidence gating with named reverts, the stability
barrier, strict improvement on a provably conservative corner, and byte-level determinism.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.ac_harness.auto_drive import generic_gt3_ggv
from tools.ac_harness.corner_refine import (
    DEFAULT_UNCERTAINTY_LCB_Z,
    Z_STABILITY_FLOOR,
    L3Params,
    barrier_ggv,
    refine_profile,
    relaxed_ggv,
    segment_corners,
    verify_refined_profile,
)
from tools.ac_harness.ggv_profile import forward_backward_profile

_N = 200
_CORNER = range(80, 121)  # one 41-point corner, radius 60 m
_KAPPA_CORNER = 1.0 / 60.0
_SEG_M = 5.0


def _channel(mean: float, std: float, *, source: str = "prior", n: int = 0) -> dict:
    safe = max(0.1, mean - 1.96 * std)
    return {
        "mean_g": round(mean, 6),
        "epistemic_std_g": round(std, 6),
        "safe_g": round(min(mean, safe), 6),
        "n": n,
        "source": source,
    }


def _grid(measured_lateral_kmh: tuple[float, float] = (0.0, 0.0), lateral_std: float = 0.1):
    """The full 30x10 km/h uncertainty grid; lateral bins inside the range are ``measured``."""
    lo_m, hi_m = measured_lateral_kmh
    bins = []
    for i in range(30):
        lo = i * 10.0
        hi = lo + 10.0
        lateral_measured = lo >= lo_m and hi <= hi_m
        bins.append(
            {
                "speed_min_kmh": lo,
                "speed_max_kmh": hi,
                "lateral": _channel(
                    1.4,
                    lateral_std if lateral_measured else 0.2,
                    source="measured" if lateral_measured else "prior",
                    n=60 if lateral_measured else 0,
                ),
                "brake": _channel(1.2, 0.15),
                "drive": _channel(0.5, 0.1),
            }
        )
    return tuple(bins)


def _plant(measured_lateral_kmh=(40.0, 200.0), lateral_std: float = 0.1):
    return replace(generic_gt3_ggv(), uncertainty_bins=_grid(measured_lateral_kmh, lateral_std))


def _track():
    """One corner bracketed by straights: (seg, kappa) arrays for a cyclic 200-point line."""
    kappa = [_KAPPA_CORNER if i in _CORNER else 0.0 for i in range(_N)]
    seg = [_SEG_M] * _N
    return seg, kappa


def _qss(plant, v_top_ms: float = 61.0):
    seg, kappa = _track()
    v, _ax = forward_backward_profile(kappa, seg, plant, v_top_ms=v_top_ms)
    return seg, kappa, v


# ---------------------------------------------------------------------------
# L3Params validation
# ---------------------------------------------------------------------------
def test_params_defaults_valid_and_roundtrip():
    params = L3Params()
    assert params.z_ladder[-1] == Z_STABILITY_FLOOR
    rebuilt = L3Params.from_dict(params.to_dict())
    assert rebuilt == params


@pytest.mark.parametrize(
    "kwargs",
    [
        {"z_ladder": ()},
        {"z_ladder": (0.5,)},  # below the stability floor
        {"z_ladder": (2.5,)},  # above the safe LCB z: a derate, not a refinement
        {"z_ladder": (float("nan"),)},
        {"kappa_threshold": 0.0},
        {"kappa_threshold": float("inf")},
        {"pad_points": -1},
        {"min_corner_points": 2},
        {"max_rel_std": 0.0},
        {"max_rel_std": 0.9},  # above MAX_REL_STD_CEILING
    ],
)
def test_params_rejects_unsafe_values(kwargs):
    with pytest.raises(ValueError):
        L3Params(**kwargs)


def test_params_from_dict_rejects_tampered_payloads():
    good = L3Params().to_dict()
    with pytest.raises(ValueError):
        L3Params.from_dict(None)
    with pytest.raises(ValueError):
        L3Params.from_dict({**good, "schema_version": 99})
    with pytest.raises(ValueError):
        L3Params.from_dict({**good, "z_ladder": [0.2]})  # laxer than the floor
    with pytest.raises(ValueError):
        L3Params.from_dict({**good, "max_rel_std": 5.0})
    without_key = {k: v for k, v in good.items() if k != "kappa_threshold"}
    with pytest.raises(ValueError):
        L3Params.from_dict(without_key)


# ---------------------------------------------------------------------------
# Relaxed / barrier grip construction
# ---------------------------------------------------------------------------
def test_relaxed_ggv_lifts_only_measured_low_variance_bins():
    plant = _plant(measured_lateral_kmh=(80.0, 120.0))
    relaxed = relaxed_ggv(plant, Z_STABILITY_FLOOR, 0.25)
    for orig, new in zip(plant.uncertainty_bins, relaxed.uncertainty_bins, strict=True):
        for kind in ("lateral", "brake", "drive"):
            o, r = orig[kind], new[kind]
            if o["source"] == "measured":
                expected = o["mean_g"] - Z_STABILITY_FLOOR * o["epistemic_std_g"]
                assert r["safe_g"] == pytest.approx(expected, abs=1e-6)
                assert r["safe_g"] > o["safe_g"]  # actually relaxed from the 1.96-z LCB
                assert r["safe_g"] <= o["mean_g"]  # never above the posterior mean
            else:
                assert r == o  # prior bins never relax


def test_relaxed_ggv_skips_high_variance_measured_bins():
    plant = _plant(measured_lateral_kmh=(80.0, 120.0), lateral_std=0.6)  # rel std 0.43 > 0.25
    relaxed = relaxed_ggv(plant, Z_STABILITY_FLOOR, 0.25)
    assert relaxed.uncertainty_bins == plant.uncertainty_bins


def test_relaxed_ggv_rejects_out_of_range_z():
    plant = _plant()
    for z in (0.5, 2.5, float("nan")):
        with pytest.raises(ValueError, match="relaxation z"):
            relaxed_ggv(plant, z, 0.25)


def test_relaxed_ggv_legacy_plant_passthrough():
    plant = generic_gt3_ggv()
    assert relaxed_ggv(plant, Z_STABILITY_FLOOR, 0.25) is plant


def test_barrier_dominates_every_relaxation_step():
    plant = _plant()
    barrier = barrier_ggv(plant, 0.25)
    for z in (1.5, 1.2, Z_STABILITY_FLOOR):
        relaxed = relaxed_ggv(plant, z, 0.25)
        for v in (20.0, 30.0, 45.0):
            assert relaxed.ay_max(v) <= barrier.ay_max(v) + 1e-9
    assert Z_STABILITY_FLOOR < DEFAULT_UNCERTAINTY_LCB_Z


# ---------------------------------------------------------------------------
# Corner segmentation
# ---------------------------------------------------------------------------
def test_segment_one_bracketed_corner_with_padding():
    _seg, kappa = _track()
    windows = segment_corners(kappa, kappa_threshold=0.005, pad_points=3, min_corner_points=5)
    assert len(windows) == 1
    idxs = windows[0]
    assert idxs[0] == _CORNER.start - 3 and idxs[-1] == _CORNER.stop - 1 + 3
    assert idxs == list(range(idxs[0], idxs[-1] + 1))


def test_segment_corner_wrapping_index_zero():
    kappa = [0.0] * _N
    for i in list(range(_N - 10, _N)) + list(range(10)):
        kappa[i] = _KAPPA_CORNER
    windows = segment_corners(kappa, kappa_threshold=0.005, pad_points=2, min_corner_points=5)
    assert len(windows) == 1
    idxs = windows[0]
    assert len(idxs) == 20 + 4
    assert idxs[0] == _N - 12
    # Consecutive modulo N (the window crosses index 0 without splitting).
    for a, b in zip(idxs, idxs[1:], strict=False):
        assert b == (a + 1) % _N


def test_segment_merges_adjacent_runs_into_one_window():
    kappa = [0.0] * _N
    for i in range(80, 95):
        kappa[i] = _KAPPA_CORNER
    for i in range(99, 114):  # 4-point gap < 2*pad
        kappa[i] = -_KAPPA_CORNER  # opposite direction: an S-chicane is one window
    windows = segment_corners(kappa, kappa_threshold=0.005, pad_points=3, min_corner_points=5)
    assert len(windows) == 1
    assert windows[0][0] == 77 and windows[0][-1] == 116


def test_segment_no_corner_and_all_corner_return_empty():
    straight = [0.0] * _N
    circle = [_KAPPA_CORNER] * _N
    assert segment_corners(straight, kappa_threshold=0.005, pad_points=3, min_corner_points=5) == []
    assert segment_corners(circle, kappa_threshold=0.005, pad_points=3, min_corner_points=5) == []


def test_segment_drops_windows_below_min_points():
    kappa = [0.0] * _N
    kappa[50] = _KAPPA_CORNER  # 1 corner point + 0 pad = below min
    assert segment_corners(kappa, kappa_threshold=0.005, pad_points=0, min_corner_points=5) == []


# ---------------------------------------------------------------------------
# refine_profile: the acceptance-criteria core
# ---------------------------------------------------------------------------
def test_refine_improves_conservative_corner_within_barrier():
    plant = _plant()
    seg, kappa, v_qss = _qss(plant)
    params = L3Params()
    v_ref, report = refine_profile(seg, kappa, v_qss, plant, params, v_top_ms=61.0)

    assert report["refined_corners"] == 1 and report["reverted_corners"] == 0
    corner = report["corners"][0]
    assert corner["status"] == "refined"
    assert corner["gain_ms"] > 0 and report["predicted_gain_ms"] == corner["gain_ms"]

    # Boundary pinning: entry/exit speeds equal the QSS values exactly.
    start, end = corner["start"], corner["end"]
    assert v_ref[start] == v_qss[start] and v_ref[end] == v_qss[end]
    # Interior strictly faster at the apex; nowhere slower than QSS; outside untouched.
    apex = min(range(_N), key=lambda i: v_qss[i])
    assert v_ref[apex] > v_qss[apex]
    assert all(v_ref[i] >= v_qss[i] - 1e-9 for i in range(_N))
    window = set(range(start, end + 1))
    assert all(v_ref[i] == v_qss[i] for i in range(_N) if i not in window)

    # The refinement genuinely used evidence headroom (beyond the safe LCB envelope) while
    # respecting the stability barrier (mean - 1.0*std).
    safe_limit = plant.ay_max(v_ref[apex])
    barrier_limit = barrier_ggv(plant, params.max_rel_std).ay_max(v_ref[apex])
    ay_apex = v_ref[apex] * v_ref[apex] * abs(kappa[apex])
    assert ay_apex > safe_limit  # beyond QSS-safe...
    assert ay_apex <= barrier_limit + 1e-6  # ...but never beyond the barrier
    assert verify_refined_profile(
        [(0.0, 0.0)] * _N, kappa, v_ref, plant, params
    ) is None


def test_refine_is_deterministic():
    plant = _plant()
    seg, kappa, v_qss = _qss(plant)
    out1 = refine_profile(seg, kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    out2 = refine_profile(seg, kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    assert out1 == out2


def test_refine_reverts_unmeasured_corner_with_named_reason():
    # Measured lateral evidence exists only far above the corner's speed range.
    plant = _plant(measured_lateral_kmh=(200.0, 250.0))
    seg, kappa, v_qss = _qss(plant)
    v_ref, report = refine_profile(seg, kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    assert v_ref == v_qss
    assert report["refined_corners"] == 0 and report["reverted_corners"] == 1
    corner = report["corners"][0]
    assert corner["status"] == "reverted"
    assert "no measured low-variance lateral bin" in corner["reason"]


def test_refine_reverts_all_for_legacy_point_model():
    plant = generic_gt3_ggv()
    seg, kappa, v_qss = _qss(plant)
    v_ref, report = refine_profile(seg, kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    assert v_ref == v_qss
    assert "not uncertainty-aware" in report["reverted_all"]
    assert report["corners"] == []


def test_refine_reverts_all_when_no_bracketed_corner():
    plant = _plant()
    kappa = [_KAPPA_CORNER] * _N  # a circle: every point is corner, no boundary to pin
    seg = [_SEG_M] * _N
    v, _ax = forward_backward_profile(kappa, seg, plant, v_top_ms=61.0)
    v_ref, report = refine_profile(seg, kappa, v, plant, L3Params(), v_top_ms=61.0)
    assert v_ref == v
    assert "no refinable corner window" in report["reverted_all"]


def test_refine_validates_inputs():
    plant = _plant()
    seg, kappa, v_qss = _qss(plant)
    with pytest.raises(ValueError, match="length mismatch"):
        refine_profile(seg[:-1], kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    with pytest.raises(ValueError, match="non-finite curvature"):
        refine_profile(seg, [float("nan")] + kappa[1:], v_qss, plant, L3Params(), v_top_ms=61.0)
    with pytest.raises(ValueError, match="QSS speed"):
        refine_profile(seg, kappa, [0.0] + v_qss[1:], plant, L3Params(), v_top_ms=61.0)
    with pytest.raises(ValueError, match="segment length"):
        refine_profile([-1.0] + seg[1:], kappa, v_qss, plant, L3Params(), v_top_ms=61.0)
    with pytest.raises(ValueError, match="v_top_ms"):
        refine_profile(seg, kappa, v_qss, plant, L3Params(), v_top_ms=0.0)


def test_verify_refined_profile_catches_tampered_speeds():
    plant = _plant()
    seg, kappa, v_qss = _qss(plant)
    params = L3Params()
    v_ref, _report = refine_profile(seg, kappa, v_qss, plant, params, v_top_ms=61.0)
    plane = [(0.0, 0.0)] * _N
    assert verify_refined_profile(plane, kappa, v_ref, plant, params) is None
    hot = [v * 1.5 for v in v_ref]
    reason = verify_refined_profile(plane, kappa, hot, plant, params)
    assert reason is not None and "stability barrier" in reason
    short = verify_refined_profile(plane, kappa, v_ref[:-1], plant, params)
    assert short is not None and "length mismatch" in short
