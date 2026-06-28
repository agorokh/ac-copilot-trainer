"""Tests for the urgency scheduler — the core arbitration logic (no audio hardware).

Drives :meth:`Scheduler.process_pending` directly with a fake clock + recording playback, so every
acceptance criterion (urgency wins, barge-in, dedup, TTL/staleness, cooldown, verbosity) is asserted
deterministically.
"""

from __future__ import annotations

from _voice_support import FakeClock, build_manifest, make_advisory

from tools.ai_sidecar.voice.config import Verbosity, VoiceConfig
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler


def _scheduler(config: VoiceConfig | None = None) -> tuple[Scheduler, RecordingPlayback, FakeClock]:
    clock = FakeClock()
    playback = RecordingPlayback()
    config = config or VoiceConfig()
    sched = Scheduler(Resolver(build_manifest()), playback, config, clock=clock)
    return sched, playback, clock


def test_basic_dispatch() -> None:
    sched, pb, clock = _scheduler()
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))
    spoken = sched.process_pending(clock())
    assert spoken is not None
    assert pb.played[-1].clip_id == "late_brake.act.t03"


def test_highest_urgency_wins_in_a_batch() -> None:
    sched, pb, clock = _scheduler()
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=0))
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=4))
    spoken = sched.process_pending(clock())
    assert spoken is not None and spoken.urgency == "act"
    assert len(pb.played) == 1  # only the winner speaks
    assert pb.played[-1].clip_id == "late_brake.act.t05"


def test_same_rank_tie_break_prefers_freshest_cue() -> None:
    """Equal-urgency batch must pick the later enqueued_at (Qodo #349 / scheduler.py:119)."""
    sched, pb, clock = _scheduler()
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))  # t0 → t03
    clock.advance(0.05)
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=3))  # fresher → t04
    spoken = sched.process_pending(clock())
    assert spoken is not None
    assert spoken.corner == 4  # 1-based corner in Utterance
    assert pb.played[-1].clip_id == "late_brake.act.t04"


def test_act_barges_in_over_lower_urgency_clip() -> None:
    sched, pb, clock = _scheduler()
    # info clip starts playing and is still sounding (current set, not finished)
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=0))
    sched.process_pending(clock())
    assert pb.current is not None and pb.current.urgency == "info"
    # an act cue arrives → barge-in: the info clip is cancelled and act plays
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))
    sched.process_pending(clock())
    assert pb.cancelled and pb.cancelled[-1].urgency == "info"
    assert pb.current is not None and pb.current.urgency == "act"


def test_lower_urgency_does_not_interrupt_busy_channel() -> None:
    sched, pb, clock = _scheduler()
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))
    sched.process_pending(clock())
    assert pb.current is not None and pb.current.urgency == "act"
    before = len(pb.played)
    # an info cue arrives while act is sounding → dropped, never queued/late, never a barge
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=5))
    sched.process_pending(clock())
    assert len(pb.played) == before
    assert not pb.cancelled  # the act was not interrupted by a lower cue


def test_dedup_same_corner_pass_collapses_to_one() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(dedup_window_s=8.0))
    adv = dict(kind="late_brake", urgency="act", corner=2)
    sched.submit(make_advisory(**adv))
    sched.process_pending(clock())
    pb.finish()  # clip done — channel free
    clock.advance(2.0)  # still within the dedup window (same pass)
    sched.submit(make_advisory(**adv))
    spoken = sched.process_pending(clock())
    assert spoken is None  # suppressed as a within-pass repeat
    assert len(pb.played) == 1
    # next pass (well beyond the window) speaks again
    clock.advance(30.0)
    sched.submit(make_advisory(**adv))
    sched.process_pending(clock())
    assert len(pb.played) == 2


def test_fresh_act_for_a_new_corner_is_never_suppressed_by_dedup() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(dedup_window_s=8.0))
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))
    sched.process_pending(clock())
    pb.finish()
    clock.advance(0.5)  # within the dedup window, but a DIFFERENT corner
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=7))
    spoken = sched.process_pending(clock())
    assert spoken is not None
    assert pb.played[-1].clip_id == "late_brake.act.t08"


def test_stale_advisory_is_dropped_by_ttl() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(ttl_s=1.5))
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))  # enqueued at t0
    clock.advance(2.0)  # car is already past the point
    spoken = sched.process_pending(clock())
    assert spoken is None
    assert pb.played == []


def test_fresh_act_is_not_dropped_by_ttl() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(ttl_s=1.5))
    clock.advance(5.0)
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))  # fresh
    spoken = sched.process_pending(clock())
    assert spoken is not None


def test_cooldown_suppresses_same_kind_but_acts_are_exempt() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(cooldown_s={"apex_deficit": 6.0, "late_brake": 1.0}))
    # two info apex cues for different corners within the cooldown → second suppressed
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=0))
    sched.process_pending(clock())
    pb.finish()
    clock.advance(2.0)
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=1))
    assert sched.process_pending(clock()) is None
    # act is exempt: two act cues (different corners) within the late_brake cooldown both speak
    clock.advance(0.1)
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=2))
    sched.process_pending(clock())
    pb.finish()
    clock.advance(0.2)  # < late_brake cooldown of 1.0
    sched.submit(make_advisory(kind="late_brake", urgency="act", corner=3))
    assert sched.process_pending(clock()) is not None


def test_verbosity_low_suppresses_info() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(verbosity=Verbosity.LOW))
    sched.submit(make_advisory(kind="apex_deficit", urgency="info", corner=0))
    assert sched.process_pending(clock()) is None
    sched.submit(make_advisory(kind="apex_deficit", urgency="prepare", corner=0))
    assert sched.process_pending(clock()) is not None


def test_verbosity_off_mutes_all() -> None:
    sched, pb, clock = _scheduler(VoiceConfig(verbosity=Verbosity.OFF))
    for urgency in ("info", "prepare", "act"):
        sched.submit(make_advisory(kind="late_brake", urgency=urgency, corner=2))
        assert sched.process_pending(clock()) is None
    assert pb.played == []


def test_empty_queue_is_a_noop() -> None:
    sched, pb, clock = _scheduler()
    assert sched.process_pending(clock()) is None
    assert pb.played == []
