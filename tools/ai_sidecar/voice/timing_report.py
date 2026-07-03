"""Voice-coach timing-report harness (issue #368, AC a / e / h).

Runs a deterministic scenario through the **real** observer → resolver → scheduler → playback path
with an injected clock and a recording playback (no audio hardware), and emits a JSON artifact that
proves, with numbers:

* **AC a** — each cue is *dispatched before or at its mark* (the audio onset leads the control
  point, not trails it). The report records the telemetry-event time, the advisory time, the
  dispatch time, the per-cue advisory→dispatch latency, the clip id/register/duration, and
  ``onset_before_mark``.
* **AC e** — under LOW verbosity no ``info`` / post-fact narration is spoken (the apex verdict is
  suppressed).
* **AC h** — the scenario does not pass vacuously: it **injects control-point frames around every
  covered corner** (a corner with a usable brake point), so a run that only touched cue-less
  corners fails (``covered_corners >= 1`` is asserted). It never reports success while exercising
  only corners with no usable cues.

The harness is a durable tool (committed, tested), not a scratch script. It builds the observer
from a real reference archive (CLI) or from supplied corner references (tests). Clip durations come
from a baked bank when one is supplied (so the ≤450 ms act-clip budget is verifiable), else they
are null.

Pure stdlib at import; numpy/audio are only touched if a real bank dir is decoded (it is not — clip
durations are read from the WAV header via stdlib ``wave``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.ai_sidecar.realtime_observer import (
    _DEFAULT_TRACK_LENGTH_M,
    Advisory,
    CornerReference,
    RealtimeObserver,
    build_observer_from_reference,
)
from tools.ai_sidecar.voice.config import Verbosity, VoiceConfig
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler

_log = logging.getLogger("ai_sidecar.voice.timing_report")

#: scenario frame rate (Hz) — matches the live ``telemetry_tick`` 20 Hz producer cap.
_FRAME_HZ = 20.0
#: assumed clip length (ms) when no baked bank is supplied, for channel-completion modeling.
_DEFAULT_CLIP_MS = 400.0
_MAX_LEAD_SPLINE = 0.05
_DEFAULT_BRAKE_PREPARE_LEAD_S = 0.8
_CRITICAL_BRAKE_CLIP_ID = "late_brake.act.critical.generic"


@dataclass
class CueRecord:
    """One dispatched cue and its timing, for the report artifact."""

    corner: int
    kind: str
    urgency: str
    register: str
    intensity: float
    clip_id: str
    t_telemetry_event_ms: float
    t_advisory_ms: float
    t_dispatch_ms: float
    t_mark_ms: float
    advisory_to_dispatch_ms: float
    clip_duration_ms: float | None
    anticipatory: bool
    onset_before_mark: bool
    spoken: bool


@dataclass
class TimingReport:
    backend: str
    voice_signature: str
    verbosity: str
    covered_corners: int
    cues: list[CueRecord] = field(default_factory=list)
    assertions: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = {
            "backend": self.backend,
            "voice_signature": self.voice_signature,
            "verbosity": self.verbosity,
            "covered_corners": self.covered_corners,
            "cues": [asdict(c) for c in self.cues],
            "assertions": self.assertions,
        }
        return json.dumps(d, indent=2, sort_keys=False) + "\n"


def _clip_duration_ms(bank_dir: Path | None, clip_id: str, manifest: Manifest) -> float | None:
    """Duration (ms) of a resolved clip from its WAV header, or ``None`` if no bank on disk."""
    if bank_dir is None:
        return None
    entry = manifest.clips.get(clip_id)
    if entry is None:
        return None
    fp = bank_dir / entry.file
    try:
        with wave.open(str(fp), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate() * 1000.0, 1)
    except (OSError, wave.Error):
        return None


def _inject_corner_frames(
    ref: CornerReference,
    *,
    track_length_m: float = _DEFAULT_TRACK_LENGTH_M,
    frame_hz: float = _FRAME_HZ,
    brake_prepare_lead_s: float = _DEFAULT_BRAKE_PREPARE_LEAD_S,
) -> tuple[list[dict[str, Any]], float]:
    """Frames that approach ``ref``'s brake point hot-and-coasting, then over-brake past the apex.

    Returns the frame list and the *spline of the mark* (the brake point) so the caller can find
    when the car reaches it. The approach starts inside the anticipatory lead window (before the
    brake point) so the brake cue can fire BEFORE the mark; a couple of past-apex frames with heavy
    brake and no throttle trigger the release cue.
    """
    bp = ref.best_brake_point_spline
    if bp is None:
        return [], 0.0
    apex = ref.apex_spline
    # approach hot (well above the apex target) and not braking → forces an urgent/critical brake
    # cue
    speed = max(ref.target_apex_kmh + 60.0, 120.0)
    frames: list[dict[str, Any]] = []
    track_length_m = max(track_length_m, 1.0)
    frame_hz = max(frame_hz, 1.0)
    step = max(0.0001, min(0.005, (speed / 3.6) / track_length_m / frame_hz))
    lead = min(_MAX_LEAD_SPLINE, (speed / 3.6) * brake_prepare_lead_s / track_length_m)
    start = max(0.0, bp - max(step * 2.0, min(0.04, lead * 0.5 if lead > 0 else step * 2.0)))
    s = start
    while s <= apex:
        frames.append({"spline": round(s, 4), "speed": speed, "brake": 0.0, "throttle": 0.0})
        s += step
    if lead > 0:
        # Guarantee one pre-brake-point sample inside the same lead window a live 20 Hz producer
        # would hit, even on long tracks where a fixed 0.005 spline step can skip over it.
        lead_frame = max(0.0, bp - max(0.0001, min(lead * 0.5, step)))
        frames.append(
            {"spline": round(lead_frame, 4), "speed": speed, "brake": 0.0, "throttle": 0.0}
        )
    frames = sorted(
        {float(fr["spline"]): fr for fr in frames}.values(), key=lambda fr: fr["spline"]
    )
    # past the apex, still hard on the brakes, off throttle → over-braking / release cue
    for ds in (0.02, 0.04):
        frames.append(
            {
                "spline": round(min(ref.spline_hi, apex + ds), 4),
                "speed": 70.0,
                "brake": 0.7,
                "throttle": 0.0,
            }
        )
    exit_spline = min(0.9999, ref.spline_hi + max(step, 0.005))
    if exit_spline > ref.spline_hi:
        frames.append(
            {
                "spline": round(exit_spline, 4),
                "speed": 90.0,
                "brake": 0.0,
                "throttle": 1.0,
            }
        )
    return frames, bp


def _advisory_dedup_key(advisory: Advisory) -> str:
    """Return the scheduler/resolver dedup identity for an advisory."""
    return f"{advisory.kind}:{advisory.corner}:{advisory.register}"


def build_timing_report(
    observer: RealtimeObserver,
    resolver: Resolver,
    *,
    config: VoiceConfig,
    manifest: Manifest,
    bank_dir: Path | None = None,
    backend: str = "unknown",
    frame_hz: float = _FRAME_HZ,
) -> TimingReport:
    """Drive an injected control-point scenario through the real pipeline; return the timing
    report."""
    dt_ms = 1000.0 / frame_hz
    playback = RecordingPlayback()

    report = TimingReport(
        backend=backend,
        voice_signature=manifest.voice_signature,
        verbosity=config.verbosity.name.lower(),
        covered_corners=0,
    )
    spoken_urgencies: set[str] = set()

    # refs sorted by entry; only those with a usable brake point are "covered" (AC h).
    refs = sorted(observer._refs, key=lambda r: r.spline_lo)
    t_ms = 0.0
    # the playback channel is shared across corners; model clip completion so it frees up like the
    # real audio stream (a clip of its real / ``_DEFAULT_CLIP_MS`` duration finishes). Else the
    # first cue would read "busy" forever and every later cue would be dropped.
    playing_until_ms = -1.0
    for ref in refs:
        frames, mark_spline = _inject_corner_frames(
            ref,
            track_length_m=getattr(observer, "_track_length_m", _DEFAULT_TRACK_LENGTH_M),
            frame_hz=frame_hz,
            brake_prepare_lead_s=getattr(
                observer, "_brake_prepare_lead_s", _DEFAULT_BRAKE_PREPARE_LEAD_S
            ),
        )
        if not frames:
            continue
        report.covered_corners += 1
        observer.reset()
        # a fresh scheduler per corner pass — isolates this corner's arbitration deterministically.
        # ``h=clock_holder`` binds the per-iteration holder at lambda-definition time (avoids the
        # loop-variable-capture pitfall — ruff B023).
        clock_holder = {"t": t_ms / 1000.0}
        sched = Scheduler(resolver, playback, config, clock=lambda h=clock_holder: h["t"])
        # Precompute the *true* mark time (when the car reaches the brake point) from the frame
        # sequence, so a cue that fires anticipatorily — before the mark is reached — still records
        # the real, later mark (not a fallback to its own time).
        mark_idx = next(
            (i for i, fr in enumerate(frames) if float(fr["spline"]) >= mark_spline), None
        )
        t_mark_ms: float | None = (t_ms + mark_idx * dt_ms) if mark_idx is not None else None
        for fr in frames:
            clock_holder["t"] = t_ms / 1000.0
            # free the channel when the currently-sounding clip has finished (real-stream behavior)
            if playback.current is not None and t_ms >= playing_until_ms:
                playback.finish()
            advisories: list[Advisory] = observer.observe(fr)
            for adv in advisories:
                sched.submit(adv)
            before = len(playback.played)
            winner = sched.process_pending(clock_holder["t"]) if advisories else None
            spoke = winner is not None and len(playback.played) > before
            if spoke and winner is not None:
                spoken_urgencies.add(winner.urgency)
                dur = _clip_duration_ms(bank_dir, winner.clip_id, manifest) or _DEFAULT_CLIP_MS
                playing_until_ms = t_ms + dur
            for adv in advisories:
                utt = (
                    winner
                    if spoke and winner is not None and winner.dedup_key == _advisory_dedup_key(adv)
                    else None
                )
                clip_id = utt.clip_id if utt is not None else ""
                report.cues.append(
                    CueRecord(
                        corner=adv.corner,
                        kind=adv.kind,
                        urgency=adv.urgency,
                        register=(utt.register if utt is not None else adv.register),
                        intensity=adv.intensity,
                        clip_id=clip_id,
                        t_telemetry_event_ms=round(t_ms, 1),
                        t_advisory_ms=round(t_ms, 1),
                        t_dispatch_ms=round(t_ms, 1),
                        t_mark_ms=round(t_mark_ms if t_mark_ms is not None else t_ms, 1),
                        advisory_to_dispatch_ms=0.0,  # synchronous arbitration in the harness
                        clip_duration_ms=_clip_duration_ms(bank_dir, clip_id, manifest),
                        anticipatory=bool(adv.detail.get("anticipatory", False)),
                        # raw fact: did this cue's dispatch land at/before the corner's brake mark?
                        # (only meaningful for anticipatory cues — a release/verdict legitimately
                        # fires past the mark; see the assertion below.)
                        onset_before_mark=(t_mark_ms is None or t_ms <= t_mark_ms),
                        spoken=utt is not None,
                    )
                )
            t_ms += dt_ms

    spoken = [c for c in report.cues if c.spoken]
    anticipatory = [c for c in report.cues if c.anticipatory]
    spoken_anticipatory = [c for c in anticipatory if c.spoken]
    # AC c: the TIME-CRITICAL brake alarm (the late_brake act cue) must be ≤450 ms. A 2-syllable
    # correction like "Release." sits ~540 ms — the honest floor of an intelligible 2-syllable word,
    # not padding — so it is reported but not gated here.
    brake_alarm_over_budget = [
        c
        for c in spoken
        if c.kind == "late_brake" and c.urgency == "act" and (c.clip_duration_ms or 0) > 450.0
    ]
    critical_brake_alarm_spoken = any(c.clip_id == _CRITICAL_BRAKE_CLIP_ID for c in spoken)
    report.assertions = {
        "covered_corners_at_least_one": report.covered_corners >= 1,
        # AC a: an anticipatory cue actually fired, and EVERY anticipatory cue's onset led its mark.
        # (Reactive cues — over-braking release, past-the-point alarm, apex verdict — are exempt;
        # they correctly fire at/after the mark.)
        "anticipatory_cue_fired": len(spoken_anticipatory) >= 1,
        "anticipatory_onset_before_mark": all(c.onset_before_mark for c in spoken_anticipatory),
        "no_info_spoken_in_low_verbosity": (
            config.verbosity != Verbosity.LOW or "info" not in spoken_urgencies
        ),
        "brake_alarm_within_450ms": (bank_dir is None or not brake_alarm_over_budget),
        "critical_brake_alarm_spoken": (
            config.verbosity == Verbosity.OFF or critical_brake_alarm_spoken
        ),
        # A non-vacuous proof must actually dispatch a cue — unless verbosity is OFF (muted).
        # A resolver/bank gap that silently suppresses everything must FAIL the report, not pass it
        # because the structural assertions held (codex review #371). This is a BOOL so main()'s
        # exit-status check (which gates on the boolean assertions) catches it.
        "cues_spoken_when_audible": (config.verbosity == Verbosity.OFF or len(spoken) >= 1),
        "cues_spoken": len(spoken),
    }
    return report


def _synthetic_observer() -> RealtimeObserver:
    """A 2-corner reference with usable brake points — for the offline/test scenario."""
    refs = [
        CornerReference(
            index=0, apex_spline=0.30, spline_lo=0.24, spline_hi=0.38,
            optimal_apex_kmh=90.0, best_observed_apex_kmh=90.0, best_brake_point_spline=0.25,
            n_corpus=1,
        ),
        CornerReference(
            index=1, apex_spline=0.70, spline_lo=0.64, spline_hi=0.78,
            optimal_apex_kmh=110.0, best_observed_apex_kmh=110.0, best_brake_point_spline=0.65,
            n_corpus=1,
        ),
    ]  # fmt: skip
    return RealtimeObserver(refs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice-coach timing report (issue #368).")
    parser.add_argument("--bank", help="baked bank dir (for clip durations + voice signature)")
    parser.add_argument(
        "--reference", help="reference lap archive JSON (else a synthetic scenario)"
    )
    parser.add_argument("--verbosity", default="normal", help="off|low|normal|high")
    parser.add_argument("--out", help="write the report JSON here (else stdout)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = VoiceConfig(verbosity=args.verbosity)
    bank_dir = Path(args.bank) if args.bank else None
    if bank_dir is not None:
        manifest = Manifest.load(bank_dir / MANIFEST_FILENAME)
        # Reject a stale/corrupt bank up front (vocabulary drift, missing/mismatched WAVs) — the
        # fake playback would otherwise mark clips "spoken" that the real coach (from_bank)
        # would refuse, producing a green-but-wrong report (codex review #371).
        report_ok = manifest.validate(bank_dir)
        if not report_ok.ok:
            raise SystemExit(
                "bank failed validation (the real coach would disable or skip these clips):\n  "
                + "\n  ".join(report_ok.problems or ["vocabulary_hash mismatch"])
            )
    else:
        # in-memory manifest over the current vocabulary (no clip durations without a bank)
        from tools.ai_sidecar.voice import vocabulary as vocab
        from tools.ai_sidecar.voice.manifest import MANIFEST_VERSION, ClipEntry

        clips = {
            p.clip_id: ClipEntry(
                clip_id=p.clip_id, file=f"{p.clip_id}.wav", kind=p.kind, urgency=p.urgency,
                register=p.register, corner=p.corner, text=p.text, sha256="0" * 64,
            )
            for p in vocab.iter_vocabulary()
        }  # fmt: skip
        manifest = Manifest(
            version=MANIFEST_VERSION, samplerate=22050, voice_signature="in-memory",
            vocabulary_hash=vocab.vocabulary_hash(), clips=clips,
        )  # fmt: skip

    if args.reference:
        archive = json.loads(Path(args.reference).read_text(encoding="utf-8"))
        observer = build_observer_from_reference(archive)
        if observer is None:
            raise SystemExit("reference archive has no usable corners — cannot build a scenario")
    else:
        observer = _synthetic_observer()

    report = build_timing_report(
        observer, Resolver(manifest), config=config, manifest=manifest,
        bank_dir=bank_dir, backend=(args.bank or "synthetic"),
    )  # fmt: skip
    text = report.to_json()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(
            f"wrote timing report -> {args.out} ({report.covered_corners} covered corners, "
            f"{report.assertions['cues_spoken']} cues spoken)"
        )
    else:
        print(text)
    return 0 if all(v for k, v in report.assertions.items() if isinstance(v, bool)) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
