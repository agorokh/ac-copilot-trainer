"""Per-corner track reference envelope: GGV optimal + human-corpus best. Pure stdlib.

The "track nuances" pillar. For each corner of a track it holds:
  * the **GGV optimal** apex speed — the theoretical min-time target from the friction-circle QSS
    profile (``ggv_profile.ggv_speed_profile_from_model``). A *ceiling*, not a guaranteed-achievable
    number (the live car is TC-off traction-limited below it — see the #244 frontier diagnostics).
  * the **corpus best** — the fastest apex speed + earliest sustainable brake point observed across
    a set of human/AI laps. The realistic, demonstrated target.

The coaching layer scores a driven corner against both ("apex 6 km/h under the best lap, 9 under the
GGV optimum; brake ~4 m later"). Built by composing already-verified pieces — the GGV profile and
``lap_dynamics`` corner segmentation — so nothing new is asserted about the physics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.ai_sidecar.lap_dynamics import LapTrace, segment_corners

#: peak pedal fraction a sustained application must reach to count as a distinct BRAKE ZONE.
#: ``segment_corners`` deliberately merges an esses complex into ONE driver-perceived corner, so a
#: merged window can hold several real brake zones (issue #522: Magione's back half — 4 of 9 zones
#: sat inside merged windows and got no mark). A lighter touch than this is a lift/drag on the way
#: to an apex, not a coachable brake mark.
_ZONE_MIN_PEAK_BRAKE = 0.35


@dataclass
class CornerReference:
    """The optimal + best-observed envelope for one corner, keyed by its spline window."""

    index: int
    apex_spline: float
    spline_lo: float
    spline_hi: float
    optimal_apex_kmh: float  # GGV QSS theoretical ceiling
    best_observed_apex_kmh: float | None = None  # fastest corpus lap through this window
    best_brake_point_spline: float | None = None  # earliest sustained brake of the best corpus lap
    n_corpus: int = 0
    #: onset splines of EVERY distinct sustained brake zone of the best corpus lap in this window
    #: (issue #522 coverage). ``best_brake_point_spline`` stays the first of these for consumers
    #: that only understand one mark per corner.
    brake_marks: list[float] = field(default_factory=list)

    @property
    def target_apex_kmh(self) -> float:
        """The realistic target: corpus best when known, else the GGV optimum."""
        return (
            self.best_observed_apex_kmh
            if self.best_observed_apex_kmh is not None
            else self.optimal_apex_kmh
        )


def _min_speed_kmh_in_window(lap: LapTrace, lo: float, hi: float) -> float | None:
    """Slowest speed (km/h) of ``lap`` within the spline window [lo, hi], or None if no samples."""
    vals = [lap.v_ms[i] for i in range(len(lap)) if lo <= lap.spline[i] <= hi]
    return min(vals) * 3.6 if vals else None


def sustained_brake_onsets(
    lap: LapTrace,
    lo: float,
    hi: float,
    *,
    thresh: float = 0.05,
    min_run: int = 3,
    min_peak: float = _ZONE_MIN_PEAK_BRAKE,
) -> list[float]:
    """Onset splines of every DISTINCT sustained brake zone within [lo, hi], in lap order.

    A zone is ``min_run`` consecutive in-window samples above ``thresh`` (so a single-frame blip is
    not a brake point — consistent with ``lap_dynamics`` treating a brake zone as near-continuous)
    whose peak pedal reaches ``min_peak`` (so a light lift/drag between apexes is not promoted to a
    coachable mark). Zones split where the pedal drops back to/below ``thresh``.
    """
    n = len(lap)
    out: list[float] = []
    i = 0
    while i < n:
        if not (lo <= lap.spline[i] <= hi and lap.brake[i] > thresh):
            i += 1
            continue
        peak = lap.brake[i]
        j = i + 1
        while j < n and lap.spline[j] <= hi and lap.brake[j] > thresh:
            peak = max(peak, lap.brake[j])
            j += 1
        if j - i >= min_run and peak >= min_peak:
            out.append(lap.spline[i])
        i = j
    return out


def build_references(optimal_lap: LapTrace) -> list[CornerReference]:
    """Build the GGV-optimal corner envelope from an optimal-line :class:`LapTrace`.

    ``optimal_lap`` is a LapTrace whose ``v_ms`` is the GGV QSS profile over the racing line (build
    it from ``ggv_speed_profile_from_model`` + the fast_lane geometry). Corner windows + apexes come
    from the verified ``lap_dynamics.segment_corners``; the optimal apex speed is the profile min
    in each window.
    """
    refs: list[CornerReference] = []
    for idx, (entry_i, apex_i, exit_i) in enumerate(segment_corners(optimal_lap)):
        refs.append(
            CornerReference(
                index=idx,
                apex_spline=optimal_lap.spline[apex_i],
                spline_lo=optimal_lap.spline[entry_i],
                spline_hi=optimal_lap.spline[exit_i],
                optimal_apex_kmh=round(optimal_lap.v_ms[apex_i] * 3.6, 1),
            )
        )
    return refs


def add_corpus_lap(references: list[CornerReference], lap: LapTrace) -> None:
    """Fold one corpus lap into the references in place: keep the FASTEST apex per corner window.

    A lap is only credited to a corner when it actually has samples in that window (a partial lap
    doesn't reset a faster prior best).
    """
    for ref in references:
        v = _min_speed_kmh_in_window(lap, ref.spline_lo, ref.spline_hi)
        if v is None:
            continue
        ref.n_corpus += 1
        if ref.best_observed_apex_kmh is None or v > ref.best_observed_apex_kmh:
            ref.best_observed_apex_kmh = round(v, 1)
            # EVERY distinct sustained brake zone of the best lap becomes a mark (issue #522:
            # a merged esses window holds several real zones and each needs a coachable cue).
            ref.brake_marks = sustained_brake_onsets(lap, ref.spline_lo, ref.spline_hi)
            ref.best_brake_point_spline = ref.brake_marks[0] if ref.brake_marks else None


@dataclass
class CornerScore:
    """How a driven corner compares to its reference envelope."""

    index: int
    apex_spline: float
    driven_apex_kmh: float
    target_apex_kmh: float
    optimal_apex_kmh: float
    deficit_to_target_kmh: float  # >0 = driver carried LESS than the realistic target
    deficit_to_optimal_kmh: float
    headline: str
    findings: list[str] = field(default_factory=list)


def score_lap(
    references: list[CornerReference], lap: LapTrace, *, notable_kmh: float = 2.0
) -> list[CornerScore]:
    """Score each reference corner against a driven lap: apex-speed deficit vs target + optimum."""
    scores: list[CornerScore] = []
    for ref in references:
        driven = _min_speed_kmh_in_window(lap, ref.spline_lo, ref.spline_hi)
        if driven is None:
            continue
        target = ref.target_apex_kmh
        d_target = round(target - driven, 1)
        d_opt = round(ref.optimal_apex_kmh - driven, 1)
        findings: list[str] = []
        if d_target >= notable_kmh:
            src = "best lap" if ref.best_observed_apex_kmh is not None else "GGV optimum"
            findings.append(
                f"apex {d_target:.0f} km/h under the {src} ({driven:.0f} vs {target:.0f}) — "
                "carry more entry speed (if grip is available)."
            )
        if ref.best_observed_apex_kmh is not None and d_opt - d_target >= notable_kmh:
            findings.append(
                f"even the best lap is {d_opt - d_target:.0f} km/h under the GGV ceiling here — a "
                "setup/grip ceiling, not just technique."
            )
        head = (
            f"C{ref.index} (apex {ref.apex_spline:.2f}): on target."
            if d_target < notable_kmh
            else f"C{ref.index} (apex {ref.apex_spline:.2f}): -{d_target:.0f} km/h vs target."
        )
        scores.append(
            CornerScore(
                index=ref.index,
                apex_spline=ref.apex_spline,
                driven_apex_kmh=round(driven, 1),
                target_apex_kmh=round(target, 1),
                optimal_apex_kmh=ref.optimal_apex_kmh,
                deficit_to_target_kmh=d_target,
                deficit_to_optimal_kmh=d_opt,
                headline=head,
                findings=findings,
            )
        )
    return scores
