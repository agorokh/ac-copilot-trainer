"""Semantic-timeliness metric — was each spoken cue ACTIONABLE COACHING or noise? (#522)

The falsifiable definition of "it coaches": record live telemetry (20 Hz), every
``coaching.cue`` advisory, and every ``coaching.voice`` dispatch on ONE wall clock, then for
each spoken cue compute the car's true position/speed/brake at the moment the clip
*finishes sounding in the ear* (dispatch + audio latency + clip duration) and classify:

    ACTIONABLE   heard complete 0.8-6.0 s before its mark — a human can act
    TOO_EARLY    > 6 s before the mark (forgettable)
    TOO_LATE     < 0.8 s before the mark (cannot react)
    AFTER_FACT   the mark is already behind the car (the #522 "Brake mid-straight" case)
    REDUNDANT    an act imperative while the driver is already braking >= 0.5
    DEBRIEF_OK   info-tier feedback delivered after the corner (its correct place)

Also scores brake-zone coverage: every real braking event NEAR A REFERENCE BRAKE MARK should have
had a brake cue in its actionable window. Onsets with no reference mark within ``COACHABLE_TOL_M``
(a mid-straight correction dab, trail-braking where no corpus brake point sits) are *off-zone* —
they cannot be coached, so they are excluded from the coverage denominator, and repeat onsets in
one zone count once (issue #527, split from #522). The ``assert`` gate encodes #522's acceptance
criteria: zero AFTER_FACT/TOO_LATE brake cues and >= the required fraction of COACHABLE brake zones
coached. The raw per-onset ratio and a reference zones-cued/zones-crossed line are reported too.

Usage::

    python -m tools.ai_sidecar.voice.semantic_timeliness record --out tap.jsonl --seconds 300
    python -m tools.ai_sidecar.voice.semantic_timeliness analyze --tap tap.jsonl \
        --track-length-m 2455.7 [--audio-latency-s 0.10] [--assert-coaching]

``record`` connects to the sidecar as a ``physical``-class peer (receives the relayed
telemetry ticks plus all broadcasts). Pure stdlib except ``websockets`` for record.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ACTIONABLE_MIN_S = 0.8
ACTIONABLE_MAX_S = 6.0
#: how far before a real brake onset a brake cue counts as having coached that event.
COVERAGE_WINDOW_S = 6.0
#: an onset within this many metres of a reference/calibrated brake mark is *coachable* — a brake
#: point exists there to cue against. Farther out there is nothing to coach (a mid-straight
#: correction dab, or trail-braking where no corpus brake point sits), so counting it in the
#: coverage denominator penalises the coach for events it cannot address (issue #527). Mirrors the
#: 50 m zone-match tolerance in ``realtime_observer._CAL_MATCH_TOL_M`` — kept in sync by value
#: because the ``analyze`` path is deliberately stdlib-pure and does not import the observer.
COACHABLE_TOL_M = 50.0
DEFAULT_AUDIO_LATENCY_S = 0.10  # PC rtmixer path; tablet WebAudio measured ~0.45 (#511)


@dataclass
class CueVerdict:
    seq: int | None
    clip_id: str
    kind: str
    urgency: str
    register: str
    heard_at_spline: float | None
    speed_kmh: float | None
    brake: float | None
    mark_spline: float | None
    gap_m: float | None
    tta_s: float | None
    verdict: str


@dataclass
class TimelinessReport:
    cues: list[CueVerdict]
    summary: dict[str, int]
    #: raw counts: EVERY gate-grade brake onset, and how many any brake cue covered in time. Kept
    #: for the reported raw ratio; no longer what the gate divides on (issue #527).
    brake_events: int
    brake_events_coached: int
    #: coachable-zone counts (issue #527): onsets within COACHABLE_TOL_M of a reference brake mark,
    #: collapsed to one per zone. ``coachable_brake_zones_coached`` is how many of those zones had
    #: a covering cue. This ratio is what ``brake_events_coached`` asserts on.
    coachable_brake_zones: int = 0
    coachable_brake_zones_coached: int = 0
    #: onsets with no reference mark within tolerance — nothing to coach against (excluded above).
    off_zone_brake_onsets: int = 0
    #: per-zone coverage guarantee (#522): reference brake zones the car crossed vs zones a cue was
    #: dispatched for. ``zones_cued == zones_crossed`` is the coverage guarantee stated directly.
    zones_crossed: int = 0
    zones_cued: int = 0
    assertions: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["cues"] = [asdict(c) for c in self.cues]
        return out


def _load_tap(path: Path) -> tuple[list, list, list]:
    ticks, advisories, dispatches = [], [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("k") == "tick" and r.get("spline") is not None:
                ticks.append(
                    (
                        r["t"],
                        float(r["spline"]),
                        float(r.get("speed") or 0.0),
                        float(r.get("brake") or 0.0),
                    )
                )
            elif r.get("k") == "coaching.cue":
                advisories.append((r["t"], r["payload"]))
            elif r.get("k") == "coaching.voice":
                p = r["payload"]
                # Recorder-clock timestamp keeps ticks/advisories/dispatches on ONE clock even
                # when the recorder runs on a different host than the sidecar (PR #523 review).
                # Loopback receive lag is ~1-5 ms; the sidecar's own t_wall_ms stays in the
                # payload as metadata.
                dispatches.append((float(r["t"]), p))
    ticks.sort(key=lambda x: x[0])
    # key= is load-bearing: tuples ending in dicts raise TypeError on timestamp ties.
    return ticks, advisories, sorted(dispatches, key=lambda x: x[0])


def _interp_state(ticks: list, times: list, t_ms: float) -> tuple[float, float, float] | None:
    if not ticks:
        return None
    i = bisect.bisect_left(times, t_ms)
    if i <= 0:
        return ticks[0][1:]
    if i >= len(ticks):
        return ticks[-1][1:]
    (t0, s0, v0, b0), (t1, s1, v1, b1) = ticks[i - 1], ticks[i]
    f = (t_ms - t0) / max(t1 - t0, 1e-6)
    ds = s1 - s0
    if ds < -0.5:
        ds += 1.0  # spline wrap
    return ((s0 + f * ds) % 1.0, v0 + f * (v1 - v0), b0 + f * (b1 - b0))


def _signed_gap_m(mark: float, car: float, track_length_m: float) -> float:
    d = (mark - car) % 1.0
    if d > 0.5:
        d -= 1.0
    return d * track_length_m


def analyze(
    tap_path: Path,
    *,
    track_length_m: float,
    audio_latency_s: float = DEFAULT_AUDIO_LATENCY_S,
    coverage_min_fraction: float = 0.8,
) -> TimelinessReport:
    ticks, advisories, dispatches = _load_tap(tap_path)
    times = [t[0] for t in ticks]

    def nearest_advisory(t_ms: float, kind: str) -> dict | None:
        best = None
        for t, p in advisories:
            if p.get("kind") == kind and abs(t - t_ms) <= 2500:
                if best is None or abs(t - t_ms) < abs(best[0] - t_ms):
                    best = (t, p)
        return best[1] if best else None

    cues: list[CueVerdict] = []
    for t_disp, p in dispatches:
        kind, urg = str(p.get("kind")), str(p.get("urgency"))
        dur_s = float(p.get("duration_ms") or 500.0) / 1000.0
        t_heard = t_disp + (audio_latency_s + dur_s) * 1000.0
        state = _interp_state(ticks, times, t_heard)
        adv = nearest_advisory(t_disp, kind)
        mark = adv.get("spline") if adv else None
        verdict = "NO_TELEMETRY"
        sp = v = b = gap = tta = None
        if state is not None:
            sp, v, b = state
            if mark is None:
                verdict = "NO_MARK"
            elif v <= 3.0:
                verdict = "CAR_STOPPED"
            else:
                gap = _signed_gap_m(float(mark), sp, track_length_m)
                tta = gap / (v / 3.6)
                if urg == "info":
                    verdict = "DEBRIEF_OK" if gap < 20.0 else "INFO_BEFORE_CORNER"
                elif gap < -30.0:
                    verdict = "AFTER_FACT"
                elif tta < ACTIONABLE_MIN_S:
                    # Timing verdicts FIRST: a just-late cue while the pedal is already down
                    # must read TOO_LATE (gated), never hide behind REDUNDANT (non-gating) —
                    # PR #523 review.
                    verdict = "TOO_LATE"
                elif urg == "act" and b >= 0.5:
                    verdict = "REDUNDANT"
                elif tta > ACTIONABLE_MAX_S:
                    verdict = "TOO_EARLY"
                else:
                    verdict = "ACTIONABLE"
        cues.append(
            CueVerdict(
                seq=p.get("seq"),
                clip_id=str(p.get("clip_id")),
                kind=kind,
                urgency=urg,
                register=str(p.get("register")),
                heard_at_spline=round(sp, 4) if sp is not None else None,
                speed_kmh=round(v, 1) if v is not None else None,
                brake=round(b, 2) if b is not None else None,
                mark_spline=round(float(mark), 4) if mark is not None else None,
                gap_m=round(gap, 1) if gap is not None else None,
                tta_s=round(tta, 2) if tta is not None else None,
                verdict=verdict,
            )
        )

    summary: dict[str, int] = {}
    for c in cues:
        summary[c.verdict] = summary.get(c.verdict, 0) + 1

    # --- brake-zone coverage (issue #527) --------------------------------------------------------
    # Real brake onsets: brake crosses 0.4 upward at speed > 60. Capture the spline at the onset so
    # each onset can be matched to a reference brake zone.
    onsets: list[tuple[float, float]] = []  # (t_ms, spline)
    prev_b = 0.0
    for t, s, v, b in ticks:
        if b >= 0.4 and prev_b < 0.4 and v > 60.0:
            onsets.append((t, s))
        prev_b = b

    # Reference brake marks the observer flagged this lap. Every ``late_brake`` advisory carries the
    # corner it belongs to (``corner``) and the brake-point ``spline``; the anticipatory heads-up
    # fires as the car approaches each zone, so the distinct corners here are the reference brake
    # zones CROSSED during recording.
    brake_marks: list[tuple[float, Any]] = [
        (float(p["spline"]), p.get("corner"))
        for (_t, p) in advisories
        if p.get("kind") == "late_brake" and p.get("spline") is not None
    ]

    def _zone_of(spline: float) -> Any | None:
        """Zone key of the reference brake mark nearest ``spline`` within tolerance, else None.

        The key is the mark's ``corner`` index when present (stable across marks of the same
        corner, so repeat onsets in one zone collapse); it falls back to the mark spline bucketed
        to the tolerance when a tap predates the ``corner`` field. None means the onset is
        *off-zone* — no reference brake point sits near it, so there is nothing to coach against.
        """
        best_key: Any | None = None
        best_d: float | None = None
        for ms, mc in brake_marks:
            d = abs(_signed_gap_m(ms, spline, track_length_m))
            if best_d is None or d < best_d:
                best_d = d
                best_key = mc if mc is not None else round(ms * track_length_m / COACHABLE_TOL_M)
        if best_d is None or best_d > COACHABLE_TOL_M:
            return None
        return best_key

    # Coverage anchors on HEARD-COMPLETE time (dispatch + audio latency + clip duration), matching
    # the per-cue verdicts — a cue that finishes in-ear after the brake onset must not count as
    # having coached it (PR #523 review).
    brake_cue_heard = [
        t + (audio_latency_s + float(p.get("duration_ms") or 500.0) / 1000.0) * 1000.0
        for (t, p) in dispatches
        if p.get("kind") == "late_brake"
    ]

    def _covered(t_ms: float) -> bool:
        return any(
            t_ms - COVERAGE_WINDOW_S * 1000.0 <= bt <= t_ms + 200.0 for bt in brake_cue_heard
        )

    # Partition onsets into coachable zones (collapsing repeats) vs off-zone. The gate divides on
    # coachable zones only; the raw ratio (every onset) stays reported for context.
    coachable_zones: dict[Any, bool] = {}  # zone key -> coached (any onset in the zone covered)
    off_zone_brake_onsets = 0
    coached_raw = 0
    for t_ms, spline in onsets:
        cov = _covered(t_ms)
        if cov:
            coached_raw += 1
        key = _zone_of(spline)
        if key is None:
            off_zone_brake_onsets += 1
            continue
        coachable_zones[key] = coachable_zones.get(key, False) or cov

    coachable_count = len(coachable_zones)
    coachable_coached = sum(1 for v in coachable_zones.values() if v)

    # Per-zone coverage guarantee (#522): every reference brake zone the car crossed should have a
    # cue dispatched for it. Distinct corners of the ``late_brake`` advisories (crossed) vs the
    # ``late_brake`` dispatches (cued). Reported, not gated — a crossed-but-uncued zone (e.g. the
    # T2 heads-up lost behind a playing exit debrief) is the #522 V2 phase-slot scheduler's scope.
    zones_crossed = {
        p.get("corner")
        for (_t, p) in advisories
        if p.get("kind") == "late_brake" and p.get("corner") is not None
    }
    zones_cued = {
        p.get("corner")
        for (_t, p) in dispatches
        if p.get("kind") == "late_brake" and p.get("corner") is not None
    }

    brake_cues = [c for c in cues if c.kind == "late_brake"]
    assertions = {
        # A tap with no telemetry or no dispatched cues proves nothing — it must FAIL the
        # gate, never pass it vacuously (PR #523 review).
        "evidence_present": len(ticks) >= 100 and len(cues) >= 1,
        "no_after_fact_brake_cues": all(c.verdict != "AFTER_FACT" for c in brake_cues),
        "no_too_late_brake_cues": all(c.verdict != "TOO_LATE" for c in brake_cues),
        # Gate on COACHABLE zones only (issue #527): onsets with no reference mark within
        # COACHABLE_TOL_M cannot be coached (no brake point to cue), and repeat onsets inside one
        # zone count once — so a scrappy lap's correction dabs no longer drag the metric red.
        "brake_events_coached": (
            not coachable_zones or coachable_coached / coachable_count >= coverage_min_fraction
        ),
        "some_actionable_coaching": (
            not brake_cues or any(c.verdict == "ACTIONABLE" for c in brake_cues)
        ),
    }
    return TimelinessReport(
        cues=cues,
        summary=summary,
        brake_events=len(onsets),
        brake_events_coached=coached_raw,
        coachable_brake_zones=coachable_count,
        coachable_brake_zones_coached=coachable_coached,
        off_zone_brake_onsets=off_zone_brake_onsets,
        zones_crossed=len(zones_crossed),
        zones_cued=len(zones_cued),
        assertions=assertions,
    )


def _record_to(url: str, out_path: Path, seconds: float) -> dict[str, int]:
    """Sync wrapper: owns the (blocking) file handle; the async loop only writes lines."""
    with open(out_path, "w", encoding="utf-8") as fh:
        return asyncio.run(_record(url, fh, seconds))


async def _record(url: str, fh: Any, seconds: float) -> dict[str, int]:
    import websockets

    counts = {"tick": 0, "coaching.cue": 0, "coaching.voice": 0}
    if fh:  # handle owned/closed by _record_to; line writes are tiny (no async file IO needed)
        async with websockets.connect(url, max_size=2**22) as ws:
            await ws.send(
                json.dumps(
                    {
                        "v": 1,
                        "type": "hello",
                        "client": "semantic-timeliness",
                        "client_class": "physical",
                    }
                )
            )
            await ws.recv()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                budget = max(0.1, deadline - time.monotonic())
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=budget)
                except TimeoutError:
                    break
                t = time.time() * 1000.0
                try:
                    fr = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                topic = fr.get("topic")
                if fr.get("type") == "telemetry_tick":
                    p = fr.get("payload", {})
                    fh.write(
                        json.dumps(
                            {
                                "t": t,
                                "k": "tick",
                                "spline": p.get("spline"),
                                "speed": p.get("speed_kmh"),
                                "brake": p.get("brake"),
                            }
                        )
                        + "\n"
                    )
                    counts["tick"] += 1
                elif topic in ("coaching.cue", "coaching.voice"):
                    fh.write(json.dumps({"t": t, "k": topic, "payload": fr.get("payload")}) + "\n")
                    counts[topic] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_rec = sub.add_parser("record", help="record telemetry + coaching frames to JSONL")
    p_rec.add_argument("--out", required=True)
    p_rec.add_argument("--seconds", type=float, default=300.0)
    p_rec.add_argument("--sidecar-url", default="ws://127.0.0.1:8765")
    p_an = sub.add_parser("analyze", help="score a recorded tap")
    p_an.add_argument("--tap", required=True)
    p_an.add_argument("--track-length-m", type=float, required=True)
    p_an.add_argument("--audio-latency-s", type=float, default=DEFAULT_AUDIO_LATENCY_S)
    p_an.add_argument("--coverage-min", type=float, default=0.8)
    p_an.add_argument("--out", default=None, help="write report JSON here")
    p_an.add_argument(
        "--assert-coaching",
        action="store_true",
        help="exit non-zero unless the #522 coaching assertions hold",
    )
    args = parser.parse_args(argv)

    if args.command == "record":
        counts = _record_to(args.sidecar_url, Path(args.out), args.seconds)
        print(json.dumps(counts))
        return 0

    report = analyze(
        Path(args.tap),
        track_length_m=args.track_length_m,
        audio_latency_s=args.audio_latency_s,
        coverage_min_fraction=args.coverage_min,
    )
    for c in report.cues:
        print(
            f"  #{c.seq} {c.clip_id:38} tta={c.tta_s!s:>7}s gap={c.gap_m!s:>8}m "
            f"brake={c.brake!s:>4} -> {c.verdict}"
        )
    print("summary:", json.dumps(report.summary))
    print(
        f"brake events coached (raw): {report.brake_events_coached}/{report.brake_events} "
        f"({report.off_zone_brake_onsets} off-zone)"
    )
    print(
        "coachable zones coached (gate): "
        f"{report.coachable_brake_zones_coached}/{report.coachable_brake_zones}"
    )
    print(f"reference brake zones cued/crossed: {report.zones_cued}/{report.zones_crossed}")
    print("assertions:", json.dumps(report.assertions))
    if args.out:
        Path(args.out).write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")
    if args.assert_coaching and not all(report.assertions.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
