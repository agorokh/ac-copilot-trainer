"""Corner-level improvement ranking: last lap vs reference (PB) features (issue #49).

Uses regret vs a faster reference lap (higher speeds = better). This is the default
path; a future SHAP-backed explainer can wrap the same feature vectors without
changing the WebSocket schema.
"""

from __future__ import annotations

from typing import Any

from tools.ai_sidecar.features import CORNER_SPEED_METRICS


def _suggestion(corner_id: int, metric: str, last: float, best: float) -> str:
    if metric == "min_speed_kmh":
        return (
            f"Corner {corner_id}: carry more minimum speed "
            f"(last {last:.1f} km/h vs reference {best:.1f} km/h)."
        )
    if metric == "apex_speed_kmh":
        return (
            f"Corner {corner_id}: raise apex speed "
            f"(last {last:.1f} km/h vs reference {best:.1f} km/h)."
        )
    return f"Corner {corner_id}: improve {metric} (last {last:.3f} vs reference {best:.3f})."


def rank_corner_improvements(
    last_corners: dict[int, dict[str, float]],
    ref_corners: dict[int, dict[str, float]],
    *,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Return ordered suggestions where *last* is slower than *ref* on speed metrics."""
    scored: list[tuple[float, int, str, float, float]] = []
    for cid, lmet in last_corners.items():
        rmet = ref_corners.get(cid)
        if not rmet:
            continue
        for metric in sorted(CORNER_SPEED_METRICS):
            lv = lmet.get(metric)
            bv = rmet.get(metric)
            if lv is None or bv is None:
                continue
            if lv >= bv:
                continue
            scale = max(abs(bv), 1e-6)
            regret = (bv - lv) / scale
            scored.append((regret, cid, metric, lv, bv))
    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[dict[str, Any]] = []
    for regret, cid, metric, lv, bv in scored[:max_items]:
        out.append(
            {
                "corner": cid,
                "metric": metric,
                "last": round(lv, 4),
                "reference": round(bv, 4),
                "priority": round(regret, 4),
                "suggestion": _suggestion(cid, metric, lv, bv),
            }
        )
    return out
