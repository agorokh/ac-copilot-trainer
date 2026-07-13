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

# An onset within this many metres of a reference/calibrated brake mark is *coachable* — a brake
# point exists there to cue against. Farther out there is nothing to coach (a mid-straight
# correction dab, or trail-braking where no corpus brake point sits), so counting it in the
# coverage denominator penalises the coach for events it cannot address (issue #527). This IS the
# observer's public zone-match tolerance — imported, not re-declared, so analyzer and observer
# share one source of truth and can never silently drift (Qodo rule 263211 / daemon #538 MEDIUM).
# The observer is stdlib-pure, so the ``analyze`` path stays stdlib-only.
from tools.ai_sidecar.realtime_observer import CAL_MATCH_TOL_M as COACHABLE_TOL_M

ACTIONABLE_MIN_S = 0.8
ACTIONABLE_MAX_S = 6.0
#: how far before a real brake onset a brake cue counts as having coached that event.
COVERAGE_WINDOW_S = 6.0
#: how long (ms) BEFORE a brake onset the anticipatory advisory for that pass may have fired — the
#: observer's lead budget (~3.2 s) plus approach travel and recorder skew. An advisory older than
#: this is a DIFFERENT pass (a re-crossing on a later lap is a lap-time away), so an onset only
#: binds to an advisory inside this window; a coachable onset with none is a dropped-advisory pass
#: (uncoached), never a stale earlier-lap occurrence (codex #538 P1). Comfortably below any real
#: lap time, comfortably above the max lead→onset gap.
ONSET_CUE_LEAD_MAX_MS = 10_000.0
DEFAULT_AUDIO_LATENCY_S = 0.10  # PC rtmixer path; tablet WebAudio measured ~0.45 (#511)


@dataclass
class CueVerdict:
    seq: int | None
    clip_id: str
    kind: str
    urgency: str
    register: str
    #: the SPOKEN 1-based corner number the cue belongs to (``corner+1``), as ``coaching.voice``
    #: carries it (issue #511 Part D dispatch payload → ``Utterance.corner``, voice/resolver.py) —
    #: NOT the 0-based ``coaching.cue`` corner. Reported for readability only; the #527 coverage
    #: metric binds cues to marks by timestamp, never by comparing this against a 0-based corner.
    #: None on taps that predate the field.
    corner: int | None
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
    #: coachable-zone counts (issue #527): distinct zones the driver braked in within
    #: COACHABLE_TOL_M of a reference brake mark (repeats collapsed).
    #: ``coachable_brake_zones_coached`` is how many of those zones drew an ACTIONABLE brake cue.
    #: This ratio is what the ``brake_events_coached`` assertion gates on.
    coachable_brake_zones: int = 0
    coachable_brake_zones_coached: int = 0
    #: onsets with no reference mark within tolerance — nothing to coach against (excluded above).
    off_zone_brake_onsets: int = 0
    #: per-pass coverage guarantee (#522): reference brake passes the observer flagged (crossed) vs
    #: passes that drew an ACTIONABLE cue (cued). ``zones_cued == zones_crossed`` is the coverage
    #: guarantee stated directly; a shortfall names the #522-V2 uncued passes (e.g. a dropped T2).
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
                corner=p.get("corner"),
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

    # Reference brake-mark OCCURRENCES the observer flagged. Each anticipatory ``late_brake``
    # advisory (urgency prepare/act — the "ran deep" debrief is urgency=info at the apex, not a
    # brake point) is one pass at a brake mark. The observer emits ONE such advisory per corner
    # pass (deduped, reset on lap wrap), so an advisory maps 1:1 to a physical brake-zone pass; its
    # occurrence identity is the advisory index, and ``t`` (recorder clock) places it in a lap.
    brake_mark_occ = [
        {"i": i, "spline": float(p["spline"]), "corner": p.get("corner"), "t": t}
        for i, (t, p) in enumerate(advisories)
        if p.get("kind") == "late_brake"
        and p.get("spline") is not None
        and p.get("urgency") != "info"
    ]

    def _onset_occ(t_onset: float, spline: float) -> Any | None:
        """Occurrence key of the brake pass an onset belongs to, or None when off-zone.

        Off-zone = no reference mark within COACHABLE_TOL_M (nothing to coach). Otherwise bind to a
        TIME-LOCAL advisory of THIS pass — one whose anticipatory cue could have led this onset
        (fired within ``ONSET_CUE_LEAD_MAX_MS`` before it); a re-crossing on a later lap is a
        lap-time away and is rejected as stale (codex #538 P1). A coachable onset with no local
        advisory is a dropped-advisory pass → a distinct ``("gap", …)`` key that is never coached,
        keyed so repeat dabs on this pass collapse yet other laps stay separate.
        """
        near = [
            occ
            for occ in brake_mark_occ
            if abs(_signed_gap_m(occ["spline"], spline, track_length_m)) <= COACHABLE_TOL_M
        ]
        if not near:
            return None
        local = [occ for occ in near if -2000.0 <= (t_onset - occ["t"]) <= ONSET_CUE_LEAD_MAX_MS]
        if local:
            best = min(
                local,
                key=lambda o: (
                    abs(_signed_gap_m(o["spline"], spline, track_length_m)),
                    abs(o["t"] - t_onset),
                ),
            )
            return ("occ", best["i"])
        nearest = min(near, key=lambda o: abs(_signed_gap_m(o["spline"], spline, track_length_m)))
        return ("gap", round(nearest["spline"], 3), int(t_onset // ONSET_CUE_LEAD_MAX_MS))

    def _dispatch_occ(t_disp: float, dispatch_corner: Any) -> Any | None:
        """Occurrence key a dispatched cue belongs to, bound by the DETERMINISTIC corner relation
        (advisory 0-based, dispatch spoken 1-based ⇒ ``occ.corner + 1 == dispatch.corner``),
        tie-broken by nearest recorder time to pick the sub-zone/pass within that corner. Corner is
        the deterministic key; time only disambiguates (daemon #538 HIGH — not a fuzzy time-only
        match). Falls back to nearest-time when either corner is absent (older taps).
        """
        best: tuple[float, int] | None = None
        for occ in brake_mark_occ:
            if (
                dispatch_corner is not None
                and occ["corner"] is not None
                and occ["corner"] + 1 != dispatch_corner
            ):
                continue
            dt = abs(occ["t"] - t_disp)
            if dt <= 2500.0 and (best is None or dt < best[0]):
                best = (dt, occ["i"])
        return ("occ", best[1]) if best else None

    # Occurrences that drew an ACTIONABLE brake cue — the #522 guarantee ("a brake cue in its
    # actionable window") and the issue's "zones cued" signal. Grading on the per-cue ACTIONABLE
    # verdict (not sub-window onset timing) is what removes the noise #527 targets: a driver who
    # brakes a hair before hearing an otherwise-actionable cue must not flip the occurrence red;
    # TOO_LATE / AFTER_FACT brake cues stay caught globally by their own gates. ``cues`` is built
    # one-per-dispatch, in order, so it zips 1:1 with ``dispatches`` for the dispatch clock/corner.
    coached_occ: set[Any] = set()
    for c, (t_disp, _p) in zip(cues, dispatches, strict=True):
        if c.kind == "late_brake" and c.verdict == "ACTIONABLE":
            key = _dispatch_occ(t_disp, c.corner)
            if key is not None:
                coached_occ.add(key)

    # Partition onsets: coachable passes (repeat dabs at one mark collapse to that occurrence) vs
    # off-zone. Raw per-onset ratio kept for context; the gate divides on coachable passes.
    coachable_occ: set[Any] = set()
    off_zone_brake_onsets = 0
    coached_raw = 0
    for t_ms, spline in onsets:
        key = _onset_occ(t_ms, spline)
        if key is None:
            off_zone_brake_onsets += 1
        else:
            coachable_occ.add(key)
            if key in coached_occ:
                coached_raw += 1

    coachable_count = len(coachable_occ)
    coachable_coached = len(coachable_occ & coached_occ)

    # Per-pass coverage guarantee (#522), stated directly: reference brake passes the observer
    # flagged (crossed) vs those that drew an ACTIONABLE cue (cued). A crossed-but-uncued pass
    # (e.g. the T2 heads-up lost behind a still-playing exit debrief) is #522 V2 phase-slot
    # scheduler scope — surfaced here, not regressed into this gate.
    zones_crossed = len(brake_mark_occ)
    zones_cued = len(coached_occ)

    brake_cues = [c for c in cues if c.kind == "late_brake"]
    assertions = {
        # A tap with no telemetry or no dispatched cues proves nothing — it must FAIL the
        # gate, never pass it vacuously (PR #523 review).
        "evidence_present": len(ticks) >= 100 and len(cues) >= 1,
        "no_after_fact_brake_cues": all(c.verdict != "AFTER_FACT" for c in brake_cues),
        "no_too_late_brake_cues": all(c.verdict != "TOO_LATE" for c in brake_cues),
        # Gate on COACHABLE occurrences only (issue #527): onsets with no reference mark within
        # COACHABLE_TOL_M cannot be coached, repeat dabs at one mark count once, and an occurrence
        # is coached iff it drew an ACTIONABLE cue — so a scrappy lap's correction dabs (and a
        # hair-early brake on an actionable cue) no longer drag it red. But brake onsets with NO
        # brake marks at all must NOT pass vacuously (codex #538 P1): that is a coaching pipeline
        # producing zero brake marks, not evidence of coverage.
        "brake_events_coached": (
            False
            if (onsets and not brake_mark_occ)
            else (
                not coachable_count or coachable_coached / coachable_count >= coverage_min_fraction
            )
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
        zones_crossed=zones_crossed,
        zones_cued=zones_cued,
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
