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

    result = {
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
    clocks = [chunk.get("callback_clock") for chunk in chunks]
    if any(clock is not None for clock in clocks):
        if any(clock != "os.preciseClock" for clock in clocks):
            raise ValueError("mixed callback clock provenance")
        callbacks = []
        last_offset = None
        for number, row in enumerate(rows):
            offset = row.get("clock_offset_s")
            if (
                isinstance(offset, bool)
                or not isinstance(offset, (int, float))
                or not math.isfinite(offset)
                or offset < 0
                or offset > elapsed
                or (last_offset is not None and offset <= last_offset)
            ):
                raise ValueError("invalid callback clock offset")
            interval = row.get("callback_ms")
            if number == 0:
                if interval is not None:
                    raise ValueError("first callback interval has no predecessor")
            else:
                expected = (offset - last_offset) * 1000
                if (
                    isinstance(interval, bool)
                    or not isinstance(interval, (int, float))
                    or not math.isfinite(interval)
                    or interval <= 0
                    or not math.isclose(interval, expected, rel_tol=1e-6, abs_tol=0.001)
                ):
                    raise ValueError("callback interval does not match producer clock")
                if row["paused"] is False and rows[number - 1]["paused"] is False:
                    callbacks.append(float(interval))
            last_offset = offset
        if not callbacks:
            raise ValueError("capture contains no complete active callback intervals")
        ordered_callbacks = sorted(callbacks)

        def callback_percentile(fraction):
            return ordered_callbacks[max(0, math.ceil(fraction * len(callbacks)) - 1)]

        result["callback_intervals"] = {
            "source": "csp_os_precise_clock",
            "units": "ms",
            "active_samples": len(callbacks),
            "excluded_boundary_or_pause_samples": len(rows) - len(callbacks),
            "mean_ms": sum(callbacks) / len(callbacks),
            "p50_ms": callback_percentile(0.5),
            "p95_ms": callback_percentile(0.95),
            "p99_ms": callback_percentile(0.99),
            "max_ms": max(callbacks),
            "over_33ms": sum(value > 33.333 for value in callbacks),
            "over_50ms": sum(value > 50 for value in callbacks),
            "limitation": "Intervals between CSP callbacks; not OS presentation timings",
        }
    return result
