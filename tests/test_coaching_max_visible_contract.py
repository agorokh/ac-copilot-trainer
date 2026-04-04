"""Contract tests for issue #43 coaching hint cap (Lua has no runner in CI)."""

from __future__ import annotations

import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY = REPO_ROOT / "src/ac_copilot_trainer/modules/coaching_overlay.lua"
MAIN = REPO_ROOT / "src/ac_copilot_trainer/ac_copilot_trainer.lua"


def _norm_coaching_max_visible(raw: object) -> int:
    """Mirror of `M.normalizedCoachingMaxVisibleHints` in coaching_overlay.lua."""
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return 3
    if math.isnan(n):
        return 3
    n = int(math.floor(n + 0.5))  # match Lua math.floor(n + 0.5), not Python banker's round
    if n < 1:
        return 1
    if n > 3:
        return 3
    return n


def test_normalization_bounds_match_lua_contract() -> None:
    assert _norm_coaching_max_visible(None) == 3
    assert _norm_coaching_max_visible(float("nan")) == 3
    assert _norm_coaching_max_visible("bogus") == 3
    assert _norm_coaching_max_visible(0) == 1
    assert _norm_coaching_max_visible(-5) == 1
    assert _norm_coaching_max_visible(2.4) == 2
    assert _norm_coaching_max_visible(2.5) == 3
    assert _norm_coaching_max_visible(4) == 3
    assert _norm_coaching_max_visible(3) == 3


def test_lua_single_normalizer_and_wiring() -> None:
    overlay = OVERLAY.read_text(encoding="utf-8")
    assert "function M.normalizedCoachingMaxVisibleHints" in overlay
    assert "math.min(cap, #coachingLines)" in overlay
    main = MAIN.read_text(encoding="utf-8")
    assert (
        "coachingOverlay.normalizedCoachingMaxVisibleHints(config.coachingMaxVisibleHints)" in main
    )
