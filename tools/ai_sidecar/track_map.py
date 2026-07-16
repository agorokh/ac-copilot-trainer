"""Track-map payload for the tablet MAP page (#531 Part F).

Built once from the loaded reference archive — the same artifact that arms the realtime
observer — because its trace carries real world coordinates (``px``/``pz``, in the archive
since the Tier-B channel work) ordered by spline. No track-install parsing, no invented
geometry: **no reference archive → no map** (the page renders its explicit unknown).

Payload shape (the ``track.map`` topic):

``{track_id?, car_id?, source: "reference_archive", lap_ms?,
   outline: [[x, z], ...],       # downsampled to <= MAX_OUTLINE_POINTS, spline-ordered
   spline:  [s, ...],            # per outline point — the client maps live spline -> dot
   corners: [{label, spline, entry_spline, min_speed_kmh, gear?}, ...]}``

Corners come from :func:`tools.ai_sidecar.lap_dynamics.segment_corners` — the SAME
segmentation the coach's spoken turn numbers use, so the map's T-labels can never drift
from the voice (the cue/track-misalignment pitfall).
"""

from __future__ import annotations

import math
from typing import Any

from tools.ai_sidecar.lap_dynamics import LapTrace, lap_trace_from_archive, segment_corners

#: Outline resolution cap — ~2 m spacing on a 5 km lap, well under the A133's SVG budget.
MAX_OUTLINE_POINTS = 256
#: A real circuit spans hundreds of metres; anything under this is a zero-filled/degenerate
#: position column, not geometry (Codex on PR #618).
MIN_OUTLINE_SPAN_M = 50.0


def _round_gear(value: float) -> int | None:
    try:
        g = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return g if g >= 1 else None


def build_track_map(archive: dict[str, Any]) -> dict[str, Any] | None:
    """The ``track.map`` payload for ``archive``, or ``None`` when it cannot be built honestly.

    Never raises: a malformed archive (no trace, no position channels, too few samples)
    returns ``None`` — the caller logs and the MAP page keeps its explicit unknown.
    """
    try:
        lap = lap_trace_from_archive(archive)
    except (ValueError, TypeError):
        return None
    # Non-finite coordinates would serialize as bare `NaN` tokens that the tablet's
    # JSON.parse rejects, dropping the only replayed map frame (Codex on PR #618 R6) —
    # keep only fully finite samples, then re-check viability.
    finite_idx = [
        i
        for i in range(len(lap.spline))
        if math.isfinite(lap.x[i]) and math.isfinite(lap.z[i]) and math.isfinite(lap.spline[i])
    ]
    n = len(finite_idx)
    if n < 8:
        return None
    xs = [lap.x[i] for i in finite_idx]
    zs = [lap.z[i] for i in finite_idx]
    # Degenerate-geometry gate (Codex on PR #618): a trace whose px/pz columns were present
    # but unreadable defaults to 0.0 rows — the "outline" would be a collapsed point that
    # HIDES the honest no-reference state. Require a real spatial span on both axes' union.
    span_x = max(xs) - min(xs)
    span_z = max(zs) - min(zs)
    if max(span_x, span_z) < MIN_OUTLINE_SPAN_M:
        return None

    step = max(1, -(-n // MAX_OUTLINE_POINTS))  # ceil-div: the cap is a cap, not a target
    idx = [finite_idx[i] for i in range(0, n, step)]
    if idx[-1] != finite_idx[-1]:
        # Always keep the final sample: dropping up to step-1 points at S/F would make the
        # client's closing segment a false chord tens of metres off (daemon on PR #618).
        idx.append(finite_idx[-1])
    outline = [[round(lap.x[i], 1), round(lap.z[i], 1)] for i in idx]
    spline = [round(lap.spline[i], 4) for i in idx]

    corners: list[dict[str, Any]] = []
    for turn, (entry_i, apex_i, _exit_i) in enumerate(segment_corners(lap), start=1):
        corner: dict[str, Any] = {
            "label": f"T{turn}",
            "spline": round(lap.spline[apex_i], 4),
            "entry_spline": round(lap.spline[entry_i], 4),
            "min_speed_kmh": round(lap.v_ms[apex_i] * 3.6),
        }
        gear = _round_gear(lap.gear[apex_i])
        if gear is not None:
            corner["gear"] = gear
        corners.append(corner)

    payload: dict[str, Any] = {
        "source": "reference_archive",
        "outline": outline,
        "spline": spline,
        "corners": corners,
    }
    if lap.track_id:
        payload["track_id"] = lap.track_id
    if lap.car_id:
        payload["car_id"] = lap.car_id
    if lap.lap_ms is not None and lap.lap_ms > 0:
        payload["lap_ms"] = lap.lap_ms
    return payload


__all__ = ["MAX_OUTLINE_POINTS", "build_track_map", "LapTrace"]
