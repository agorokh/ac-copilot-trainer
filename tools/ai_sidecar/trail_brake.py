"""Trail-braking technique analyzer: quantify + classify how a driver brakes INTO each corner.

The "methodics of trail braking" pillar. A pro bleeds the brake off progressively as steering loads
up — keeping the front tyres loaded through entry so the car rotates — rather than braking in a
straight line and coasting to the apex (lost entry speed) or trailing too deep (over-slowed / lock
risk). This reads the trace's ``brake``/``steer``/``speed``/``spline`` over each corner's
braking-into-entry phase (from :mod:`lap_dynamics` segmentation) and scores three signals:

* **trail overlap** — fraction of the braking samples where steering is also meaningfully applied
  (straight-line braking vs trailing into the corner);
* **brake-off point vs apex** — where the brake decays to ~0 relative to the apex, as a fraction of
  the corner window (released well before apex = coasting; at/just-before = textbook; after = deep);
* **release smoothness** — the largest single-sample brake drop while coming off the pedal (an
  abrupt release unsettles the platform).

Honest scope: this is *inferred* from the brake+steer overlap and the decel profile — the archive
has no direct load-transfer or per-wheel-lock measurement, so the classification is a technique
read, not a proof of what the tyres did. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.ai_sidecar.lap_dynamics import LapTrace, lap_trace_from_archive, segment_corners

#: pedal/steer fractions above which we consider the input "applied"
BRAKE_ON = 0.05
STEER_ON = 0.08
#: trail-overlap fraction: at/above this, the driver is genuinely trailing the brake into the corner
TRAIL_OVERLAP_MIN = 0.30
#: brake-off point as a fraction of the corner window, relative to the apex (0 = at apex)
BRAKE_OFF_EARLY = -0.15  # released this far (corner-fraction) before apex → coasting
BRAKE_OFF_DEEP = 0.10  # released this far after apex → trailing too deep
#: largest single-sample brake drop (0..1) that counts as an abrupt, platform-unsettling release
ABRUPT_RELEASE_DROP = 0.40

_COACHING = {
    "good_trail_brake": "Textbook: brake trailed progressively into the apex, front loaded.",
    "brakes_early_then_coasts": "Braking finishes well before the apex, then you coast — you're "
    "giving up entry speed. Brake a touch later and trail the last of it toward the apex.",
    "trails_too_deep": "Brake is still on past the apex — over-slowing the entry (and risking a "
    "front lock). Get the heavy braking done earlier and release by the apex.",
    "abrupt_release": "The brake comes off in one step, which unsettles the front just as you turn "
    "in. Bleed it off smoothly so the front stays loaded into the corner.",
    "straight_braking": "Braking is done in a straight line with little steering overlap — fine "
    "for a hard stop, but trailing some brake in would help the car rotate on entry.",
    "no_braking": "No meaningful braking into this corner (flat or lift-only).",
}


@dataclass(frozen=True)
class TrailBrakeFinding:
    """How the driver braked into one corner."""

    corner: int
    apex_spline: float
    classification: str
    trail_overlap: float  # 0..1 fraction of braking samples with steering also applied
    brake_off_rel: float | None  # (brake_off - apex) / corner_window; <0 = before apex; None = none
    release_abruptness: float  # largest single-sample brake drop coming off the pedal (0..1)
    coaching: str


def _corner_window(lap: LapTrace, entry_i: int, exit_i: int) -> float:
    """Spline span of the corner; guarded against a degenerate (<=0) window."""
    w = lap.spline[exit_i] - lap.spline[entry_i]
    return w if w > 1e-6 else 1e-6


def _analyze_corner(
    lap: LapTrace,
    entry_i: int,
    apex_i: int,
    exit_i: int,
    *,
    brake_on: float,
    steer_on: float,
) -> TrailBrakeFinding:
    apex_spline = lap.spline[apex_i]
    # braking-into-entry phase: from corner entry through the apex
    braking = [k for k in range(entry_i, apex_i + 1) if lap.brake[k] > brake_on]
    if not braking:
        return TrailBrakeFinding(
            corner=-1,
            apex_spline=apex_spline,
            classification="no_braking",
            trail_overlap=0.0,
            brake_off_rel=None,
            release_abruptness=0.0,
            coaching=_COACHING["no_braking"],
        )
    overlap = sum(1 for k in braking if abs(lap.steer[k]) > steer_on) / len(braking)

    # brake-off point: last in-corner sample (entry..exit) still on the brakes
    on_brakes = [k for k in range(entry_i, exit_i + 1) if lap.brake[k] > brake_on]
    brake_off_i = max(on_brakes)
    brake_off_rel = (lap.spline[brake_off_i] - apex_spline) / _corner_window(lap, entry_i, exit_i)

    # release smoothness: largest single-sample brake DROP from the peak through the off-step (the
    # transition where the pedal is released — including the step that crosses below threshold, so a
    # high-then-suddenly-zero release is caught, not just the on-pedal taper).
    peak_i = max(range(entry_i, brake_off_i + 1), key=lambda k: lap.brake[k])
    abruptness = 0.0
    for k in range(peak_i, min(brake_off_i + 1, len(lap) - 1)):
        abruptness = max(abruptness, lap.brake[k] - lap.brake[k + 1])

    if overlap < TRAIL_OVERLAP_MIN:
        cls = "brakes_early_then_coasts" if brake_off_rel < BRAKE_OFF_EARLY else "straight_braking"
    elif abruptness >= ABRUPT_RELEASE_DROP:
        cls = "abrupt_release"
    elif brake_off_rel > BRAKE_OFF_DEEP:
        cls = "trails_too_deep"
    else:
        cls = "good_trail_brake"

    return TrailBrakeFinding(
        corner=-1,
        apex_spline=apex_spline,
        classification=cls,
        trail_overlap=round(overlap, 3),
        brake_off_rel=round(brake_off_rel, 3),
        release_abruptness=round(abruptness, 3),
        coaching=_COACHING[cls],
    )


def analyze_trail_braking(
    lap: LapTrace,
    corners: list[tuple[int, int, int]] | None = None,
    *,
    brake_on: float = BRAKE_ON,
    steer_on: float = STEER_ON,
) -> list[TrailBrakeFinding]:
    """Per-corner trail-braking technique read for a lap.

    ``corners`` are ``(entry_i, apex_i, exit_i)`` triples; defaults to
    :func:`lap_dynamics.segment_corners`. Findings are returned in corner order with a 0-based
    ``corner`` index (matching the brain's per-corner indexing).
    """
    segs = corners if corners is not None else segment_corners(lap)
    out: list[TrailBrakeFinding] = []
    for idx, (entry_i, apex_i, exit_i) in enumerate(segs):
        f = _analyze_corner(lap, entry_i, apex_i, exit_i, brake_on=brake_on, steer_on=steer_on)
        out.append(
            TrailBrakeFinding(
                corner=idx,
                apex_spline=f.apex_spline,
                classification=f.classification,
                trail_overlap=f.trail_overlap,
                brake_off_rel=f.brake_off_rel,
                release_abruptness=f.release_abruptness,
                coaching=f.coaching,
            )
        )
    return out


def trail_braking_from_lap_archive(archive: dict) -> list[TrailBrakeFinding] | None:
    """Build trail-braking findings from a lap archive, or None when it has no usable trace."""
    try:
        lap = lap_trace_from_archive(archive)
    except ValueError:
        return None
    return analyze_trail_braking(lap)
