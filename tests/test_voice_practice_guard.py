"""The normal scheduler enforces uncued retention without muting emergency SAVE."""

from __future__ import annotations

import threading

import pytest
from _voice_support import FakeClock, build_manifest, make_advisory

from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.dispatch import DispatchTapPlayback
from tools.ai_sidecar.voice.engine import VoiceCoach
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler


def setup_scheduler(playback=None):
    clock = FakeClock()
    playback = RecordingPlayback() if playback is None else playback
    scheduler = Scheduler(Resolver(build_manifest()), playback, VoiceConfig(), clock=clock)
    return scheduler, playback, clock


def instruction(*, kind="no_trail", urgency="prepare", corner=2):
    return make_advisory(
        kind=kind,
        urgency=urgency,
        corner=corner,
        detail={"coach": "prime", "root": kind},
    )


def save():
    return make_advisory(kind="save", urgency="act", register="critical", detail={"coach": "save"})


def test_retention_filters_an_act_prime_without_swallowing_save_in_same_batch():
    scheduler, playback, clock = setup_scheduler()
    scheduler.set_instructional_guard(lambda: False)
    scheduler.submit(instruction(kind="late_throttle", urgency="act"))
    scheduler.submit(save())
    spoken = scheduler.process_pending(clock())
    assert spoken is not None and spoken.kind == "save"
    assert spoken.instructional is False
    assert [item.kind for item in playback.played] == ["save"]


def test_resolved_deferred_instruction_is_rechecked_at_actual_dispatch():
    scheduler, playback, clock = setup_scheduler()
    allowed = True
    scheduler.set_instructional_guard(lambda: allowed)
    # A non-drill info clip defers the prepare cue through the ordinary phase-slot path.
    scheduler.submit(make_advisory(kind="apex_deficit", urgency="info"))
    assert scheduler.process_pending(clock()) is not None
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is None
    assert len(scheduler._deferred) == 1
    allowed = False  # no refresh: the final dispatch barrier itself must catch this.
    playback.finish()
    assert scheduler.process_pending(clock()) is None
    assert [item.kind for item in playback.played] == ["apex_deficit"]


def test_refresh_purges_queued_instructions_and_cancels_only_current_instruction():
    scheduler, playback, clock = setup_scheduler()
    allowed = True
    scheduler.set_instructional_guard(lambda: allowed)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    scheduler.submit(instruction(corner=4))
    scheduler.submit(save())
    allowed = False
    scheduler.refresh_instructional_guard()
    assert [item.kind for item in playback.cancelled] == ["no_trail"]
    assert [pending.advisory.kind for pending in scheduler._pending] == ["save"]
    assert scheduler.process_pending(clock()).kind == "save"
    scheduler.refresh_instructional_guard()
    assert playback.current is not None and playback.current.kind == "save"
    # Historical evidence remains; cancellation cannot turn a spoken cue into silence.
    assert [item.kind for item in playback.played] == ["no_trail", "save"]


def test_guard_failure_is_closed_for_instruction_but_not_save_or_legacy_warning():
    scheduler, playback, clock = setup_scheduler()

    def broken():
        raise RuntimeError("unavailable practice state")

    scheduler.set_instructional_guard(broken)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is None
    assert scheduler.instructional_guard_error_count >= 1
    scheduler.submit(save())
    assert scheduler.process_pending(clock()).kind == "save"
    playback.finish()
    scheduler.submit(make_advisory(kind="late_brake", urgency="act", register="critical"))
    assert scheduler.process_pending(clock()).kind == "late_brake"


def test_no_guard_and_guard_removal_preserve_normal_instruction_dispatch():
    scheduler, playback, clock = setup_scheduler()
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    playback.finish()
    scheduler.set_instructional_guard(lambda: False)
    scheduler.set_instructional_guard(None)
    clock.advance(20)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None


def test_dispatch_evidence_retains_semantic_flag_and_unknown_duration():
    inner = RecordingPlayback()
    events = []
    tap = DispatchTapPlayback(inner, events.append)
    scheduler, _, clock = setup_scheduler(tap)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    event = events[-1]
    assert event.instructional is True
    assert event.duration_ms is None  # absent duration remains unknown, never fabricated.
    assert event.to_payload()["instructional"] is True
    inner.finish()
    scheduler.submit(save())
    assert scheduler.process_pending(clock()) is not None
    assert events[-1].to_payload()["instructional"] is False
    inner.finish()
    scheduler.submit(make_advisory(kind="late_brake", urgency="act", register="critical"))
    assert scheduler.process_pending(clock()) is not None
    assert events[-1].instructional is None
    assert "instructional" not in events[-1].to_payload()


def test_engine_exposes_guard_without_arming_a_disabled_coach():
    scheduler, playback, clock = setup_scheduler()
    coach = VoiceCoach(scheduler, playback, enabled=True)
    coach.set_instructional_guard(lambda: False)
    assert not coach.practice_evidence_ready  # an unwrapped injected backend has no evidence.
    coach.subscribe(instruction())
    assert scheduler.process_pending(clock()) is None
    coach.refresh_instructional_guard()
    disabled = VoiceCoach.disabled("synthetic unavailable voice")
    disabled.set_instructional_guard(lambda: True)
    disabled.refresh_instructional_guard()
    assert not disabled.enabled
    assert not disabled.practice_evidence_ready


def test_refresh_cannot_cancel_save_that_wins_a_concurrent_dispatch():
    playing_save = threading.Event()
    release_save = threading.Event()

    class PausingPlayback(RecordingPlayback):
        def play(self, utterance):
            if utterance.kind == "save":
                playing_save.set()
                assert release_save.wait(2), "test failed to release the SAVE dispatch"
            super().play(utterance)

    scheduler, playback, clock = setup_scheduler(PausingPlayback())
    allowed = True
    scheduler.set_instructional_guard(lambda: allowed)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    scheduler.submit(save())
    worker = threading.Thread(target=scheduler.process_pending, args=(clock(),))
    worker.start()
    assert playing_save.wait(2)
    allowed = False
    refresh = threading.Thread(target=scheduler.refresh_instructional_guard)
    refresh.start()
    release_save.set()
    worker.join(2)
    refresh.join(2)
    assert not worker.is_alive() and not refresh.is_alive()
    assert playback.current is not None and playback.current.kind == "save"
    assert [item.kind for item in playback.cancelled] == ["no_trail"]


@pytest.mark.parametrize("cancel_reason", ["save_barge_in", "retention_refresh"])
def test_interrupted_instruction_emits_correlation_without_rewriting_dispatch(cancel_reason):
    inner = RecordingPlayback()
    dispatches, cancellations = [], []
    clock = FakeClock()
    tap = DispatchTapPlayback(
        inner,
        dispatches.append,
        cancellation_listener=cancellations.append,
        duration_lookup=lambda _clip: 1000.0,
        mono_clock=clock,
    )
    scheduler = Scheduler(Resolver(build_manifest()), tap, VoiceConfig(), clock=clock)
    allowed = True
    scheduler.set_instructional_guard(lambda: allowed)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    original = dispatches[0]
    clock.advance(0.2)
    if cancel_reason == "save_barge_in":
        scheduler.submit(save())
        assert scheduler.process_pending(clock()).kind == "save"
    else:
        allowed = False
        scheduler.refresh_instructional_guard()
    assert dispatches[0] is original
    assert original.duration_ms == 1000.0  # expected clip length is not an elapsed-play claim.
    assert cancellations == [
        {
            "seq": original.seq,
            "clip_id": original.clip_id,
            "dispatch_t_mono_ms": original.t_mono_ms,
            "cancel_attempted_at_mono_ms": clock() * 1000.0,
            "canceled_at_mono_ms": clock() * 1000.0,
            "cancel_succeeded": True,
        }
    ]
    assert cancellations[0]["canceled_at_mono_ms"] < original.t_mono_ms + original.duration_ms
    if cancel_reason == "save_barge_in":
        assert len(dispatches) == 2 and dispatches[-1].kind == "save"
        scheduler.refresh_instructional_guard()
        assert inner.current is not None and inner.current.kind == "save"
    else:
        assert len(dispatches) == 1  # cancellation is not another coaching.voice event.


def test_finished_or_mismatched_current_cue_never_gets_stale_cancellation_identity():
    inner = RecordingPlayback()
    dispatches, cancellations = [], []
    tap = DispatchTapPlayback(inner, dispatches.append, cancellation_listener=cancellations.append)
    scheduler, _, clock = setup_scheduler(tap)
    scheduler.submit(instruction())
    assert scheduler.process_pending(clock()) is not None
    inner.finish()
    tap.cancel()
    assert cancellations == []
    # If a backend was changed outside the tap, its cue cannot be labelled as the old dispatch.
    clock.advance(20)
    scheduler.submit(instruction(corner=4))
    assert scheduler.process_pending(clock()) is not None
    outside_save = Resolver(build_manifest()).resolve(save())
    inner.play(outside_save)
    tap.cancel()
    assert cancellations == []


@pytest.mark.parametrize("failure", ["throws", "no_op"])
def test_failed_backend_cancel_never_claims_a_successful_stop(failure):
    class FailedCancel(RecordingPlayback):
        def cancel(self):
            if failure == "throws":
                raise RuntimeError("synthetic cancellation failure")

    inner = FailedCancel()
    dispatches, cancellations = [], []
    tap = DispatchTapPlayback(inner, dispatches.append, cancellation_listener=cancellations.append)
    utterance = Resolver(build_manifest()).resolve(instruction())
    tap.play(utterance)
    if failure == "throws":
        with pytest.raises(RuntimeError, match="synthetic cancellation failure"):
            tap.cancel()
    else:
        tap.cancel()
    assert inner.current is utterance
    assert cancellations[0]["seq"] == dispatches[0].seq
    assert cancellations[0]["cancel_succeeded"] is False
    assert cancellations[0]["canceled_at_mono_ms"] is None
    assert tap.cancellation_error_count == 1


def test_cancellation_listener_fault_does_not_break_audio_and_is_observable():
    def broken(_event):
        raise RuntimeError("synthetic cancellation diagnostic failure")

    inner = RecordingPlayback()
    dispatches = []
    tap = DispatchTapPlayback(inner, dispatches.append, cancellation_listener=broken)
    tap.play(Resolver(build_manifest()).resolve(instruction()))
    tap.cancel()
    assert inner.current is None
    assert len(dispatches) == 1
    assert tap.cancellation_error_count == 1
    coach = VoiceCoach(None, tap, enabled=False)
    assert coach.cancellation_error_count == 1


def test_from_bank_forwards_optional_cancellation_diagnostics(monkeypatch):
    manifest = build_manifest()
    monkeypatch.setattr("tools.ai_sidecar.voice.engine.Manifest.load", lambda _path: manifest)
    playback = RecordingPlayback()
    dispatches, cancellations = [], []
    clock = FakeClock()
    coach = VoiceCoach.from_bank(
        "synthetic-bank",
        playback=playback,
        clock=clock,
        dispatch_listener=dispatches.append,
        cancellation_listener=cancellations.append,
    )
    assert coach.enabled
    assert not coach.practice_evidence_ready  # listeners alone do not enforce retention.
    coach.subscribe(instruction())
    assert coach._scheduler.process_pending(clock()) is not None
    coach.set_instructional_guard(lambda: False)
    assert playback.current is None
    assert len(dispatches) == 1 and len(cancellations) == 1
    assert cancellations[0]["seq"] == dispatches[0].seq
    assert cancellations[0]["cancel_succeeded"] is True
    assert coach.cancellation_error_count == 0
    assert coach.practice_evidence_ready
    coach.set_instructional_guard(None)
    assert not coach.practice_evidence_ready


@pytest.mark.parametrize("listeners", ["neither", "dispatch_only", "cancel_only"])
def test_practice_evidence_requires_both_real_listeners(monkeypatch, listeners):
    manifest = build_manifest()
    monkeypatch.setattr("tools.ai_sidecar.voice.engine.Manifest.load", lambda _path: manifest)
    coach = VoiceCoach.from_bank(
        "synthetic-bank",
        playback=RecordingPlayback(),
        dispatch_listener=(lambda _event: None) if listeners == "dispatch_only" else None,
        cancellation_listener=(lambda _event: None) if listeners == "cancel_only" else None,
    )
    coach.set_instructional_guard(lambda: False)
    assert coach.enabled
    assert not coach.practice_evidence_ready


@pytest.mark.parametrize("fault", ["dispatch", "cancellation", "guard"])
def test_practice_evidence_readiness_stays_false_after_an_observation_or_guard_fault(fault):
    def broken(_event=None):
        raise RuntimeError("synthetic evidence failure")

    tap = DispatchTapPlayback(
        RecordingPlayback(),
        broken if fault == "dispatch" else lambda _event: None,
        cancellation_listener=broken if fault == "cancellation" else lambda _event: None,
    )
    scheduler, _, clock = setup_scheduler(tap)
    coach = VoiceCoach(scheduler, tap, enabled=True)
    coach.set_instructional_guard(lambda: True)
    assert coach.practice_evidence_ready
    coach.subscribe(instruction())
    assert scheduler.process_pending(clock()) is not None
    if fault == "cancellation":
        coach.set_instructional_guard(lambda: False)
    elif fault == "guard":
        coach.set_instructional_guard(broken)
    assert not coach.practice_evidence_ready
    coach.set_instructional_guard(lambda: True)
    assert not coach.practice_evidence_ready  # resetting a callback cannot erase missing evidence.
