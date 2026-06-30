"""Sector, micro-sector, and SuperLap benchmarks for lap traces.

This module is intentionally pure-stdlib and works from :class:`LapTrace`, so
the sidecar can reuse it for imported laps, saved archives, Track Titan exports,
and live-lap follow-ups without coupling to any one source.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from tools.ai_sidecar.lap_dynamics import LapTrace


@dataclass(frozen=True)
class SegmentWindow:
    """Spline-bounded benchmark segment."""

    key: str
    label: str
    spline_start: float
    spline_end: float
    sector_index: int
    micro_index: int | None = None


@dataclass(frozen=True)
class SectorMap:
    """Deterministic sector map plus equal-width micro-sector subdivisions."""

    sectors: list[SegmentWindow]
    micro_sectors: list[SegmentWindow]


@dataclass(frozen=True)
class SegmentDelta:
    """Duration delta for one sector or micro-sector.

    ``delta_s`` is positive when the candidate lost time to the reference.
    """

    key: str
    label: str
    spline_start: float
    spline_end: float
    candidate_s: float
    reference_s: float
    delta_s: float
    sector_index: int
    micro_index: int | None = None


@dataclass(frozen=True)
class SectorDeltaReport:
    """All sector/micro-sector deltas for one candidate/reference pair."""

    total_delta_s: float
    sectors: list[SegmentDelta]
    micro_sectors: list[SegmentDelta]
    car_id: str | None = None
    track_id: str | None = None


@dataclass(frozen=True)
class SuperLapSegment:
    """Best observed micro-sector selected for a stitched SuperLap."""

    key: str
    label: str
    spline_start: float
    spline_end: float
    duration_s: float
    source_index: int
    source_lap_s: float | None
    car_id: str | None = None
    track_id: str | None = None


@dataclass(frozen=True)
class SuperLap:
    """Best-of-bests composite lap from the fastest observed micro-sectors."""

    lap_time_s: float
    baseline_best_lap_s: float | None
    gain_vs_best_s: float | None
    segments: list[SuperLapSegment]
    source_count: int


def build_sector_map(
    *, sector_count: int = 3, micro_per_sector: int = 3, sector_names: list[str] | None = None
) -> SectorMap:
    """Return equal spline sectors and micro-sectors.

    AC exposes live sector boundaries separately, but saved lap archives do not
    carry a per-track sector-definition file yet. Equal spline thirds make the
    benchmark deterministic now, and ``sector_names`` lets a future track map
    swap labels without changing the payload shape.
    """

    if sector_count <= 0:
        raise ValueError("sector_count must be positive")
    if micro_per_sector <= 0:
        raise ValueError("micro_per_sector must be positive")
    names = sector_names or [f"S{i + 1}" for i in range(sector_count)]
    if len(names) != sector_count:
        raise ValueError("sector_names length must match sector_count")

    sectors: list[SegmentWindow] = []
    micro_sectors: list[SegmentWindow] = []
    for si in range(sector_count):
        s0 = si / sector_count
        s1 = (si + 1) / sector_count
        label = names[si]
        sectors.append(
            SegmentWindow(
                key=label.lower(),
                label=label,
                spline_start=s0,
                spline_end=s1,
                sector_index=si,
            )
        )
        span = s1 - s0
        for mi in range(micro_per_sector):
            m0 = s0 + span * mi / micro_per_sector
            m1 = s0 + span * (mi + 1) / micro_per_sector
            mlabel = f"{label}.{mi + 1}"
            micro_sectors.append(
                SegmentWindow(
                    key=mlabel.lower(),
                    label=mlabel,
                    spline_start=m0,
                    spline_end=m1,
                    sector_index=si,
                    micro_index=mi,
                )
            )
    return SectorMap(sectors=sectors, micro_sectors=micro_sectors)


def segment_duration_s(lap: LapTrace, window: SegmentWindow) -> float | None:
    """Duration in seconds across ``window`` using spline/time interpolation."""

    t0 = _time_at_spline(lap, window.spline_start)
    t1 = _time_at_spline(lap, window.spline_end)
    if t0 is None or t1 is None:
        return None
    duration = t1 - t0
    if not math.isfinite(duration) or duration < -1e-6:
        return None
    return max(0.0, duration)


def build_sector_delta_report(
    candidate: LapTrace,
    reference: LapTrace,
    *,
    sector_map: SectorMap | None = None,
) -> SectorDeltaReport:
    """Compare candidate vs reference by sector and micro-sector.

    Positive deltas mean the candidate was slower than the reference over that
    segment; negative deltas mean the candidate gained time.
    """

    smap = sector_map or build_sector_map()
    sectors = _delta_windows(candidate, reference, smap.sectors)
    micro_sectors = _delta_windows(candidate, reference, smap.micro_sectors)
    total_delta_s = sum(s.delta_s for s in sectors)
    return SectorDeltaReport(
        total_delta_s=total_delta_s,
        sectors=sectors,
        micro_sectors=micro_sectors,
        car_id=candidate.car_id or reference.car_id,
        track_id=candidate.track_id or reference.track_id,
    )


def build_superlap(
    laps: Iterable[LapTrace],
    *,
    sector_map: SectorMap | None = None,
) -> SuperLap | None:
    """Stitch the fastest observed micro-sector from a corpus into a SuperLap."""

    valid_laps = [lap for lap in laps if len(lap) >= 2]
    if not valid_laps:
        return None

    smap = sector_map or build_sector_map()
    segments: list[SuperLapSegment] = []
    for window in smap.micro_sectors:
        best: tuple[float, int, LapTrace] | None = None
        for idx, lap in enumerate(valid_laps):
            duration = segment_duration_s(lap, window)
            if duration is None:
                continue
            if best is None or duration < best[0]:
                best = (duration, idx, lap)
        if best is None:
            continue
        duration, source_index, lap = best
        segments.append(
            SuperLapSegment(
                key=window.key,
                label=window.label,
                spline_start=window.spline_start,
                spline_end=window.spline_end,
                duration_s=duration,
                source_index=source_index,
                source_lap_s=_lap_duration_s(lap),
                car_id=lap.car_id,
                track_id=lap.track_id,
            )
        )

    if not segments:
        return None
    lap_time_s = sum(s.duration_s for s in segments)
    lap_durations = [d for lap in valid_laps if (d := _lap_duration_s(lap)) is not None]
    baseline = min(lap_durations) if lap_durations else None
    gain = (baseline - lap_time_s) if baseline is not None else None
    return SuperLap(
        lap_time_s=lap_time_s,
        baseline_best_lap_s=baseline,
        gain_vs_best_s=gain,
        segments=segments,
        source_count=len({s.source_index for s in segments}),
    )


def _delta_windows(
    candidate: LapTrace, reference: LapTrace, windows: list[SegmentWindow]
) -> list[SegmentDelta]:
    out: list[SegmentDelta] = []
    for window in windows:
        cand = segment_duration_s(candidate, window)
        ref = segment_duration_s(reference, window)
        if cand is None or ref is None:
            continue
        out.append(
            SegmentDelta(
                key=window.key,
                label=window.label,
                spline_start=window.spline_start,
                spline_end=window.spline_end,
                candidate_s=cand,
                reference_s=ref,
                delta_s=cand - ref,
                sector_index=window.sector_index,
                micro_index=window.micro_index,
            )
        )
    return out


def _time_at_spline(lap: LapTrace, spline_pos: float) -> float | None:
    points = sorted(
        (float(sp), float(t))
        for sp, t in zip(lap.spline, lap.t_s, strict=False)
        if math.isfinite(float(sp)) and math.isfinite(float(t))
    )
    if len(points) < 2:
        return None
    sp = min(1.0, max(0.0, float(spline_pos)))
    if sp <= points[0][0]:
        return points[0][1]
    if sp >= points[-1][0]:
        return points[-1][1]
    lo, hi = 0, len(points) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if points[mid][0] <= sp:
            lo = mid
        else:
            hi = mid
    a_sp, a_t = points[lo]
    b_sp, b_t = points[hi]
    span = b_sp - a_sp
    if span <= 1e-9:
        return a_t
    frac = (sp - a_sp) / span
    return a_t + frac * (b_t - a_t)


def _lap_duration_s(lap: LapTrace) -> float | None:
    if lap.lap_ms is not None and lap.lap_ms > 0:
        return lap.lap_ms / 1000.0
    if len(lap.t_s) >= 2:
        duration = lap.t_s[-1] - lap.t_s[0]
        if duration > 0 and math.isfinite(duration):
            return duration
    return None
