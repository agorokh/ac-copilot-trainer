"""Lupa L0 regression for `delta.lua` predicates used by the #180 `delta` WS producer.

`delta.isBackwardSplineReset(prevSpline, spline)` is the shared discontinuity test that BOTH the
live `delta` producer's skip guard (in `ac_copilot_trainer.lua` `script.update`) and the
end-of-update `resetRollingDrivingState` detection consume, so the pit/session-reset threshold
cannot drift between them (Cursor + codex on #185: a same-lap spline rewind would otherwise leak
one bogus delta against the prior stint's lap clock + reference trace before the reset fires).

A *lap wrap* (prev spline near 1.0, now near 0.0) is forward lap completion, NOT a reset, and must
return False. The backward threshold is strict (`d < -0.2`).
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


def _call(fn: str, prev: str, cur: str):
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    p = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{p}/?.lua"')
    return rt.eval(f"(function() local D = require('delta') return D.{fn}({prev}, {cur}) end)()")


def _is_reset(prev: str, cur: str):
    return _call("isBackwardSplineReset", prev, cur)


def _is_jump(prev: str, cur: str):
    return _call("isBackwardSplineJump", prev, cur)


def test_backward_spline_reset_detects_mid_lap_rewind():
    # Pit/session reset mid-lap: spline jumps 0.62 -> 0.05 (d = -0.57), prev not near 1.0 -> reset.
    assert _is_reset("0.62", "0.05") is True


def test_backward_spline_reset_ignores_lap_wrap():
    # Normal lap completion: prev 0.95 (>0.8), now 0.05 (<0.25) -> likelyWrap -> NOT a reset.
    assert _is_reset("0.95", "0.05") is False


def test_backward_spline_reset_ignores_forward_progress():
    assert _is_reset("0.40", "0.45") is False


def test_backward_spline_reset_ignores_small_backward_noise():
    # -0.05 is within the -0.2 tolerance (GPS/spline jitter), not a reset.
    assert _is_reset("0.50", "0.45") is False


def test_backward_spline_reset_nil_prev_is_false():
    # First frame after entry: no prior spline -> cannot be a reset.
    assert _is_reset("nil", "0.5") is False


def test_backward_spline_reset_threshold_is_strict():
    # Exactly -0.2 is NOT < -0.2; just past it is. Pins the threshold both consumers rely on.
    assert _is_reset("0.50", "0.30") is False  # d = -0.20
    assert _is_reset("0.50", "0.29") is True  # d = -0.21


# --- isBackwardSplineJump: LIBERAL variant for the harmless delta-skip (INCLUDES wrap-shaped) ----
def test_backward_spline_jump_includes_wrap_shaped():
    # Unlike isBackwardSplineReset, the jump variant does NOT exclude wrap-shaped rewinds — the
    # delta producer only calls it with lapCount unchanged, where a wrap-shaped jump is a teleport,
    # and skipping a delta frame on it is harmless even when resetCounter is unavailable (#185).
    assert _is_jump("0.95", "0.05") is True  # wrap-shaped -> reset excludes, jump includes
    assert _is_reset("0.95", "0.05") is False  # the conservative variant still excludes it


def test_backward_spline_jump_detects_mid_lap_rewind():
    assert _is_jump("0.62", "0.05") is True


def test_backward_spline_jump_ignores_forward_and_noise():
    assert _is_jump("0.40", "0.45") is False  # forward
    assert _is_jump("0.50", "0.45") is False  # -0.05 within tolerance


def test_backward_spline_jump_nil_prev_is_false():
    assert _is_jump("nil", "0.5") is False


def test_backward_spline_jump_threshold_is_strict():
    assert _is_jump("0.50", "0.30") is False  # d = -0.20
    assert _is_jump("0.50", "0.29") is True  # d = -0.21
