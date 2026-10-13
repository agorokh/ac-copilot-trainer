"""Measured completion checks shared by archive qualification and MAP.

These helpers inspect supplied samples; they never synthesize coverage or repair
raw archives. The finish-tail rule is the existing MAP native wrap convention.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def finish_wrap_cut(spline: Sequence[float], elapsed: Sequence[float]) -> int | None:
    """Return the measured prefix length, or None for an unsupported backwards jump."""
    if not spline or len(spline) != len(elapsed):
        return None
    decreases = [i for i in range(1, len(spline)) if spline[i] < spline[i - 1]]
    if not decreases:
        return len(spline)
    if len(decreases) != 1:
        return None
    cut = decreases[0]
    if spline[0] > 0.01 or spline[cut - 1] < 0.99:
        return None
    if any(not 0 <= s <= 0.01 for s in spline[cut:]):
        return None
    if any(a >= b for a, b in zip(elapsed, elapsed[1:], strict=False)):
        return None
    return cut


def completed_trace_reason(
    spline: Sequence[float],
    elapsed_ms: Sequence[float],
    speed: Sequence[float],
    lap_ms: float | None,
) -> str | None:
    """Validate an already trimmed measured trace with MAP's completion tolerances."""
    if len(spline) < 2 or len(spline) != len(elapsed_ms) or len(spline) != len(speed):
        return "insufficient_trace_samples"
    if not lap_ms or not math.isfinite(lap_ms) or lap_ms <= 0:
        return "invalid_lap_duration"
    if any(not math.isfinite(v) for values in (spline, elapsed_ms, speed) for v in values):
        return "nonfinite_or_missing_trace_value"
    if any(not 0 <= s <= 1 for s in spline) or any(v < 0 for v in speed):
        return "trace_value_out_of_range"
    if any(a >= b for a, b in zip(spline, spline[1:], strict=False)) or any(
        a >= b for a, b in zip(elapsed_ms, elapsed_ms[1:], strict=False)
    ):
        return "nonmonotonic_trace"
    if spline[0] > 0.01 or spline[-1] < 0.99:
        return "incomplete_lap_coverage"
    if abs(elapsed_ms[-1] - elapsed_ms[0] - lap_ms) > max(500, lap_ms * 0.01):
        return "elapsed_lap_duration_mismatch"
    return None
