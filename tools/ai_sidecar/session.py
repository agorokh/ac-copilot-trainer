"""Per-connection lap comparison state for optional ``improvementRanking`` (issue #49)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.ai_sidecar.features import extract_corner_table
from tools.ai_sidecar.improvement_ranking import rank_corner_improvements


def _positive_lap_time_ms(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if v > 0 else None


class LapComparisonState:
    """Tracks fastest ``lapTimeMs`` seen and the fastest lap that included corner telemetry.

    Overall PB can be updated on laps without ``telemetry.corners``; ranking compares
    against the best corner table seen (fastest lap among those that had corners).
    """

    __slots__ = ("_best_corners", "_best_corners_time_ms", "_best_time_ms")

    def __init__(self) -> None:
        self._best_corners: dict[int, dict[str, float]] | None = None
        self._best_corners_time_ms: int | None = None
        self._best_time_ms: int | None = None

    def improvement_ranking_for(self, inbound: Mapping[str, Any]) -> list[dict[str, Any]]:
        lap_time = _positive_lap_time_ms(inbound.get("lapTimeMs"))
        if lap_time is not None and (self._best_time_ms is None or lap_time < self._best_time_ms):
            self._best_time_ms = lap_time

        corners = extract_corner_table(inbound)
        if not corners:
            return []

        if lap_time is not None and (
            self._best_corners_time_ms is None or lap_time < self._best_corners_time_ms
        ):
            self._best_corners = corners
            self._best_corners_time_ms = lap_time
            return []

        if self._best_corners is not None:
            return rank_corner_improvements(corners, self._best_corners)
        return []
