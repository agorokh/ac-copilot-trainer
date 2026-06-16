"""Lupa L0 regression for `delta.lua` predicates used by the #180/#188 reset guards.

`delta.isBackwardSplineJump(prevSpline, spline)` is the liberal skip guard for the live `delta`
producer; `delta.isBackwardSplineReset(prevSpline, spline)` is the conservative immediate reset
predicate for rolling state. The one-frame `rollingResetDecision` covers #188's ambiguous
wrap-shaped same-lap jump on CSP builds where `car.resetCounter` is unavailable.

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
    return _eval(f"return D.{fn}({prev}, {cur})")


def _eval(body: str):
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    p = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{p}/?.lua"')
    return rt.eval(f"(function() local D = require('delta') {body} end)()")


def _is_reset(prev: str, cur: str):
    return _call("isBackwardSplineReset", prev, cur)


def _is_jump(prev: str, cur: str):
    return _call("isBackwardSplineJump", prev, cur)


def _is_wrap_jump(prev: str, cur: str):
    return _call("isWrapShapedBackwardSplineJump", prev, cur)


def _decision(
    *,
    pending: str = "nil",
    last_lap: str = "5",
    lap: str = "5",
    prev: str = "0.40",
    cur: str = "0.45",
    teleported: str = "false",
):
    return _eval(
        "local r = D.rollingResetDecision({"
        f"pendingWrapLapCount = {pending}, "
        f"lastLapCount = {last_lap}, "
        f"lapCount = {lap}, "
        f"prevSpline = {prev}, "
        f"spline = {cur}, "
        f"teleported = {teleported}"
        "}) return { reset = r.reset, pending = r.pendingWrapLapCount }"
    )


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
    assert _is_wrap_jump("0.95", "0.05") is True


def test_wrap_shaped_helper_ignores_non_wrap_mid_lap_rewind():
    assert _is_wrap_jump("0.62", "0.05") is False


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


def test_rolling_reset_decision_defer_wrap_shaped_same_lap_jump():
    out = _decision(prev="0.95", cur="0.05", last_lap="5", lap="5")
    assert out["reset"] is False
    assert out["pending"] == 5


def test_rolling_reset_decision_clears_deferred_wrap_when_lap_count_catches_up():
    out = _decision(pending="5", prev="0.05", cur="0.08", last_lap="5", lap="6")
    assert out["reset"] is False
    assert out["pending"] is None


def test_rolling_reset_decision_resets_deferred_wrap_when_lap_count_stays_same():
    out = _decision(pending="5", prev="0.05", cur="0.08", last_lap="5", lap="5")
    assert out["reset"] is True
    assert out["pending"] is None


def test_rolling_reset_decision_keeps_deferred_wrap_when_lap_count_unavailable():
    out = _decision(pending="5", prev="0.05", cur="0.08", last_lap="5", lap="nil")
    assert out["reset"] is False
    assert out["pending"] == 5


def test_rolling_reset_decision_immediate_for_non_wrap_same_lap_rewind():
    out = _decision(prev="0.62", cur="0.05", last_lap="5", lap="5")
    assert out["reset"] is True
    assert out["pending"] is None


def test_rolling_reset_decision_immediate_for_reset_counter_and_lap_rollback():
    by_counter = _decision(teleported="true", prev="0.40", cur="0.41", last_lap="5", lap="5")
    by_rollback = _decision(prev="0.40", cur="0.41", last_lap="5", lap="4")
    assert by_counter["reset"] is True
    assert by_counter["pending"] is None
    assert by_rollback["reset"] is True
    assert by_rollback["pending"] is None
