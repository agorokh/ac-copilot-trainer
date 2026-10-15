"""Validate recorded performance.frames chunks; no live rig control or ETW claims.

Use the existing authenticated harness WS action capturePerformance and subscribe
to performance.frames. Supply its state.snapshot payloads to summarize_capture.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def summarize_capture(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fail on incomplete/lost/reset captures; exclude paused UI frames explicitly."""
    if not chunks or len(chunks) > 160:
        raise ValueError("one bounded completed capture is required")
    identity = chunks[0].get("capture_id")
    rows: list[dict[str, Any]] = []
    for number, chunk in enumerate(chunks, 1):
        if chunk.get("capture_id") != identity or chunk.get("chunk") != number:
            raise ValueError("mixed capture identity or missing/reordered chunks")
        if chunk.get("source") != "csp_ui_dt" or chunk.get("units") != "ms":
            raise ValueError("unsupported timing provenance")
        batch = chunk.get("rows")
        if not isinstance(batch, list) or len(batch) > 128:
            raise ValueError("invalid bounded sample chunk")
        rows.extend(batch)
    final = chunks[-1]
    if final.get("complete") is not True or final.get("reason") not in ("duration", "sample_limit"):
        raise ValueError("capture incomplete or reset")
    if final.get("gaps") != 0 or final.get("invalid_dt") != 0:
        raise ValueError(
            "missing render frames or invalid intervals prevent full distribution proof"
        )
    if not rows or len(rows) != final.get("sample_count") or len(rows) > 20000:
        raise ValueError("sample count mismatch")
    elapsed = final.get("elapsed_s")
    if (
        not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or not 0 < elapsed <= 130
    ):
        raise ValueError("invalid measured duration")
    intervals = []
    previous = None
    for row in rows:
        frame, interval = row.get("frame"), row.get("dt_ms")
        if (
            not isinstance(frame, int)
            or isinstance(frame, bool)
            or (previous is not None and frame != previous + 1)
        ):
            raise ValueError("nonconsecutive frame identities")
        previous = frame
        if (
            not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or not 0 < interval <= 10000
        ):
            raise ValueError("invalid frame interval")
        if row.get("paused") is False:
            intervals.append(float(interval))
        elif row.get("paused") is not True:
            raise ValueError("pause provenance missing")
    if not intervals:
        raise ValueError("capture contains no active render frames")
    ordered = sorted(intervals)

    def percentile(fraction: float) -> float:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "capture_id": identity,
        "source": "csp_ui_dt",
        "units": "ms",
        "elapsed_s": elapsed,
        "sample_count": len(rows),
        "active_samples": len(intervals),
        "paused_samples": len(rows) - len(intervals),
        "duplicates_ignored": final.get("duplicates"),
        "mean_ms": sum(intervals) / len(intervals),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": max(intervals),
        "over_33ms": sum(value > 33.333 for value in intervals),
        "over_50ms": sum(value > 50 for value in intervals),
        "limitation": "CSP UI/render intervals; not OS displayed/presentation frame timings",
    }
