"""Off-rig tests for the resilient launcher's verdict logic (#624 / #619).

The launcher's value is entirely in *how it decides* an attempt succeeded: the delayed CSP init
livelock lands ~48-90 s AFTER go-live, so a gate that declares success on a few early live reads
(as ``entry_launcher`` does) reports a wedged session as good. These tests pin the sustained-window
semantics against synthetic traces — no Assetto Corsa, no Windows shared memory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.ac_harness.resilient_launch import (
    FREEZE_VERDICTS,
    AttemptOutcome,
    AttemptReadiness,
    LaunchVerdict,
    Sample,
    SectionOwnershipGate,
    StableSessionWatch,
    _Car0NotDrivable,
    _Car0ProbeCleanupError,
    _ensure_acs_gone,
    _ensure_cm_running,
    _hold_rig_until_acs_gone,
    _hold_stable_session,
    _make_process_liveness_probe,
    _make_rig_safe,
    _non_negative_float,
    _OperatorRelease,
    _positive_float,
    _positive_int,
    _probe_car0_drivable,
    _publish_stable_phase,
    _ResettableProcessLivenessProbe,
    _retry_telemetry_cleanup_holds,
    _run_with_safe_release,
    _sample_now,
    _wait_process_exit,
    _watch_live,
    _watched_delivery,
    car0_handshake_failure_outcome,
    classify,
    cycle_delivered,
    run_retry_loop,
)
from tools.ac_harness.shared_memory import SharedMemoryUnavailable


def trace(points: list[tuple[float, int | None, bool]]) -> list[Sample]:
    return [Sample(t=t, gfx_packet=p, acs_alive=a) for t, p, a in points]


def steady(start_t: float, end_t: float, *, first_packet: int, step: float = 1.0) -> list[Sample]:
    """A healthy render trace: packetId advances every sample."""
    out: list[Sample] = []
    packet = first_packet
    t = start_t
    while t <= end_t:
        out.append(Sample(t=t, gfx_packet=packet, acs_alive=True))
        packet += 60
        t += step
    return out


def test_never_live_when_sim_never_renders():
    """acs never maps shared memory / never advances a frame within the go-live budget."""
    samples = trace([(float(t), None, False) for t in range(0, 40, 2)])
    assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.NEVER_LIVE


def test_init_wedge_when_process_up_but_render_never_starts():
    """#630 Part C — acs alive through the whole budget, stream never advances: the init wedge.

    A main thread wedged inside ``accRenderingAdv.dll`` DURING session init never produces a
    packet-advancing sample, so it can never reach the ``FROZE`` branch. Bucketing it as
    ``never_live`` made every freeze rate computed from the ``FROZE`` bucket understate the #627
    init livelock — this is the distinct verdict that fixes the denominator.
    """
    samples = trace([(float(t), 7, True) for t in range(0, 40, 2)])
    assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.WEDGED_INIT


def test_init_wedge_when_process_up_but_section_never_appears():
    """acs alive the whole budget with NO readable shared memory is the same wedge shape."""
    samples = trace([(float(t), None, True) for t in range(0, 40, 2)])
    assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.WEDGED_INIT


def test_process_exit_after_first_appearing_fails_before_go_live_timeout():
    samples = [
        Sample(t=0.0, gfx_packet=None, acs_alive=False),
        Sample(t=1.0, gfx_packet=100, acs_alive=True, entry_ready=False),
        Sample(t=2.0, gfx_packet=None, acs_alive=False),
    ]

    assert classify(samples, go_live_timeout=80.0) is LaunchVerdict.NEVER_LIVE


def test_stable_when_render_advances_through_the_window():
    samples = steady(0.0, 60.0, first_packet=100)
    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.STABLE


def test_delayed_init_freeze_is_caught_not_reported_stable():
    """THE regression this launcher exists for: live first, then wedges mid-window.

    ``entry_launcher``-style logic (success after a few early live reads) would call this a good
    session. The sustained window must call it FROZE.
    """
    samples = steady(0.0, 20.0, first_packet=100)
    frozen_at = samples[-1].gfx_packet
    samples += trace([(float(t), frozen_at, True) for t in range(21, 40)])
    assert classify(samples, go_live_timeout=30.0, stability_window=60.0) is LaunchVerdict.FROZE


def test_short_stall_then_recovery_is_not_a_freeze():
    """A brief hitch (fewer than stall_samples) must not fail an otherwise healthy session."""
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0, held, True), (12.0, held, True)])  # 2 stalled samples < 4
    samples += steady(13.0, 60.0, first_packet=held + 60)
    verdict = classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
    assert verdict is LaunchVerdict.STABLE


def test_unknown_graphics_sample_breaks_the_consecutive_stall_run():
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0, held, True), (12.0, held, True)])
    samples.append(Sample(t=13.0, gfx_packet=None, acs_alive=True, entry_ready=None))
    samples += trace([(14.0, held, True), (15.0, held, True)])
    samples += steady(16.0, 60.0, first_packet=held + 60)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_single_not_ready_flicker_does_not_abort_stability_window():
    samples = steady(0.0, 10.0, first_packet=100)
    samples.append(Sample(t=11.0, gfx_packet=800, acs_alive=True, entry_ready=False))
    samples += steady(12.0, 60.0, first_packet=860)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_unknown_readiness_breaks_the_consecutive_not_ready_run():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += [
        Sample(t=11.0, gfx_packet=800, acs_alive=True, entry_ready=False),
        Sample(t=12.0, gfx_packet=801, acs_alive=True, entry_ready=False),
        Sample(t=13.0, gfx_packet=802, acs_alive=True, entry_ready=None),
        Sample(t=14.0, gfx_packet=803, acs_alive=True, entry_ready=False),
        Sample(t=15.0, gfx_packet=804, acs_alive=True, entry_ready=False),
    ]
    samples += steady(16.0, 60.0, first_packet=860)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_sustained_not_ready_with_an_advancing_stream_is_not_drivable_not_a_freeze():
    """A rendering session that never becomes drivable is AC's pre-drive menu (#466), not a wedge.

    Measured on AG_PC 2026-07-29 at 23.4 h uptime: four consecutive attempts scored ``froze`` at
    14.38/14.40/15.41/14.39 s while the graphics packet advanced ~114/s and physics ~374/s, and a
    screenshot showed AC parked at the Drive/Setup/Exit menu. The #627 wedge REQUIRES a pinned
    graphics packet (§2), so an advancing stream must not land in the freeze bucket.
    """
    samples = steady(0.0, 10.0, first_packet=100)
    samples += [
        Sample(t=11.0 + index, gfx_packet=800 + index, acs_alive=True, entry_ready=False)
        for index in range(4)
    ]

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.NOT_DRIVABLE
    )
    assert LaunchVerdict.NOT_DRIVABLE.value not in FREEZE_VERDICTS


def test_sustained_not_ready_with_a_pinned_stream_is_still_a_freeze():
    """Readiness lost AND the render stream pinned is a genuine wedge — keep it in FROZE.

    The pinned packet must equal the LAST live packet: a real wedge freezes the stream where it
    stood, so there is no advance anywhere inside the not-ready run. (Jumping to a fresh higher
    packet would itself be an advance, i.e. evidence the renderer was still running.)
    """
    samples = steady(0.0, 10.0, first_packet=100)
    pinned = samples[-1].gfx_packet
    samples += [
        Sample(t=11.0 + index, gfx_packet=pinned, acs_alive=True, entry_ready=False)
        for index in range(4)
    ]

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.FROZE
    )


def test_car0_handshake_failure_is_not_drivable_not_a_freeze():
    """The PRODUCTION route for a rendered-but-not-drivable session must match the classifier.

    `main` catches `_Car0NotDrivable` and previously mapped it to FROZE, so real menu-park
    attempts kept landing in FREEZE_VERDICTS even after the pure classifier was fixed
    (Codex P1 on #726). `main` is `pragma: no cover`, so the mapping lives in this helper.
    """
    outcome = car0_handshake_failure_outcome()

    assert outcome.verdict is LaunchVerdict.NOT_DRIVABLE
    assert str(outcome.verdict) not in FREEZE_VERDICTS
    # The session WAS rendering, so CM really started an acs.exe and a cycle was consumed (#710).
    assert outcome.cycle_delivered is True


def test_one_hitch_on_the_threshold_sample_does_not_flip_a_menu_to_froze():
    """The split reads the not-ready RUN's history, not just its final sample (Codex P1 on #726).

    A rendering menu whose graphics packet happens to repeat on exactly the sample that trips the
    not-ready threshold must not be labelled FROZE off that ONE stalled interval — `stall_run`
    would also be only 1. The classifier resolves it by declining to decide on the hitch and
    letting the next advancing sample settle it; `FROZE` stays owned by the independent
    `stall_run >= stall_samples` threshold, which a genuinely pinned stream reaches and an
    intermittently-hitching menu never does.
    """
    samples = steady(0.0, 10.0, first_packet=100)
    samples += [
        Sample(t=11.0 + index, gfx_packet=800 + index, acs_alive=True, entry_ready=False)
        for index in range(3)
    ]
    # 4th not-ready sample repeats the 3rd's packet — a single stalled interval at the boundary.
    samples.append(Sample(t=14.0, gfx_packet=802, acs_alive=True, entry_ready=False))
    # 5th advances again: the renderer was alive all along, so this is the menu, not a wedge.
    samples.append(Sample(t=15.0, gfx_packet=803, acs_alive=True, entry_ready=False))

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.NOT_DRIVABLE
    )


def test_a_menu_that_pins_after_one_advance_still_reaches_froze():
    """The inverse transition: one early advance must not latch a delayed wedge out of FROZE.

    Readiness goes false on an advancing sample and the stream then pins. A latched
    "advanced at some point" flag would return NOT_DRIVABLE forever and undercount #627
    (Codex P1 on #726); the stall threshold must still be able to resolve.
    """
    samples = steady(0.0, 10.0, first_packet=100)
    advancing = samples[-1].gfx_packet + 60
    samples.append(Sample(t=11.0, gfx_packet=advancing, acs_alive=True, entry_ready=False))
    samples += [
        Sample(t=12.0 + index, gfx_packet=advancing, acs_alive=True, entry_ready=False)
        for index in range(5)
    ]

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.FROZE
    )


def steady_phys(
    start_t: float, end_t: float, *, first_packet: int, first_phys: int, step: float = 1.0
) -> list[Sample]:
    """A healthy render trace where BOTH the graphics and physics packets advance."""
    out: list[Sample] = []
    packet, phys, t = first_packet, first_phys, start_t
    while t <= end_t:
        out.append(Sample(t=t, gfx_packet=packet, acs_alive=True, phys_packet=phys))
        packet += 60
        phys += 40
        t += step
    return out


def test_pause_via_physics_stagnation_is_not_a_freeze():
    """#630 Part B — a pause is read from PHYSICS stagnation, not status (which AC leaves LIVE).

    An alt-tab pins the graphics packet AND stops physics; that must not FROZE + taskkill a healthy
    session. A real wedge (physics still advancing) is unaffected — see the next test.
    """
    samples = steady_phys(0.0, 10.0, first_packet=100, first_phys=5000)
    # 12 s paused: gfx pinned, physics pinned (status may still read LIVE, entry_ready False).
    samples += [
        Sample(t=11.0 + i, gfx_packet=760, acs_alive=True, entry_ready=False, phys_packet=5480)
        for i in range(12)
    ]
    # ...then the operator resumes and both streams advance, completing the window.
    samples += steady_phys(24.0, 90.0, first_packet=820, first_phys=5520)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_render_wedge_with_physics_still_advancing_is_froze():
    """The pause carve-out must not weaken real freeze detection: gfx pinned + phys ADVANCING."""
    samples = steady_phys(0.0, 10.0, first_packet=100, first_phys=5000)
    held = samples[-1].gfx_packet
    phys = samples[-1].phys_packet
    # The #627 §2 signature: graphics packet pinned while physics keeps advancing.
    samples += [
        Sample(t=11.0 + i, gfx_packet=held, acs_alive=True, phys_packet=phys + 40 * (i + 1))
        for i in range(5)
    ]

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.FROZE
    )


def test_pause_suspends_the_stability_clock():
    """#630 Part B — paused seconds are not credited toward the window.

    Without suspension, a session that goes live, pauses for longer than the window, then emits one
    resumed frame would satisfy ``t - live_since >= window`` immediately and hand off without a real
    post-resume render window — letting the delayed init wedge land after handoff.
    """
    samples = steady_phys(0.0, 10.0, first_packet=100, first_phys=5000)
    # Paused (physics pinned) from t=11 to t=70 — 60 s, well past the 45 s window.
    samples += [
        Sample(t=11.0 + i, gfx_packet=760, acs_alive=True, entry_ready=False, phys_packet=5480)
        for i in range(60)
    ]
    # One resumed live frame: the window must NOT be satisfied yet (paused time excluded).
    samples.append(Sample(t=71.0, gfx_packet=820, acs_alive=True, phys_packet=5520))

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.PENDING
    )


def test_pause_beyond_budget_falls_back_to_stall_detection():
    """The pause hold is bounded (#637 daemon MEDIUM).

    A hang that pins BOTH streams while acs.exe stays enumerated is indistinguishable from an
    alt-tab at any single instant, so past ``pause_budget`` the hold expires and the ordinary
    stall/not-ready paths must still FROZE the attempt.
    """
    samples = steady_phys(0.0, 10.0, first_packet=100, first_phys=5000)
    # 30 s of dual stagnation against a 10 s pause budget: the hold must expire mid-trace.
    samples += [
        Sample(t=11.0 + i, gfx_packet=760, acs_alive=True, entry_ready=False, phys_packet=5480)
        for i in range(30)
    ]

    assert (
        classify(
            samples,
            go_live_timeout=30.0,
            stability_window=45.0,
            stall_samples=4,
            pause_budget=10.0,
        )
        is LaunchVerdict.FROZE
    )


def test_stable_requires_physics_advancing_past_pause_budget():
    """#637 daemon HIGH — STABLE must never land while physics is still pinned.

    AC can keep the graphics stream animating through a pause/menu; if readiness stays true and
    the pause outlasts ``pause_budget``, the pre-fix code fell through to the ordinary STABLE
    predicate and handed off a session whose physics never resumed (the delayed-init handoff
    #630 Part B exists to prevent). Physics-pinned seconds are never credited and STABLE
    requires physics advancing, so this trace stays PENDING.
    """
    samples = steady_phys(0.0, 10.0, first_packet=100, first_phys=5000)
    # Past the 5 s budget: graphics keeps ANIMATING, physics pinned, still READY.
    samples += [
        Sample(t=11.0 + i, gfx_packet=760 + 60 * i, acs_alive=True, phys_packet=5480)
        for i in range(20)
    ]

    assert (
        classify(
            samples,
            go_live_timeout=30.0,
            stability_window=12.0,
            stall_samples=4,
            pause_budget=5.0,
        )
        is LaunchVerdict.PENDING
    )


def test_streaming_watch_extends_deadline_through_pause(monkeypatch):
    """#637 Codex P1 + daemon HIGH: a pause longer than the spare 30 s must not FROZE at the
    fixed wall-clock deadline — the watcher stretches its budget by the pause hold classify
    reports, so a healthy paused session survives to STABLE after the operator resumes."""
    now = 0.0
    tick = 0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def read_state() -> tuple[int, bool, bool, int]:
        nonlocal tick
        tick += 1
        if tick <= 5:
            return 100 + tick, True, True, 5000 + tick  # live, both streams advancing
        if tick <= 45:
            return 105, False, True, 5005  # 40 s paused: graphics AND physics pinned
        return 105 + (tick - 45), True, True, 5005 + (tick - 45)  # resumed

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    # Budget is 2 + 5 + 30 = 37 s; the 40 s pause outlives it, so without the pause-aware
    # deadline this returns FROZE while the operator is simply alt-tabbed.
    assert (
        _watch_live(
            read_state,
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
        ).verdict
        is LaunchVerdict.STABLE
    )


def test_streaming_watch_freezes_dual_stream_hang_past_pause_budget(monkeypatch):
    """A hang that pins both streams forever is not an infinite pause: once the hold exceeds
    ``pause_budget`` the stall path takes over and FROZEs — the deadline extension is capped."""
    now = 0.0
    tick = 0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def read_state() -> tuple[int, bool, bool, int]:
        nonlocal tick
        tick += 1
        if tick <= 5:
            return 100 + tick, True, True, 5000 + tick
        return 105, True, True, 5005  # hard hang: both pinned, still READY (not a menu)

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    assert (
        _watch_live(
            read_state,
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
            pause_budget=8.0,
        ).verdict
        is LaunchVerdict.FROZE
    )


def test_unfinished_live_trace_is_pending_not_a_terminal_failure():
    samples = steady(0.0, 20.0, first_packet=100)
    assert classify(samples, go_live_timeout=10.0, stability_window=60.0) is LaunchVerdict.PENDING


def test_advancing_pre_drive_menu_is_not_accepted_as_stable():
    samples = [
        Sample(t=float(t), gfx_packet=100 + t, acs_alive=True, entry_ready=False)
        for t in range(0, 61)
    ]
    assert (
        classify(samples, go_live_timeout=30.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE
    )


def test_live_not_in_pit_overlay_without_car0_is_not_accepted_as_stable():
    samples = [
        Sample(
            t=float(t),
            gfx_packet=100 + t,
            acs_alive=True,
            entry_ready=True,
            drivable=False,
        )
        for t in range(0, 61)
    ]
    assert (
        classify(samples, go_live_timeout=30.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE
    )


def test_first_ready_frame_at_go_live_deadline_is_too_late():
    samples = [
        Sample(t=0.0, gfx_packet=100, acs_alive=True, entry_ready=False),
        Sample(t=5.0, gfx_packet=101, acs_alive=True, entry_ready=True),
    ]
    assert classify(samples, go_live_timeout=5.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE


def test_acs_exit_after_go_live_is_froze_not_stable():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += trace([(11.0, None, False)])
    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.FROZE


def test_packet_reset_during_stability_cannot_inherit_prior_session_progress() -> None:
    samples = steady(0.0, 20.0, first_packet=100)
    samples.append(Sample(t=21.0, gfx_packet=1, acs_alive=True))
    samples += steady(22.0, 70.0, first_packet=2)

    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.FROZE


def test_surviving_shared_memory_corpse_does_not_fail_a_healthy_launch() -> None:
    """#628 — a dead session's ``acpmf_*`` section outlives it and must not poison the next verdict.

    Measured on the rig: after ``taskkill /IM acs.exe /F`` the graphics section is still PRESENT
    14 s later, holding the previous session's high packet id. The next launch renders its own
    stream from ~0. Before the fix that read as a regression and a perfectly healthy session was
    discarded as ``never_live`` — burning every retry after the first.
    """
    corpse = trace([(0.0, 23_000, False), (2.0, 23_000, False), (4.0, 23_000, False)])
    fresh = steady(6.0, 60.0, first_packet=5)

    assert classify(corpse + fresh, go_live_timeout=30.0, stability_window=45.0) is (
        LaunchVerdict.STABLE
    )


def test_corpse_reading_does_not_mask_a_genuinely_dead_launch() -> None:
    """The corpse must not manufacture liveness either: no live acs means NEVER_LIVE."""
    corpse = trace([(float(t), 23_000, False) for t in range(0, 40, 2)])

    assert classify(corpse, go_live_timeout=30.0, stability_window=45.0) is (
        LaunchVerdict.NEVER_LIVE
    )


def test_corpse_persisting_into_the_new_acs_lifetime_does_not_fail_the_launch() -> None:
    """#628 — the exact trace measured on the rig, which the ``acs_alive`` guard alone misses.

    The dead session's section stays mapped for ~6 s AFTER the new acs.exe starts: the process is
    alive and loading but has not published its own stream yet, so readings in that window are
    live-correlated *and* stale. Verbatim from ``.scratch/trial_verbose.py``::

        t=0.0  acs=None   gfx=16983   <- corpse
        t=2.0  acs=14020  gfx=16983   <- new acs ALIVE, section still the corpse
        t=4.0  acs=14020  gfx=16983
        t=6.0  acs=14020  gfx=16983
        t=8.0  acs=14020  gfx=121     <- new session finally publishes

    Before the fix this was ``never_live`` at t=8.0 s — a normal, healthy load discarded.
    """
    samples = [Sample(t=0.0, gfx_packet=16_983, acs_alive=False, entry_ready=True, drivable=True)]
    samples += [
        Sample(t=t, gfx_packet=16_983, acs_alive=True, entry_ready=True, drivable=True)
        for t in (2.0, 4.0, 6.0)
    ]
    samples += [Sample(t=8.0, gfx_packet=121, acs_alive=True, entry_ready=True, drivable=True)]
    samples += steady(10.0, 70.0, first_packet=200)

    assert classify(samples, go_live_timeout=80.0, stability_window=45.0) is LaunchVerdict.STABLE


def test_pre_go_live_regression_does_not_bypass_the_go_live_timeout() -> None:
    """Rebasing before go-live must not become an infinite grace period."""
    # A stream that keeps resetting and never advances must still time out. acs.exe was alive
    # through the whole budget without ever advancing its stream, so the timeout buckets as the
    # init wedge (#630 Part C) — the essential property is that it times out at all.
    samples = [
        Sample(t=float(t), gfx_packet=1_000 - t, acs_alive=True, entry_ready=False, drivable=False)
        for t in range(0, 40, 2)
    ]

    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is (
        LaunchVerdict.WEDGED_INIT
    )


class TestSectionOwnershipGate:
    """#628 — readings are trusted only once the packet proves a LIVE writer.

    The shipped launcher failed 6/6 attempts in ~7 s each because the corpse's ``is_live`` flag
    fired the Car0 drivability handshake before AC existed. A corpse packet never advances, so the
    gate needs nothing but the packet stream to tell a corpse from a live owner.
    """

    def test_pinned_corpse_is_never_trusted(self) -> None:
        """A corpse holds one value forever — no advance, no trust."""
        gate = SectionOwnershipGate()
        for _ in range(4):
            assert gate.observe(16_983) is False
        assert gate.publishing is False

    def test_trusted_once_the_new_stream_advances(self) -> None:
        gate = SectionOwnershipGate()
        # Corpse pinned, then the new session publishes its own low, ADVANCING stream.
        gate.observe(16_983)
        gate.observe(16_983)
        assert gate.observe(121) is False  # regression off the corpse
        assert gate.observe(140) is True  # first advance = proven live writer
        assert gate.publishing is True

    def test_packet_regression_revokes_trust(self) -> None:
        """A restart fast enough that no absence was observed must still re-earn trust."""
        gate = SectionOwnershipGate()
        gate.observe(100)
        assert gate.observe(200) is True
        # Session replaced: the new stream restarts low.
        assert gate.observe(5) is False
        assert gate.publishing is False
        # ...and the new generation re-earns trust on its own strictly-increasing stream.
        assert gate.observe(9) is True

    def test_unreadable_sample_neither_grants_nor_revokes_trust(self) -> None:
        gate = SectionOwnershipGate()
        gate.observe(100)
        assert gate.observe(200) is True
        assert gate.observe(None) is True  # a momentary unreadable section does not revoke


class TestAttemptReadiness:
    """#628 — the Car0 cache must be revoked with section ownership, not outlive it."""

    @staticmethod
    def _earn_ownership(readiness: AttemptReadiness) -> None:
        readiness.observe(packet=100, entry_ready=False)
        readiness.observe(packet=200, entry_ready=False)
        assert readiness.publishing is True

    def test_car0_probe_runs_once_per_attempt(self) -> None:
        calls = []
        readiness = AttemptReadiness(lambda: (calls.append(1), True)[1])
        self._earn_ownership(readiness)

        for packet in (300, 400, 500):
            ready, drivable = readiness.observe(packet=packet, entry_ready=True)
            assert (ready, drivable) == (True, True)
        assert len(calls) == 1

    def test_probe_is_not_run_before_ownership_is_earned(self) -> None:
        calls = []
        readiness = AttemptReadiness(lambda: (calls.append(1), True)[1])

        # The corpse reports READY on a pinned packet before AC publishes — the 6/6 froze case.
        assert readiness.observe(packet=16_983, entry_ready=True) == (None, None)
        assert readiness.observe(packet=16_983, entry_ready=True) == (None, None)
        assert calls == []

    def test_packet_regression_revokes_the_car0_cache(self) -> None:
        """A fast restart (packet regression) must re-run the handshake, not inherit the verdict."""
        calls = []
        readiness = AttemptReadiness(lambda: (calls.append(1), True)[1])
        self._earn_ownership(readiness)
        readiness.observe(packet=300, entry_ready=True)
        assert readiness.car0_ready is True
        assert len(calls) == 1

        # Session replaced: the new low stream revokes trust and the cached verdict.
        assert readiness.observe(packet=5, entry_ready=True) == (None, None)
        assert readiness.car0_ready is None

        readiness.observe(packet=9, entry_ready=True)
        assert len(calls) == 2

    def test_not_drivable_raises(self) -> None:
        readiness = AttemptReadiness(lambda: False)
        self._earn_ownership(readiness)

        with pytest.raises(_Car0NotDrivable):
            readiness.observe(packet=300, entry_ready=True)

    def test_cached_verdict_expires_and_reprobes(self) -> None:
        """#630 Part D — the Car0 cache is a TTL, not a one-shot latch.

        A session that renders frames but LOSES drivability after go-live was previously held as
        STABLE forever, because the handshake could never run a second time within the attempt.
        """
        now = [0.0]
        calls = []
        readiness = AttemptReadiness(
            lambda: (calls.append(1), True)[1], reprobe_seconds=45.0, clock=lambda: now[0]
        )
        self._earn_ownership(readiness)

        readiness.observe(packet=300, entry_ready=True)
        assert len(calls) == 1
        now[0] = 44.0
        readiness.observe(packet=400, entry_ready=True)
        assert len(calls) == 1  # inside the TTL: cached
        now[0] = 45.0
        readiness.observe(packet=500, entry_ready=True)
        assert len(calls) == 2  # TTL expired: the handshake re-earns the verdict

    def test_expired_reprobe_failure_fails_the_attempt(self) -> None:
        """Losing drivability mid-window must surface as _Car0NotDrivable, not stay STABLE."""
        now = [0.0]
        verdicts = iter([True, False])
        readiness = AttemptReadiness(
            lambda: next(verdicts), reprobe_seconds=10.0, clock=lambda: now[0]
        )
        self._earn_ownership(readiness)

        ready, drivable = readiness.observe(packet=300, entry_ready=True)
        assert (ready, drivable) == (True, True)
        now[0] = 10.0
        with pytest.raises(_Car0NotDrivable):
            readiness.observe(packet=400, entry_ready=True)

    def test_none_reprobe_seconds_restores_the_one_shot_latch(self) -> None:
        now = [0.0]
        calls = []
        readiness = AttemptReadiness(
            lambda: (calls.append(1), True)[1], reprobe_seconds=None, clock=lambda: now[0]
        )
        self._earn_ownership(readiness)

        readiness.observe(packet=300, entry_ready=True)
        now[0] = 10_000.0
        readiness.observe(packet=400, entry_ready=True)
        assert len(calls) == 1

    def test_regression_resets_the_reprobe_clock_with_the_cache(self) -> None:
        """A new generation must not inherit the old generation's TTL stamp."""
        now = [0.0]
        calls = []
        readiness = AttemptReadiness(
            lambda: (calls.append(1), True)[1], reprobe_seconds=45.0, clock=lambda: now[0]
        )
        self._earn_ownership(readiness)
        readiness.observe(packet=300, entry_ready=True)
        assert len(calls) == 1

        now[0] = 44.0  # inside the TTL — but the session is replaced
        assert readiness.observe(packet=5, entry_ready=True) == (None, None)
        readiness.observe(packet=9, entry_ready=True)
        assert len(calls) == 2  # re-earned by the new generation, stamped at t=44

        now[0] = 88.0
        readiness.observe(packet=20, entry_ready=True)
        assert len(calls) == 2  # 44 s since the NEW stamp < 45 s TTL: cached

    def test_rejects_non_positive_reprobe_seconds(self) -> None:
        with pytest.raises(ValueError, match="reprobe_seconds"):
            AttemptReadiness(lambda: True, reprobe_seconds=0.0)


def test_empty_trace_is_pending():
    assert classify([]) is LaunchVerdict.PENDING


def test_stability_window_is_measured_from_go_live_not_from_launch():
    """A slow-loading session still gets its full stability window."""
    late = trace([(float(t), None, False) for t in range(0, 25, 5)])  # 25 s of loading
    late += steady(25.0, 65.0, first_packet=500)  # live at 25 s, 40 s of steady render
    assert classify(late, go_live_timeout=40.0, stability_window=35.0) is LaunchVerdict.STABLE
    # ...but a 60 s window is not satisfied by only 40 s of post-go-live render
    assert classify(late, go_live_timeout=40.0, stability_window=60.0) is not LaunchVerdict.STABLE


class TestCycleDelivered:
    """#710 — delivery is 'acs.exe was seen alive', never inferred from the verdict."""

    def test_empty_trace_delivered_nothing(self):
        assert cycle_delivered([]) is False

    def test_a_trace_that_never_saw_acs_delivered_no_cycle(self):
        samples = trace([(0.0, None, False), (1.0, None, False), (2.0, None, False)])
        assert classify(samples, go_live_timeout=1.0) is LaunchVerdict.NEVER_LIVE
        assert cycle_delivered(samples) is False

    def test_a_process_that_appeared_and_exited_delivered_a_cycle(self):
        """Same NEVER_LIVE verdict as above, opposite physical outcome — that is the bug."""
        samples = trace([(0.0, None, False), (1.0, 10, True), (2.0, None, False)])
        assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.NEVER_LIVE
        assert cycle_delivered(samples) is True

    def test_a_wedged_init_delivered_a_cycle(self):
        samples = trace([(0.0, 10, True), (1.0, 10, True), (2.0, 10, True)])
        assert classify(samples, go_live_timeout=2.0) is LaunchVerdict.WEDGED_INIT
        assert cycle_delivered(samples) is True

    def test_a_packet_advance_proves_delivery_without_a_process_sighting(self):
        """#710 Codex P1 — the Car0 handshake blocks for up to 5 s, so a process can live and die
        entirely between two ``acs_alive`` reads while still advancing the render packet. Only a
        LIVE writer can move a packet id; a corpse is a frozen snapshot."""
        samples = trace([(0.0, 100, False), (1.0, 101, False), (2.0, 101, False)])
        assert cycle_delivered(samples) is True

    def test_a_packet_regression_proves_delivery(self):
        """#710 Codex P1 round 2 — the corpse-handover shape (#628).

        The dead session's section stays mapped at a high id for ~6 s into the next acs.exe's
        lifetime, so a new generation publishing from ~0 reads as ``16983 -> 121``. A corpse
        never changes on its own, so a DECREASE proves a new writer just as an increase does —
        and requiring a strict increase would miss this trace when the process also died before
        any liveness poll saw it.
        """
        samples = trace([(0.0, 16983, False), (1.0, 121, False), (2.0, 121, False)])
        assert cycle_delivered(samples) is True

    def test_a_pinned_corpse_packet_is_not_delivery(self):
        """The dead session's section stays mapped at a high, UNCHANGING id (#628)."""
        samples = trace([(0.0, 16983, False), (1.0, 16983, False), (2.0, 16983, False)])
        assert cycle_delivered(samples) is False

    def test_a_physics_advance_also_proves_delivery(self):
        samples = [
            Sample(t=0.0, gfx_packet=None, acs_alive=False, phys_packet=500),
            Sample(t=1.0, gfx_packet=None, acs_alive=False, phys_packet=501),
        ]
        assert cycle_delivered(samples) is True


def test_only_pre_launch_failures_may_assert_non_delivery():
    """#710 Codex P1 round 4 — the three-state boundary, stated once.

    `False` is a positive claim that nothing was spawned, and only the paths that return BEFORE
    `actuator.launch()` can make it. A watched trace can prove delivery but never disprove it:
    an acs.exe that starts and dies inside one inter-poll gap before publishing looks exactly
    like a launch that never happened, and recording that as `False` would make the analyzer skip
    a real cycle and shift every later accumulator position.
    """
    proven = trace([(0.0, 10, True), (1.0, 11, True)])
    unproven = trace([(0.0, None, False), (1.0, None, False)])
    assert _watched_delivery(proven) is True
    assert _watched_delivery(unproven) is None  # NOT False
    # The established-non-delivery value still exists — it is just not the sampler's to give.
    assert AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=False).cycle_delivered is False


def test_watch_live_seeds_delivery_from_the_pre_launch_baseline(monkeypatch):
    """#710 Codex P2 — a session that dies before the first sample completes still delivered.

    Without a pre-launch baseline the evidence window opens at the first post-launch sample, so
    every sample reads the dead session's final packet, nothing moves, and the attempt is
    published as `cycle_delivered=False` — silently shifting every later accumulator position.
    """
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    # Corpse sat at 16983 before launch; every sampled reading is the dead new session's 240.
    baseline = Sample(t=0.0, gfx_packet=16983, acs_alive=False)
    outcome = _watch_live(
        lambda: (240, None),
        lambda: False,
        go_live_timeout=2.0,
        stability_window=5.0,
        poll_interval=1.0,
        delivery_baseline=baseline,
    )
    assert outcome == AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=True)


def test_watch_live_without_a_baseline_cannot_see_that_movement(monkeypatch):
    """The same trace, unseeded — pins the value the baseline adds rather than assuming it."""
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    outcome = _watch_live(
        lambda: (240, None),
        lambda: False,
        go_live_timeout=2.0,
        stability_window=5.0,
        poll_interval=1.0,
    )
    # UNKNOWN, not False: a watched trace can only prove delivery, never disprove it (#710
    # Codex P1 round 4). Without the baseline the movement is simply invisible.
    assert outcome == AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=None)


def test_watch_live_reports_delivery_alongside_the_verdict(monkeypatch):
    """#710 — the rig path derives delivery from the trace it already collected."""
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    outcome = _watch_live(
        lambda: (None, None),
        lambda: False,  # acs.exe never appears
        go_live_timeout=2.0,
        stability_window=5.0,
        poll_interval=1.0,
    )
    # A watched trace with no positive evidence is UNKNOWN. Only the pre-launch failure paths
    # (CM absent / launch() raised) may assert non-delivery (#710 Codex P1 round 4).
    assert outcome == AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=None)


class TestRetryLoop:
    def test_stops_on_first_stable_and_counts_attempts(self):
        verdicts = [LaunchVerdict.FROZE, LaunchVerdict.FROZE, LaunchVerdict.STABLE]
        report = run_retry_loop(lambda i: verdicts[i - 1], max_attempts=10)
        assert report.succeeded
        assert (report.attempts, report.froze, report.never_live) == (3, 2, 0)

    def test_exhausts_budget_and_reports_failure_honestly(self):
        report = run_retry_loop(lambda i: LaunchVerdict.FROZE, max_attempts=4)
        assert not report.succeeded
        assert report.attempts == 4 and report.froze == 4
        assert report.verdict is LaunchVerdict.FROZE
        assert "reboot" in report.summary()

    def test_never_live_dominance_keeps_launch_delivery_remediation(self):
        """One menu park must not hide a run dominated by launches that never reached AC."""
        seq = [
            LaunchVerdict.NOT_DRIVABLE,
            LaunchVerdict.NEVER_LIVE,
            LaunchVerdict.NEVER_LIVE,
            LaunchVerdict.NEVER_LIVE,
        ]
        report = run_retry_loop(lambda i: seq[i - 1], max_attempts=len(seq))

        assert "AC rendered but never became drivable" not in report.summary()
        assert "cold-restart Content Manager" in report.summary()

    def test_cold_restarts_cm_after_consecutive_never_live(self):
        """Repeated never_live means a stale CM ignoring the preset URL (#537/#558) — restart it."""
        calls: list[int] = []
        run_retry_loop(
            lambda i: LaunchVerdict.NEVER_LIVE,
            max_attempts=4,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert len(calls) == 2  # fires on attempts 2 and 4, streak resets between

    def test_freeze_breaks_the_never_live_streak(self):
        """A FROZE verdict proves CM is not stale, so it must reset the restart counter."""
        seq = [LaunchVerdict.NEVER_LIVE, LaunchVerdict.FROZE, LaunchVerdict.NEVER_LIVE]
        calls: list[int] = []
        run_retry_loop(
            lambda i: seq[i - 1],
            max_attempts=3,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert calls == []

    def test_rejects_pending_attempt_result(self):
        with pytest.raises(ValueError, match="non-terminal"):
            run_retry_loop(lambda _: LaunchVerdict.PENDING, max_attempts=1)

    def test_init_wedge_breaks_the_never_live_streak(self):
        """#630 Part C — WEDGED_INIT proves CM delivered an acs.exe; restarting CM is wrong."""
        seq = [LaunchVerdict.NEVER_LIVE, LaunchVerdict.WEDGED_INIT, LaunchVerdict.NEVER_LIVE]
        calls: list[int] = []
        run_retry_loop(
            lambda i: seq[i - 1],
            max_attempts=3,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert calls == []

    def test_init_wedge_is_counted_in_its_own_bucket(self):
        seq = [LaunchVerdict.WEDGED_INIT, LaunchVerdict.FROZE, LaunchVerdict.STABLE]
        report = run_retry_loop(lambda i: seq[i - 1], max_attempts=5)
        assert report.succeeded
        assert (report.froze, report.wedged_init, report.never_live, report.stable) == (1, 1, 0, 1)
        assert "wedged_init 1" in report.summary()

    def test_every_attempt_is_recorded_with_verdict_and_uptime(self):
        """#630 Part E / #627 §9.2 — verdict + uptime + launch index for EVERY trial."""
        seq = [LaunchVerdict.FROZE, LaunchVerdict.STABLE]
        clock = iter([10.0, 15.5, 20.0, 26.25])  # start/end per attempt
        uptimes = iter([2.1, 2.2])
        report = run_retry_loop(
            lambda i: seq[i - 1],
            max_attempts=5,
            clock=lambda: next(clock),
            wall_clock=lambda: 1_700_000_000.0,
            uptime_hours=lambda: next(uptimes),
        )
        assert [record.attempt for record in report.attempts_log] == [1, 2]
        assert [record.verdict for record in report.attempts_log] == seq
        assert [record.elapsed_s for record in report.attempts_log] == [5.5, 6.25]
        assert [record.uptime_h for record in report.attempts_log] == [2.1, 2.2]
        assert all("T" in record.started_at_utc for record in report.attempts_log)

    def test_trials_mode_runs_every_attempt_past_a_stable(self):
        """stop_on_stable=False is the #627 §9.2 rate-measurement mode: a full denominator."""
        seq = [
            LaunchVerdict.STABLE,
            LaunchVerdict.FROZE,
            LaunchVerdict.STABLE,
            LaunchVerdict.WEDGED_INIT,
        ]
        report = run_retry_loop(lambda i: seq[i - 1], max_attempts=4, stop_on_stable=False)
        assert report.attempts == 4
        assert (report.stable, report.froze, report.wedged_init) == (2, 1, 1)
        assert len(report.attempts_log) == 4
        # The report verdict is the LAST verdict; "succeeded" is not the point of a measurement.
        assert report.verdict is LaunchVerdict.WEDGED_INIT

    def test_report_as_dict_is_json_serializable(self):
        import json as json_module

        report = run_retry_loop(
            lambda i: LaunchVerdict.STABLE, max_attempts=1, uptime_hours=lambda: None
        )
        payload = json_module.loads(json_module.dumps(report.as_dict()))
        assert payload["schema"] == "resilient-launch-report/v4"
        assert payload["verdict"] == "stable"
        assert payload["counts"] == {
            "stable": 1,
            "froze": 0,
            "wedged_init": 0,
            "not_drivable": 0,
            "never_live": 0,
        }
        assert payload["cycles"] == {"delivered": 1, "undelivered": 0, "undetermined": 0}
        assert payload["attempts_log"][0]["attempt"] == 1
        assert payload["attempts_log"][0]["uptime_h"] is None
        assert payload["attempts_log"][0]["cycle_delivered"] is True

    def test_report_as_dict_includes_launch_provenance(self):
        """#657 Qodo — observable ``launch`` field must stay covered by tests."""
        from tools.ac_harness.resilient_launch import LaunchReport, LaunchVerdict

        launch = {
            "car": "ks_porsche_911_gt3_r_2016",
            "track": "spa",
            "layout": None,
            "stability_window": 140.0,
            "go_live_timeout": 80.0,
            "trials_per_invocation": 1,
        }
        report = LaunchReport(
            verdict=LaunchVerdict.STABLE,
            attempts=1,
            froze=0,
            never_live=0,
            stable=1,
            launch=launch,
        )
        payload = report.as_dict()
        assert payload["launch"] == launch
        assert (
            "launch"
            not in LaunchReport(
                verdict=LaunchVerdict.STABLE,
                attempts=1,
                froze=0,
                never_live=0,
                stable=1,
            ).as_dict()
        )

    def test_bare_verdict_leaves_never_live_delivery_undetermined(self):
        """#710 — a caller returning a bare verdict supplies no delivery evidence.

        Every other verdict implies a live acs.exe and is derivable; ``never_live`` is exactly
        the ambiguous one, so it must stay UNKNOWN rather than be guessed either way.
        """
        seq = [LaunchVerdict.NEVER_LIVE, LaunchVerdict.WEDGED_INIT, LaunchVerdict.STABLE]
        report = run_retry_loop(lambda i: seq[i - 1], max_attempts=3)
        assert [record.cycle_delivered for record in report.attempts_log] == [None, True, True]
        assert (report.cycles_delivered, report.cycles_undelivered) == (2, 0)
        assert report.cycles_undetermined == 1

    def test_never_live_records_which_of_its_two_shapes_it_was(self):
        """#710 — the whole point: 'never spawned' and 'appeared then exited' stop sharing a row."""
        outcomes = [
            AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=False),
            AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=True),
            AttemptOutcome(LaunchVerdict.STABLE, cycle_delivered=True),
        ]
        report = run_retry_loop(lambda i: outcomes[i - 1], max_attempts=3)
        assert [record.cycle_delivered for record in report.attempts_log] == [False, True, True]
        assert report.never_live == 2
        # Two never_live rows, but only ONE of them failed to reach AC.
        assert (report.cycles_delivered, report.cycles_undelivered) == (2, 1)
        payload = report.as_dict()
        assert payload["cycles"] == {"delivered": 2, "undelivered": 1, "undetermined": 0}
        assert [row["cycle_delivered"] for row in payload["attempts_log"]] == [False, True, True]

    def test_delivered_never_live_still_advances_the_cm_restart_streak(self):
        """Recorded delivery must NOT shorten the #537/#558 streak (#710 Codex P1).

        A delivered never_live also covers a session that rendered but never reached readiness —
        the stale cached-session / pre-drive-overlay failure whose proven recovery IS this cold
        restart. Delivery proves AC started, not that CM honored the requested preset.
        """
        outcomes = [AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=True)] * 2
        calls: list[int] = []
        run_retry_loop(
            lambda i: outcomes[i - 1],
            max_attempts=2,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert calls == [1]

    def test_undelivered_never_live_still_cold_restarts_cm(self):
        outcomes = [AttemptOutcome(LaunchVerdict.NEVER_LIVE, cycle_delivered=False)] * 2
        calls: list[int] = []
        run_retry_loop(
            lambda i: outcomes[i - 1],
            max_attempts=2,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert calls == [1]

    @pytest.mark.parametrize("delivery", [False, None])
    def test_rejects_a_live_verdict_without_a_delivered_cycle(self, delivery):
        """A FROZE/STABLE/WEDGED_INIT verdict is only reachable through a live acs.exe.

        ``None`` must be rejected too: `_parse_report` requires ``True`` for every non-never_live
        verdict, so accepting it here would let the producer emit a report its own analyzer
        considers internally invalid (#710 Codex P2).
        """
        with pytest.raises(ValueError, match="requires a live acs.exe"):
            run_retry_loop(
                lambda _: AttemptOutcome(LaunchVerdict.FROZE, cycle_delivered=delivery),
                max_attempts=1,
            )

    def test_uptime_reader_failure_does_not_fail_the_attempt(self):
        def boom() -> float:
            raise OSError("GetTickCount64 unavailable")

        report = run_retry_loop(lambda i: LaunchVerdict.STABLE, max_attempts=1, uptime_hours=boom)
        assert report.succeeded
        assert report.attempts_log[0].uptime_h is None


@pytest.mark.parametrize("stall_samples", [2, 3, 5])
def test_stall_threshold_is_honored(stall_samples: int):
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0 + i, held, True) for i in range(stall_samples)])
    verdict = classify(
        samples, go_live_timeout=30.0, stability_window=120.0, stall_samples=stall_samples
    )
    assert verdict is LaunchVerdict.FROZE


def test_streaming_watch_survives_go_live_timeout_until_stability(monkeypatch):
    now = 0.0
    packet = 100

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def read_state() -> tuple[int, bool]:
        nonlocal packet
        packet += 1
        return packet, True

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    assert (
        _watch_live(
            read_state,
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
        ).verdict
        is LaunchVerdict.STABLE
    )


def test_sample_timestamp_follows_blocking_readiness_work(monkeypatch):
    now = 10.0
    observations: list[tuple[str, float]] = []

    def monotonic() -> float:
        return now

    def acs_alive() -> bool:
        observations.append(("alive", now))
        return True

    def read_state() -> tuple[int, bool, bool]:
        nonlocal now
        observations.append(("state", now))
        now += 5.0
        return 101, True, True

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)

    sample = _sample_now(read_state, acs_alive)

    assert sample.t == 15.0
    assert sample.acs_alive is True
    assert observations == [("state", 10.0), ("alive", 15.0)]
    assert now == 15.0


def test_blocking_readiness_probe_consumes_go_live_budget() -> None:
    samples = [
        Sample(t=15.0, gfx_packet=1, acs_alive=True, entry_ready=True, drivable=True),
        Sample(t=16.0, gfx_packet=2, acs_alive=True, entry_ready=True, drivable=True),
    ]

    assert (
        classify(
            samples,
            go_live_timeout=4.0,
            stability_window=20.0,
            started_at=10.0,
        )
        is LaunchVerdict.NEVER_LIVE
    )


def test_process_liveness_probe_fails_closed_and_confirms_absence() -> None:
    observations = iter(
        [
            OSError("snapshot failed"),
            (),
            (),
            (42,),
            (),
            (),
        ]
    )

    def process_ids(_image: str) -> tuple[int, ...]:
        observation = next(observations)
        if isinstance(observation, OSError):
            raise observation
        return observation

    alive = _make_process_liveness_probe("acs.exe", process_ids=process_ids)

    assert [alive() for _ in range(6)] == [False, False, False, True, True, False]


def test_process_liveness_probe_fails_closed_after_real_sighting() -> None:
    observations = iter([(42,), OSError("snapshot failed"), (), ()])

    def process_ids(_image: str) -> tuple[int, ...]:
        observation = next(observations)
        if isinstance(observation, OSError):
            raise observation
        return observation

    alive = _make_process_liveness_probe("acs.exe", process_ids=process_ids)

    assert [alive() for _ in range(4)] == [True, True, True, False]


def test_process_liveness_probe_does_not_invent_presence_before_first_sighting() -> None:
    observations = iter([(), (), (42,), (), ()])
    alive = _make_process_liveness_probe(
        "acs.exe",
        process_ids=lambda _image: next(observations),
    )

    assert [alive() for _ in range(5)] == [False, False, True, True, False]


def test_process_liveness_history_resets_between_launch_attempts() -> None:
    observations = iter([(42,), (), (), (), (), (84,)])
    alive = _ResettableProcessLivenessProbe(
        "acs.exe",
        process_ids=lambda _image: next(observations),
    )

    assert [alive() for _ in range(3)] == [True, True, False]
    alive.reset()
    assert [alive() for _ in range(3)] == [False, False, True]


def test_process_liveness_probe_rejects_invalid_confirmation_count() -> None:
    with pytest.raises(ValueError, match="absent_confirmations"):
        _make_process_liveness_probe("acs.exe", absent_confirmations=0)


def test_streaming_watch_waits_through_short_hitch(monkeypatch):
    now = 0.0
    packets = iter([100, 101, 102, 102, 102, 103, 104, 105, 106, 107])

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    assert (
        _watch_live(
            lambda: (next(packets), True),
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
        ).verdict
        is LaunchVerdict.STABLE
    )


def test_wait_process_exit_rejects_lingering_killed_process(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    monkeypatch.setattr("tools.ac_harness.resilient_launch._process_running", lambda _image: True)

    assert _wait_process_exit("Content Manager.exe", timeout=1.0, poll=0.25) is False
    assert now == 1.0


def test_wait_process_exit_clamps_sleep_to_deadline(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    monkeypatch.setattr("tools.ac_harness.resilient_launch._process_running", lambda _image: True)

    assert _wait_process_exit("Content Manager.exe", timeout=1.0, poll=0.6) is False
    assert now == 1.0


def test_wait_process_exit_honors_release_before_process_probe(monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._process_running",
        lambda _image: pytest.fail("release must be checked before the process probe"),
    )

    with pytest.raises(_OperatorRelease):
        _wait_process_exit("Content Manager.exe", release_requested=lambda: True)


@pytest.mark.parametrize(
    ("parser", "value", "message"),
    [
        (_positive_float, "0", "finite and > 0"),
        (_positive_float, "-1", "finite and > 0"),
        (_positive_int, "0", "must be > 0"),
        (_positive_int, "-2", "must be > 0"),
    ],
)
def test_positive_cli_types_reject_non_positive(parser, value, message):
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        parser(value)


def test_rig_lock_timeout_cli_type_rejects_negative():
    with pytest.raises(argparse.ArgumentTypeError, match="finite and >= 0"):
        _non_negative_float("-0.1")


class TestResolveReportPath:
    """#646 review — the --json destination must stay inside an approved output root."""

    def test_path_inside_an_approved_root_is_accepted(self, tmp_path) -> None:
        from tools.ac_harness.resilient_launch import _resolve_report_path

        target = tmp_path / "reports" / "run.json"
        resolved = _resolve_report_path(target, approved_roots=(tmp_path,))
        assert resolved == target.resolve()

    def test_absolute_path_outside_every_root_is_rejected(self, tmp_path) -> None:
        from tools.ac_harness.resilient_launch import _resolve_report_path

        outside = tmp_path / "outside" / "run.json"
        approved = tmp_path / "approved"
        with pytest.raises(ValueError, match="approved output root"):
            _resolve_report_path(outside, approved_roots=(approved,))

    def test_dotdot_traversal_cannot_escape_the_root(self, tmp_path) -> None:
        from tools.ac_harness.resilient_launch import _resolve_report_path

        approved = tmp_path / "approved"
        sneaky = approved / ".." / "escaped.json"
        with pytest.raises(ValueError, match="approved output root"):
            _resolve_report_path(sneaky, approved_roots=(approved,))

    def test_relative_path_resolves_against_cwd(self, tmp_path, monkeypatch) -> None:
        from tools.ac_harness.resilient_launch import _resolve_report_path

        monkeypatch.chdir(tmp_path)
        resolved = _resolve_report_path(Path(".scratch/run.json"), approved_roots=(tmp_path,))
        assert resolved == (tmp_path / ".scratch" / "run.json").resolve()

    def test_relative_path_from_an_unapproved_cwd_is_rejected(self, tmp_path, monkeypatch) -> None:
        """#646 review round 2 — the caller's CWD is not a root: cd-ing to Downloads and passing
        a bare filename must not become a write there."""
        from tools.ac_harness.resilient_launch import _resolve_report_path

        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        monkeypatch.chdir(downloads)
        with pytest.raises(ValueError, match="approved output root"):
            _resolve_report_path(Path("report.json"), approved_roots=(tmp_path / "approved",))

    def test_scratch_root_is_the_module_checkouts_scratch_dir(self) -> None:
        from tools.ac_harness.resilient_launch import _scratch_root

        root = _scratch_root()
        assert root.name == ".scratch"
        assert (root.parent / "tools" / "ac_harness" / "resilient_launch.py").is_file()

    def test_source_files_are_outside_the_scratch_root(self) -> None:
        """--json <checkout>/tools/.../resilient_launch.py must NOT validate (#647 round 3)."""
        from tools.ac_harness.resilient_launch import _resolve_report_path, _scratch_root

        source = _scratch_root().parent / "tools" / "ac_harness" / "resilient_launch.py"
        with pytest.raises(ValueError, match="approved output root"):
            _resolve_report_path(source, approved_roots=(_scratch_root(),))


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_float_cli_types_reject_non_finite(value):
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        _positive_float(value)
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        _non_negative_float(value)


def test_ensure_acs_gone_kills_the_full_process_tree(monkeypatch):
    calls: list[list[str]] = []
    alive = iter([True, False, False])

    monkeypatch.setattr("tools.ac_harness.entry_launcher.sys.platform", "win32")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **_kwargs: (
            calls.append(command) or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )
    assert _ensure_acs_gone(lambda: next(alive)) is True
    assert calls == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]


def test_ensure_acs_gone_returns_false_when_process_survives(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.entry_launcher.sys.platform", "win32")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert _ensure_acs_gone(lambda: True, timeout=1.0, poll=0.25) is False
    assert now == 1.0


def test_ensure_acs_gone_does_not_treat_enumeration_failure_as_absence(monkeypatch):
    now = 0.0
    taskkills: list[list[str]] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.entry_launcher.sys.platform", "win32")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **_kwargs: (
            taskkills.append(command) or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _ensure_acs_gone(
            lambda: (_ for _ in ()).throw(OSError("snapshot failed")),
            timeout=1.0,
            poll=0.25,
        )
        is False
    )
    assert taskkills == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]
    assert now == 1.0


def test_cleanup_failure_holds_ownership_until_acs_is_gone(monkeypatch):
    cleanup_results = iter([False, False, True])
    alive_results = iter([True, True, True, False])
    cleanup_calls: list[int] = []
    sleeps: list[float] = []

    def retry_cleanup(_acs_alive):
        cleanup_calls.append(1)
        return next(cleanup_results)

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    _hold_rig_until_acs_gone(
        lambda: next(alive_results),
        retry_cleanup=retry_cleanup,
        poll=0.25,
    )

    assert len(cleanup_calls) == 3
    assert sleeps == [0.25, 0.25]


def test_cleanup_hold_rechecks_liveness_after_reported_success(monkeypatch):
    alive_results = iter([True, True, True, False])
    cleanup_calls: list[int] = []
    sleeps: list[float] = []

    def retry_cleanup(_acs_alive) -> bool:
        cleanup_calls.append(1)
        return True

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    _hold_rig_until_acs_gone(
        lambda: next(alive_results),
        retry_cleanup=retry_cleanup,
        poll=0.25,
    )

    assert len(cleanup_calls) == 2
    assert sleeps == [0.25]


def test_cleanup_hold_allows_only_explicit_operator_release(monkeypatch):
    def interrupt(_acs_alive):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep",
        lambda _seconds: pytest.fail("interrupt must release before sleeping"),
    )

    _hold_rig_until_acs_gone(lambda: True, retry_cleanup=interrupt)


def test_fatal_cleanup_hold_ignores_interrupt_until_acs_is_gone(monkeypatch):
    cleanup_calls = iter([KeyboardInterrupt(), True])
    alive_results = iter([True, True, False])

    def cleanup(_acs_alive):
        result = next(cleanup_calls)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", lambda _seconds: None)

    _hold_rig_until_acs_gone(
        lambda: next(alive_results),
        retry_cleanup=cleanup,
        allow_operator_release=False,
    )


def test_fatal_cleanup_hold_ignores_release_but_still_runs_cleanup(monkeypatch):
    alive_results = iter([True, False])
    forwarded_release: list[object] = []
    sleeps: list[float] = []

    def cleanup(_acs_alive, *, release_requested=None):
        forwarded_release.append(release_requested)
        return True

    monkeypatch.setattr("tools.ac_harness.resilient_launch._ensure_acs_gone", cleanup)
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    assert (
        _hold_rig_until_acs_gone(
            lambda: next(alive_results),
            release_requested=lambda: True,
            allow_operator_release=False,
            poll=0.25,
        )
        is True
    )
    assert forwarded_release == [None]
    assert sleeps == []


def test_fatal_cleanup_hold_bounds_repeated_enumeration_failures(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _hold_rig_until_acs_gone(
            lambda: (_ for _ in ()).throw(OSError("snapshot failed")),
            retry_cleanup=lambda _acs_alive: False,
            allow_operator_release=False,
            poll=0.25,
            timeout=1.0,
        )
        is False
    )
    assert now == 1.0


def test_cleanup_hold_honors_game_point_release_signal() -> None:
    _hold_rig_until_acs_gone(
        lambda: True,
        retry_cleanup=lambda _acs_alive: pytest.fail("release must precede another cleanup"),
        release_requested=lambda: True,
    )


def test_cleanup_hold_forwards_release_to_default_cleanup(monkeypatch) -> None:
    callbacks: list[object] = []

    def release_requested() -> bool:
        return False

    def cleanup(_acs_alive, *, release_requested=None):
        callbacks.append(release_requested)
        raise _OperatorRelease

    monkeypatch.setattr("tools.ac_harness.resilient_launch._ensure_acs_gone", cleanup)

    _hold_rig_until_acs_gone(
        lambda: True,
        release_requested=release_requested,
    )

    assert callbacks == [release_requested]


def test_stable_session_exit_without_release_is_failure() -> None:
    assert _hold_stable_session(lambda: False, lambda: False) is False


def test_stable_session_release_is_success() -> None:
    assert _hold_stable_session(lambda: True, lambda: True) is True


def test_stable_session_retries_retained_telemetry_until_released(monkeypatch) -> None:
    from tools.ac_harness.custom_ai import ControllerTelemetryCloseError

    class Controller:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls < 5:
                raise ControllerTelemetryCloseError("read mapping still busy")

    controller = Controller()
    retained: list[object] = [controller]
    alive = iter((True, True, False))
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", lambda _seconds: None)

    assert (
        _hold_stable_session(
            lambda: next(alive),
            lambda: False,
            maintenance=lambda: _retry_telemetry_cleanup_holds(retained),
        )
        is False
    )
    assert retained == []
    assert controller.close_calls == 5


def test_stable_phase_publication_failure_keeps_proven_session_available(capsys) -> None:
    phases: list[str] = []

    def fail_publish(phase: str) -> None:
        phases.append(phase)
        raise OSError("owner metadata unavailable")

    assert _publish_stable_phase(fail_publish) is False
    assert phases == ["stable"]
    assert (
        "retaining the proven live session under stabilizing ownership" in capsys.readouterr().out
    )


def test_abnormal_retry_exit_makes_rig_safe_before_propagating(monkeypatch):
    calls: list[str] = []

    def fail() -> object:
        calls.append("run")
        raise RuntimeError("watch failed")

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._make_rig_safe",
        lambda _acs_alive, **_kwargs: calls.append("safe"),
    )

    with pytest.raises(RuntimeError, match="watch failed"):
        _run_with_safe_release(fail, lambda: True)

    assert calls == ["run", "safe"]


def test_pre_stable_operator_release_makes_rig_safe_before_propagating(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def release_requested() -> bool:
        return True

    def release() -> object:
        calls.append(("run", {}))
        raise _OperatorRelease

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._make_rig_safe",
        lambda _acs_alive, **kwargs: calls.append(("safe", kwargs)),
    )

    with pytest.raises(_OperatorRelease):
        _run_with_safe_release(release, lambda: True, release_requested=release_requested)

    # Cleanup is attempted first; the durable signal remains Game Point's no-console escape hatch.
    assert calls == [
        ("run", {}),
        ("safe", {"release_requested": release_requested}),
    ]


def test_make_rig_safe_attempts_cleanup_before_honoring_release(monkeypatch):
    callbacks: list[object] = []
    held_with: list[object] = []

    def release_requested() -> bool:
        return True

    def cleanup(_acs_alive, *, release_requested=None, graceful_grace=0.0):
        callbacks.append(release_requested)
        return False

    monkeypatch.setattr("tools.ac_harness.resilient_launch._ensure_acs_gone", cleanup)
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._hold_rig_until_acs_gone",
        lambda _acs_alive, *, release_requested=None, allow_operator_release=True, timeout=None: (
            held_with.append((release_requested, allow_operator_release, timeout))
        ),
    )

    _make_rig_safe(lambda: True, release_requested=release_requested)

    assert callbacks == [None]
    assert held_with == [(release_requested, True, None)]


def test_car0_probe_closes_controller_after_handshake(monkeypatch):
    reads = iter([None] * 12 + [{"packet_id": 1}])
    closed: list[bool] = []
    now = 0.0

    class Controller:
        def read_car_data(self):
            return next(reads)

        def close(self):
            closed.append(True)

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _probe_car0_drivable(
            poll=0.1,
            controller_factory=Controller,
        )
        is True
    )
    assert closed == [True]
    assert now > 1.0


def test_car0_probe_performs_final_read_at_timeout_boundary(monkeypatch) -> None:
    now = 0.0
    reads = iter([None, {"packet_id": 1}])

    class Controller:
        def read_car_data(self):
            return next(reads)

        def close(self) -> None:
            pass

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.monotonic",
        lambda: now,
    )
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _probe_car0_drivable(
            timeout=0.1,
            poll=0.1,
            controller_factory=Controller,
        )
        is True
    )


def test_car0_probe_mapping_failure_waits_out_the_injection_race(monkeypatch) -> None:
    now = 0.0

    def fail_controller() -> object:
        raise SharedMemoryUnavailable("mapping unavailable")

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.monotonic",
        lambda: now,
    )
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert _probe_car0_drivable(timeout=5.0, controller_factory=fail_controller) is False
    assert now == pytest.approx(5.0)


def test_car0_probe_honors_release_during_handshake(monkeypatch) -> None:
    release_checks = iter([False, False, True])
    closed: list[bool] = []

    class Controller:
        def read_car_data(self):
            return None

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep",
        lambda _seconds: pytest.fail("release must interrupt before another probe sleep"),
    )

    with pytest.raises(_OperatorRelease):
        _probe_car0_drivable(
            controller_factory=Controller,
            release_requested=lambda: next(release_checks),
        )

    assert closed == [True]


def test_car0_failure_verdict_does_not_restart_content_manager() -> None:
    restarts: list[bool] = []

    report = run_retry_loop(
        lambda _attempt: LaunchVerdict.FROZE,
        max_attempts=2,
        on_never_live_streak=lambda: restarts.append(True),
        never_live_before_restart=2,
    )

    assert report.verdict is LaunchVerdict.FROZE
    assert restarts == []


def test_car0_probe_close_failure_aborts_before_another_probe() -> None:
    class Controller:
        def __init__(self) -> None:
            self.close_calls = 0

        def read_car_data(self):
            return {"packet_id": 1}

        def close(self):
            self.close_calls += 1
            raise OSError("unmap failed")

    with pytest.raises(_Car0ProbeCleanupError, match="could not close") as caught:
        _probe_car0_drivable(controller_factory=Controller)

    assert isinstance(caught.value.controller, Controller)
    assert caught.value.controller.close_calls == 3


def test_car0_probe_close_interrupt_retains_controller_for_fatal_cleanup() -> None:
    class Controller:
        def read_car_data(self):
            return {"packet_id": 1}

        def close(self):
            raise KeyboardInterrupt

    with pytest.raises(_Car0ProbeCleanupError, match="control ownership unknown") as caught:
        _probe_car0_drivable(controller_factory=Controller)

    assert isinstance(caught.value.controller, Controller)
    assert isinstance(caught.value.__cause__, KeyboardInterrupt)


def test_car0_probe_retries_transient_close_failure() -> None:
    class Controller:
        def __init__(self) -> None:
            self.close_calls = 0

        def read_car_data(self):
            return {"packet_id": 1}

        def close(self):
            self.close_calls += 1
            if self.close_calls < 3:
                raise OSError("unmap temporarily failed")

    controller = Controller()

    assert _probe_car0_drivable(controller_factory=lambda: controller) is True
    assert controller.close_calls == 3


def test_car0_probe_does_not_kill_session_for_read_only_mapping_leak(capsys) -> None:
    from tools.ac_harness.custom_ai import ControllerTelemetryCloseError

    class Controller:
        def read_car_data(self):
            return {"packet_id": 1}

        def close(self):
            raise ControllerTelemetryCloseError("CarControls already released")

    retained: list[object] = []

    assert (
        _probe_car0_drivable(
            controller_factory=Controller,
            retain_telemetry_controller=retained.append,
        )
        is True
    )
    assert len(retained) == 1
    assert "retained a read-only telemetry mapping" in capsys.readouterr().out


def test_retained_read_only_mapping_is_retried_until_released() -> None:
    class Controller:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            if self.close_calls < 5:
                from tools.ac_harness.custom_ai import ControllerTelemetryCloseError

                raise ControllerTelemetryCloseError("read mapping still busy")

    controller = Controller()
    retained: list[object] = [controller]

    _retry_telemetry_cleanup_holds(retained)
    assert retained == [controller]
    assert controller.close_calls == 3

    _retry_telemetry_cleanup_holds(retained)
    assert retained == []
    assert controller.close_calls == 5


def test_ensure_cm_running_fails_before_same_named_process_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._strict_process_running",
        lambda _image: pytest.fail("a running image cannot validate a missing configured path"),
    )

    assert _ensure_cm_running(tmp_path / "missing.exe") is False


def test_ensure_cm_running_probes_the_configured_image_name(tmp_path, monkeypatch):
    images: list[str] = []
    cm_exe = tmp_path / "PortableCM.exe"
    cm_exe.touch()

    def running(image: str) -> bool:
        images.append(image)
        return True

    monkeypatch.setattr("tools.ac_harness.resilient_launch._strict_process_running", running)

    assert _ensure_cm_running(cm_exe) is True
    assert images == ["PortableCM.exe"]


def test_ensure_cm_running_honors_release_before_process_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._strict_process_running",
        lambda _image: pytest.fail("release must be checked before probing or starting CM"),
    )

    with pytest.raises(_OperatorRelease):
        _ensure_cm_running(tmp_path / "Content Manager.exe", release_requested=lambda: True)


def test_ensure_cm_running_fails_on_unknown_process_state(tmp_path, monkeypatch):
    cm_exe = tmp_path / "Content Manager.exe"
    cm_exe.touch()
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._strict_process_running",
        lambda _image: (_ for _ in ()).throw(OSError("snapshot failed")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda _args: pytest.fail("unknown process state must not start a duplicate CM"),
    )

    assert _ensure_cm_running(cm_exe) is False


def test_ensure_cm_running_rechecks_presence_after_settle(tmp_path, monkeypatch):
    cm_exe = tmp_path / "Content Manager.exe"
    cm_exe.touch()
    observations = iter([False, True, False])
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("subprocess.Popen", lambda _args: object())
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _ensure_cm_running(
            cm_exe,
            timeout=5.0,
            settle=1.0,
            poll=0.5,
            process_running=lambda _image: next(observations),
        )
        is False
    )
    assert now == 1.0


def test_ensure_acs_gone_honors_release_before_process_probe() -> None:
    with pytest.raises(_OperatorRelease):
        _ensure_acs_gone(
            lambda: pytest.fail("release must be checked before probing or killing acs.exe"),
            release_requested=lambda: True,
        )


class TestStableSessionWatch:
    """#630 Part A — a render freeze AFTER the stable handoff must be surfaced, not held as healthy.

    The wedge test is the Part B discriminator: graphics pinned while PHYSICS keeps advancing. That
    is what makes it safe — an alt-tab pins graphics too, but it also stops physics, so a pause can
    never latch a false wedge here.
    """

    @staticmethod
    def _watch() -> StableSessionWatch:
        return StableSessionWatch(wedge_seconds=20.0)

    def test_healthy_session_never_wedges(self) -> None:
        watch = self._watch()
        for i in range(60):  # both streams advancing for 60 s
            assert (
                watch.observe(gfx_packet=1000 + i * 5, phys_packet=9000 + i * 30, now=float(i))
                is False
            )
        assert watch.wedged is False

    def test_gfx_pinned_while_physics_advances_is_a_wedge(self) -> None:
        """The #627 §2 signature: render thread dead, physics thread alive."""
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        # gfx pinned at 5000 from t=0; physics keeps advancing.
        assert watch.observe(gfx_packet=5000, phys_packet=9030, now=10.0) is False
        assert watch.observe(gfx_packet=5000, phys_packet=9060, now=19.0) is False
        assert watch.observe(gfx_packet=5000, phys_packet=9090, now=20.0) is True
        assert watch.wedged is True

    def test_a_pause_never_wedges_even_though_graphics_pins(self) -> None:
        """An alt-tab pins graphics AND stops physics — the false wedge this avoids."""
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        for t in range(1, 90):  # 90 s paused: both streams pinned
            assert watch.observe(gfx_packet=5000, phys_packet=9000, now=float(t)) is False
        assert watch.wedged is False

    def test_a_brief_hitch_under_the_window_is_not_a_wedge(self) -> None:
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        for t in (5.0, 10.0, 15.0):  # 15 s pinned, physics advancing — under the window
            assert watch.observe(gfx_packet=5000, phys_packet=9000 + int(t) * 3, now=t) is False
        # ...then rendering resumes.
        assert watch.observe(gfx_packet=5100, phys_packet=9100, now=17.0) is False
        assert watch.wedged is False

    def test_resumed_render_clears_the_wedge_clock(self) -> None:
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        watch.observe(gfx_packet=5000, phys_packet=9030, now=15.0)  # 15 s pinned
        watch.observe(gfx_packet=5100, phys_packet=9060, now=16.0)  # advances -> clock resets
        assert watch.observe(gfx_packet=5100, phys_packet=9090, now=30.0) is False  # 14 s
        assert watch.observe(gfx_packet=5100, phys_packet=9120, now=36.0) is True  # 20 s since 16

    def test_unreadable_sample_neither_advances_nor_confirms(self) -> None:
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        assert watch.observe(gfx_packet=None, phys_packet=None, now=10.0) is False
        assert watch.wedged is False

    def test_wedged_latches(self) -> None:
        watch = self._watch()
        watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
        assert watch.observe(gfx_packet=5000, phys_packet=9060, now=25.0) is True
        # A later advance does not un-wedge it (terminal per #627 §3.2).
        assert watch.observe(gfx_packet=6000, phys_packet=9090, now=26.0) is True


def test_unreadable_sample_does_not_restart_the_wedge_clock() -> None:
    """#630 Part A — an unreadable blip must not defer (or defeat) detection of a real wedge.

    Resetting the clock on ``None`` would let a periodically-unreadable section keep restarting the
    window while the render thread stays dead.
    """
    watch = StableSessionWatch(wedge_seconds=20.0)
    watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
    watch.observe(gfx_packet=5000, phys_packet=9030, now=5.0)  # wedge clock running from t=0
    watch.observe(gfx_packet=None, phys_packet=None, now=10.0)  # blip: neutral, clock keeps running
    assert watch.observe(gfx_packet=5000, phys_packet=9060, now=20.0) is True


def test_a_resumed_render_after_a_blip_still_clears_the_clock() -> None:
    """The neutral-blip rule must not make the clock un-clearable: real progress still resets it."""
    watch = StableSessionWatch(wedge_seconds=20.0)
    watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
    watch.observe(gfx_packet=None, phys_packet=None, now=5.0)
    watch.observe(gfx_packet=5100, phys_packet=9030, now=10.0)  # render advanced -> clock cleared
    assert watch.observe(gfx_packet=5100, phys_packet=9060, now=25.0) is False


def test_hold_retries_a_failed_wedged_phase_publish() -> None:
    """#630 Part A — a swallowed publish failure would leave Game Point showing a healthy hold.

    That is the exact failure this detection exists to end, so the durable write is retried until
    it lands rather than attempted once inside the latch transition.
    """
    polls = {"n": 0}

    def acs_alive() -> bool:
        polls["n"] += 1
        return polls["n"] <= 10

    phys = {"p": 1000}

    def read_state() -> tuple[int | None, bool | None, int | None]:
        phys["p"] += 10  # physics advancing while graphics stays pinned -> a wedge
        return 500, True, phys["p"]

    published = {"attempts": 0}

    def set_phase(name: str) -> None:
        assert name == "wedged"
        published["attempts"] += 1
        if published["attempts"] == 1:
            raise OSError("durable phase write failed")

    _hold_stable_session(
        acs_alive,
        lambda: False,
        poll=0.0,
        read_state=read_state,
        set_phase=set_phase,
        wedge_seconds=1e-6,
    )

    # First attempt raised; the loop must have retried and landed it.
    assert published["attempts"] >= 2


def test_hold_publishes_the_wedged_phase_exactly_once_on_success() -> None:
    polls = {"n": 0}

    def acs_alive() -> bool:
        polls["n"] += 1
        return polls["n"] <= 10

    phys = {"p": 1000}

    def read_state() -> tuple[int | None, bool | None, int | None]:
        phys["p"] += 10
        return 500, True, phys["p"]

    calls: list[str] = []
    _hold_stable_session(
        acs_alive,
        lambda: False,
        poll=0.0,
        read_state=read_state,
        set_phase=calls.append,
        wedge_seconds=1e-6,
    )

    assert calls == ["wedged"]


def test_a_blip_before_the_first_confirm_does_not_move_the_wedge_anchor() -> None:
    """#630 Part A — the reviewer's deferral scenario, pinned.

    Establish the pin at t=0, blip at t=10, first confirming read at t=15. The anchor must remain
    t=0 (when the packet was last SEEN at that value), so the 20 s window latches at t=20 — not at
    t=30, which is what an anchor moved forward by the blip would produce.
    """
    watch = StableSessionWatch(wedge_seconds=20.0)
    watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
    watch.observe(gfx_packet=None, phys_packet=None, now=10.0)  # blip must not move the anchor
    assert watch.observe(gfx_packet=5000, phys_packet=9030, now=15.0) is False
    assert watch.observe(gfx_packet=5000, phys_packet=9060, now=20.0) is True


def test_an_armed_clock_expires_even_on_a_neutral_sample() -> None:
    """A shared-memory blackout after the wedge was confirmed must not postpone reporting it."""
    watch = StableSessionWatch(wedge_seconds=20.0)
    watch.observe(gfx_packet=5000, phys_packet=9000, now=0.0)
    watch.observe(gfx_packet=5000, phys_packet=9030, now=5.0)  # clock armed, anchored at t=0
    # Section goes unreadable and never comes back; the armed clock still expires.
    assert watch.observe(gfx_packet=None, phys_packet=None, now=25.0) is True


@pytest.mark.parametrize(
    ("report_written", "intentional_release", "expected"),
    [
        (True, True, 0),
        (True, False, 1),
        (False, True, 1),
        (False, False, 1),
    ],
)
def test_stable_session_exit_code_requires_written_report(
    report_written: bool, intentional_release: bool, expected: int
) -> None:
    """#657 Qodo — failed exclusive --json publish must not exit 0 after STABLE."""
    from tools.ac_harness.resilient_launch import stable_session_exit_code

    assert (
        stable_session_exit_code(
            report_written=report_written,
            intentional_release=intentional_release,
        )
        == expected
    )


class TestWriteReportJson:
    """#657 — exclusive publish without destination tombstones; refuse overwrite."""

    def test_writes_once_and_refuses_overwrite(self, tmp_path, monkeypatch) -> None:
        from tools.ac_harness.resilient_launch import (
            LaunchReport,
            LaunchVerdict,
            _write_report_json,
        )

        logs: list[str] = []
        monkeypatch.setattr(
            "tools.ac_harness.resilient_launch._log",
            lambda message: logs.append(message),
        )
        path = tmp_path / "trial.json"
        report = LaunchReport(
            verdict=LaunchVerdict.STABLE,
            attempts=1,
            froze=0,
            never_live=0,
            stable=1,
        )
        assert _write_report_json(report, path) is True
        assert path.is_file()
        assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "stable"
        assert _write_report_json(report, path) is False
        assert any("refusing overwrite" in line for line in logs)
        # No leftover temp siblings after a successful exclusive publish.
        assert list(tmp_path.glob(".trial.json.*.tmp")) == []

    def test_fdopen_failure_closes_raw_fd_and_returns_false(self, tmp_path, monkeypatch) -> None:
        """#657 Qodo — mkstemp fd must not leak when fdopen raises."""
        from tools.ac_harness.resilient_launch import (
            LaunchReport,
            LaunchVerdict,
            _write_report_json,
        )

        closed: list[int] = []
        real_fdopen = os.fdopen
        real_close = os.close

        def boom_fdopen(fd, *args, **kwargs):
            raise OSError("fdopen refused")

        def tracking_close(fd):
            closed.append(fd)
            return real_close(fd)

        monkeypatch.setattr("tools.ac_harness.resilient_launch.os.fdopen", boom_fdopen)
        monkeypatch.setattr("tools.ac_harness.resilient_launch.os.close", tracking_close)
        monkeypatch.setattr(
            "tools.ac_harness.resilient_launch._log",
            lambda _message: None,
        )
        path = tmp_path / "trial.json"
        report = LaunchReport(
            verdict=LaunchVerdict.STABLE,
            attempts=1,
            froze=0,
            never_live=0,
            stable=1,
        )
        assert _write_report_json(report, path) is False
        assert not path.exists()
        assert closed, "raw mkstemp fd must be closed after fdopen failure"
        # Restore builtins for any leftover handles in this process.
        monkeypatch.setattr("tools.ac_harness.resilient_launch.os.fdopen", real_fdopen)


class TestPerturberTreatmentReceipt:
    """#719 — the #625 A/B must MEASURE the treatment, not take the operator at their word.

    The asymmetry under test is empirical, not stylistic: on the rig 2026-07-28 one live
    ``acs.exe`` showed neither perturber at 45 modules loaded and BOTH at 115 modules ~3 s later.
    A single early snapshot therefore cannot establish absence.
    """

    def test_presence_is_dispositive_and_unions_across_samples(self):
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        # The early snapshot that misses everything — exactly the measured race.
        watch.observe(frozenset({"ntdll.dll", "kernel32.dll"}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        # A later snapshot sees it; a still-later one misses it again.
        watch.observe(frozenset({"gameoverlayrenderer64.dll"}))
        watch.observe(frozenset({"ntdll.dll"}))
        # Presence must survive: a perturber cannot un-inject, so the union is the truth.
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.INJECTED)
        assert watch.injected("steam_overlay")

    def test_failed_snapshot_is_unavailable_not_absent(self):
        """The inversion this whole feature exists to prevent."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(None)
        watch.observe(None)
        assert watch.successful_looks == 0
        for value in watch.evidence().values():
            # Were this NOT_OBSERVED, a denied OpenProcess would read as "overlay disabled" and
            # silently flip a boot's arm.
            assert value == str(PerturberEvidence.UNAVAILABLE)

    def test_empty_module_set_is_absent_not_unavailable(self):
        """A SUCCESSFUL look that found nothing is a real (weak) observation."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(frozenset())
        assert watch.successful_looks == 1
        assert watch.evidence()["nvidia_capture"] == str(PerturberEvidence.NOT_OBSERVED)

    def test_module_matching_is_case_insensitive(self):
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(frozenset({"GameOverlayRenderer64.dll".casefold()}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.INJECTED)

    def test_only_the_off_arm_can_be_refuted_by_one_attempt(self):
        from tools.ac_harness.resilient_launch import (
            PerturberEvidence,
            contradicts_expectation,
        )

        injected = {"steam_overlay": str(PerturberEvidence.INJECTED)}
        absent = {"steam_overlay": str(PerturberEvidence.NOT_OBSERVED)}
        unavailable = {"steam_overlay": str(PerturberEvidence.UNAVAILABLE)}

        # Dispositive: planned off, demonstrably injected.
        assert contradicts_expectation(injected, "off") is True
        # NOT dispositive: the injection race makes a single miss uninformative, so the `on` arm
        # is judged by the analyzer over the whole boot, never aborted here.
        assert contradicts_expectation(absent, "on") is False
        assert contradicts_expectation(unavailable, "off") is False
        assert contradicts_expectation(absent, "off") is False
        # No declared arm: an ordinary launch outside the experiment is never interrupted.
        assert contradicts_expectation(injected, None) is False

    def test_contradicted_off_arm_stops_the_loop_without_desyncing_cycles(self):
        """The early stop must leave ``cycles`` consistent with ``attempts_log`` (#710 contract)."""
        from tools.ac_harness.resilient_launch import (
            AttemptOutcome,
            LaunchVerdict,
            PerturberEvidence,
            run_retry_loop,
        )

        def watch(attempt: int) -> AttemptOutcome:
            return AttemptOutcome(
                LaunchVerdict.FROZE,
                cycle_delivered=True,
                perturbers={"steam_overlay": str(PerturberEvidence.INJECTED)},
            )

        report = run_retry_loop(
            watch,
            max_attempts=24,
            stop_on_stable=False,
            uptime_hours=lambda: None,
            expect_perturbers="off",
        )
        # Stopped on the FIRST attempt rather than burning all 24 launch cycles.
        assert report.attempts == 1
        assert report.arm_contradicted is True
        assert report.expect_perturbers == "off"
        # Without the counters running before the break, this attempt would appear in the log but
        # not in `cycles`/`counts`, and the analyzer would reject the report as corrupt
        # (cursor HIGH / Codex P1 on #721).
        assert report.cycles_delivered == 1
        assert report.froze == 1
        assert report.stable == 0
        assert report.never_live == 0
        assert report.wedged_init == 0
        assert len(report.attempts_log) == 1
        payload = report.as_dict()
        assert payload["cycles"]["delivered"] == len(payload["attempts_log"])
        assert payload["counts"] == {
            "stable": 0,
            "froze": 1,
            "wedged_init": 0,
            "not_drivable": 0,
            "never_live": 0,
        }
        assert payload["arm_contradicted"] is True

    def test_matching_off_arm_runs_the_whole_budget(self):
        from tools.ac_harness.resilient_launch import (
            AttemptOutcome,
            LaunchVerdict,
            PerturberEvidence,
            run_retry_loop,
        )

        def watch(attempt: int) -> AttemptOutcome:
            return AttemptOutcome(
                LaunchVerdict.FROZE,
                cycle_delivered=True,
                perturbers={"steam_overlay": str(PerturberEvidence.NOT_OBSERVED)},
            )

        report = run_retry_loop(
            watch,
            max_attempts=5,
            stop_on_stable=False,
            uptime_hours=lambda: None,
            expect_perturbers="off",
        )
        assert report.attempts == 5
        assert report.arm_contradicted is False

    def test_report_defaults_every_attempt_to_unavailable(self):
        """A producer that never looked must not read as one that looked and found nothing."""
        from tools.ac_harness.resilient_launch import (
            LaunchVerdict,
            PerturberEvidence,
            run_retry_loop,
        )

        report = run_retry_loop(
            lambda i: LaunchVerdict.STABLE, max_attempts=1, uptime_hours=lambda: None
        )
        payload = report.as_dict()
        assert payload["attempts_log"][0]["perturbers"] == {
            "steam_overlay": str(PerturberEvidence.UNAVAILABLE),
            "nvidia_capture": str(PerturberEvidence.UNAVAILABLE),
        }
        assert payload["perturbers"]["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)
        # Perturbers ride OUTSIDE `counts`, which stays the verdict histogram consumers compare.
        assert set(payload["counts"]) == {
            "stable",
            "froze",
            "wedged_init",
            "not_drivable",
            "never_live",
        }
        # No declared arm -> the experiment-only fields stay absent entirely.
        assert "expect_perturbers" not in payload
        assert "arm_contradicted" not in payload

    def test_boot_summary_unions_evidence_across_attempts(self):
        from tools.ac_harness.resilient_launch import (
            AttemptOutcome,
            LaunchVerdict,
            PerturberEvidence,
            run_retry_loop,
        )

        seen = {
            1: str(PerturberEvidence.UNAVAILABLE),
            2: str(PerturberEvidence.NOT_OBSERVED),
            3: str(PerturberEvidence.INJECTED),
        }

        def watch(attempt: int) -> AttemptOutcome:
            return AttemptOutcome(
                LaunchVerdict.FROZE,
                cycle_delivered=True,
                perturbers={"steam_overlay": seen[attempt], "nvidia_capture": seen[1]},
            )

        report = run_retry_loop(
            watch, max_attempts=3, stop_on_stable=False, uptime_hours=lambda: None
        )
        summary = report.perturber_summary()
        # One sighting anywhere in the boot is dispositive for the boot.
        assert summary["steam_overlay"] == str(PerturberEvidence.INJECTED)
        # Never successfully looked for this one across any attempt.
        assert summary["nvidia_capture"] == str(PerturberEvidence.UNAVAILABLE)

    def test_invalid_expectation_is_rejected(self):
        from tools.ac_harness.resilient_launch import LaunchVerdict, run_retry_loop

        with pytest.raises(ValueError, match="expect_perturbers"):
            run_retry_loop(
                lambda i: LaunchVerdict.STABLE,
                max_attempts=1,
                uptime_hours=lambda: None,
                expect_perturbers="overlays_off",
            )

    def test_partial_multi_pid_sample_does_not_invent_absence(self):
        """Codex P1: a failed PID snapshot must not turn a miss on another PID into not_observed."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        # One PID opened cleanly with no overlay; the other failed — presence unknown for absence.
        watch.note_injected(frozenset({"ntdll.dll"}))
        assert watch.successful_looks == 0
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)
        # Dispositive presence still records through the partial path.
        watch.note_injected(frozenset({"gameoverlayrenderer64.dll"}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.INJECTED)

    def test_early_miss_then_failed_looks_is_unavailable_not_absent(self):
        """Codex P1: a race-window miss must not stick after later snapshots fail."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(frozenset({"ntdll.dll"}))  # early miss
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        watch.observe(None)  # later failure
        watch.observe(None)
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)
        # A final successful miss restores not_observed (post-race look).
        watch.observe(frozenset({"ntdll.dll"}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)

    def test_partial_pid_sample_invalidates_prior_absence(self):
        """Cursor HIGH: note_injected alone must not leave a sticky not_observed."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(frozenset({"ntdll.dll"}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        # Partial multi-PID path: union injection then invalidate absence.
        watch.note_injected(frozenset({"ntdll.dll"}))
        watch.observe(None)
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)

    def test_empty_pid_poll_must_not_clear_prior_absence(self):
        """Cursor MEDIUM: gone acs.exe is not a failed look — leave post-race miss intact."""
        from tools.ac_harness.resilient_launch import (
            PerturberEvidence,
            PerturberWatch,
            fold_perturber_snapshots,
        )

        watch = PerturberWatch()
        watch.observe(frozenset({"ntdll.dll"}))  # post-race miss
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        fold_perturber_snapshots(watch, pids_empty=True)
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        # Contrast: a real failed look at a live process does invalidate.
        fold_perturber_snapshots(watch, enum_failed=True)
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)

    def test_fold_partial_and_full_pid_samples(self):
        """fold_perturber_snapshots covers partial invalidation and full multi-PID observe."""
        from tools.ac_harness.resilient_launch import (
            PerturberEvidence,
            PerturberWatch,
            fold_perturber_snapshots,
        )

        watch = PerturberWatch()
        watch.observe(frozenset({"ntdll.dll"}))
        fold_perturber_snapshots(
            watch,
            successes=[frozenset({"ntdll.dll"})],
            any_pid_failed=True,
        )
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.UNAVAILABLE)

        watch2 = PerturberWatch()
        # primary_only (default): only the first snapshot is classified — unioning two
        # PIDs would invent full treatment when Steam and NVIDIA sit on different processes.
        fold_perturber_snapshots(
            watch2,
            successes=[
                frozenset({"ntdll.dll"}),
                frozenset({"gameoverlayrenderer64.dll"}),
            ],
            any_pid_failed=False,
        )
        assert watch2.evidence()["steam_overlay"] == str(PerturberEvidence.NOT_OBSERVED)
        watch3 = PerturberWatch()
        fold_perturber_snapshots(
            watch3,
            successes=[frozenset({"gameoverlayrenderer64.dll", "nvspcap64.dll"})],
        )
        assert watch3.evidence()["steam_overlay"] == str(PerturberEvidence.INJECTED)
        assert watch3.evidence()["nvidia_capture"] == str(PerturberEvidence.INJECTED)

    def test_arm_contradicted_salvage_path_is_unique_per_timestamp(self, tmp_path):
        """Cursor MEDIUM: salvage names must not collide under exclusive publish."""
        from tools.ac_harness.resilient_launch import (
            LaunchReport,
            LaunchVerdict,
            _arm_contradicted_salvage_path,
            _write_report_json,
        )

        base = tmp_path / "boot3.json"
        first = _arm_contradicted_salvage_path(base, when=1_753_766_510.100000)
        second = _arm_contradicted_salvage_path(base, when=1_753_766_510.200000)
        assert first != second
        assert first.name.startswith("boot3.arm_contradicted.")
        assert first.suffix == ".json"
        # No colons — Windows path safety.
        assert ":" not in first.name
        report = LaunchReport(
            verdict=LaunchVerdict.FROZE,
            attempts=1,
            froze=1,
            never_live=0,
            stable=0,
            arm_contradicted=True,
        )
        assert _write_report_json(report, first) is True
        assert _write_report_json(report, second) is True
        # Same timestamp would refuse overwrite — uniqueness is what makes retry work.
        assert _write_report_json(report, first) is False

    def test_stable_on_arm_miss_stops_the_loop(self):
        """Codex P1: STABLE + successful miss makes on-arm confirmation impossible."""
        from tools.ac_harness.resilient_launch import (
            AttemptOutcome,
            LaunchVerdict,
            PerturberEvidence,
            contradicts_expectation,
            run_retry_loop,
        )

        evidence = {
            "steam_overlay": str(PerturberEvidence.NOT_OBSERVED),
            "nvidia_capture": str(PerturberEvidence.NOT_OBSERVED),
        }
        assert contradicts_expectation(evidence, "on", verdict=LaunchVerdict.STABLE) is True
        assert contradicts_expectation(evidence, "on", verdict=LaunchVerdict.WEDGED_INIT) is False
        assert contradicts_expectation(evidence, "on", verdict=LaunchVerdict.FROZE) is False

        def watch(_attempt: int) -> AttemptOutcome:
            return AttemptOutcome(
                LaunchVerdict.STABLE,
                cycle_delivered=True,
                perturbers=evidence,
            )

        report = run_retry_loop(
            watch,
            max_attempts=24,
            stop_on_stable=False,
            uptime_hours=lambda: None,
            expect_perturbers="on",
        )
        assert report.attempts == 1
        assert report.arm_contradicted is True
        assert report.stable == 1

    def test_pid_replacement_latches_injection_without_on_arm_union(self):
        """Codex P1: latch off-arm injection; reset so on-arm cannot inherit corpse full set."""
        from tools.ac_harness.resilient_launch import PerturberEvidence, PerturberWatch

        watch = PerturberWatch()
        watch.observe(frozenset({"gameoverlayrenderer64.dll", "nvspcap64.dll", "ntdll.dll"}))
        assert watch.evidence()["steam_overlay"] == str(PerturberEvidence.INJECTED)
        latched = {name for name in ("steam_overlay", "nvidia_capture") if watch.injected(name)}
        watch.reset()
        # Replacement only has Steam — on-arm must not see full injection from the latch alone.
        watch.observe(frozenset({"gameoverlayrenderer64.dll"}))
        evidence = dict(watch.evidence())
        for name in latched:
            evidence[name] = str(PerturberEvidence.INJECTED)
        assert evidence["steam_overlay"] == str(PerturberEvidence.INJECTED)
        # After reset, nvidia is only latched if it was on the corpse; if we latched both,
        # the emission overlays both — for off-arm. On-arm confirmation requires stable
        # per-launch full set from the live watch before latch overlay; analyzer uses
        # per-launch rows. Unit-level: latch is a plain dict overlay of injected keys.
        assert "nvidia_capture" in latched
