"""Resilient AC launcher — retry past the CSP init livelock, hold a stable session (#624).

Why this exists (#619): Custom Shaders Patch hits a **stochastic infinite loop on AC's main
thread during session init** — dump-proven (thread 0 parked on an arithmetic instruction inside
a tight hash loop in CSP's ``accRenderingAdv.dll``, no wait frame, all other threads idle). It is
roughly a coin-flip per launch, and a session that *clears* init runs indefinitely stable. So the
rig is not unusable because sessions die — it is unusable because **starting one is a lottery**.

This module turns that lottery into a bounded retry: relaunch until a session sustains continuous
render progress for a stability window, then leave AC **live and drivable** for the operator (it
never hijacks car controls, unlike ``auto_drive``).

Why the existing pieces do not cover it:

* :mod:`tools.ac_harness.entry_launcher` retries, but declares success after a handful of quick
  live reads — it **misses the delayed init freeze**, which lands ~48-90 s *after* go-live.
* :mod:`tools.ac_harness.auto_drive` reaches live reliably but then drives autonomously and exits
  on a bounded window, so it cannot hand a live session to a human driver.

The launch itself reuses the proven primitives (``ContentManagerActuator`` +
``minimize_foreground_window`` + a freshly generated deterministic preset). A prototype that
hand-rolled the ``acmanager://`` URL returned ``never_live`` repeatedly because it skipped the
foreground-minimize (CM's auto-start race loses when a window holds the desktop foreground) and
CM's stale-session cold-restart (#537/#558) — both are handled here.

The verdict logic is a **pure function** over sampled ``(t, gfx_packet, acs_alive)`` traces so it
is unit-tested off-rig with no Assetto Corsa present.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

DEFAULT_STABILITY_WINDOW = 140.0
DEFAULT_GO_LIVE_TIMEOUT = 80.0
DEFAULT_MAX_ATTEMPTS = 12
#: consecutive unchanged-packet samples (while acs is alive) that count as a wedge
DEFAULT_STALL_SAMPLES = 4
#: seconds a physics-stagnant pause hold (#630 Part B) is honored before sustained dual-stream
#: stagnation must be treated as the hang it may be — a hard hang that pins BOTH streams while
#: acs.exe stays enumerated is indistinguishable from an alt-tab at any single instant, so the
#: carve-out is bounded and the ordinary stall/not-ready paths take over past this budget.
DEFAULT_PAUSE_BUDGET = 300.0
#: consecutive never_live attempts before cold-restarting Content Manager (#537/#558)
NEVER_LIVE_BEFORE_CM_RESTART = 2
#: seconds a cached Car0 drivability verdict stays valid before the handshake re-runs (#630
#: Part D) — a one-shot latch would hold a session that LOSES drivability after go-live as
#: STABLE for the rest of the window. Long enough that a 140 s window costs ~3 extra probes.
DEFAULT_CAR0_REPROBE_SECONDS = 45.0


class LaunchVerdict(StrEnum):
    """Outcome of watching one launch attempt.

    ``NEVER_LIVE`` and ``WEDGED_INIT`` split what used to be one bucket (#630 Part C): the first
    means **acs.exe never appeared** (or appeared and exited during load) — a launch-delivery
    failure, usually Content Manager's; the second means **acs.exe appeared and burned the whole
    go-live budget alive without ever publishing an advancing render stream** — the #627 init
    livelock signature. Any freeze *rate* for #627 must count ``WEDGED_INIT`` with ``FROZE``, or
    the init wedge disappears into launch-plumbing noise and the denominator means nothing.
    """

    PENDING = "pending"
    STABLE = "stable"
    FROZE = "froze"
    NEVER_LIVE = "never_live"
    WEDGED_INIT = "wedged_init"


REPORT_SCHEMA = "resilient-launch-report/v1"
TERMINAL_VERDICTS = frozenset(
    {
        LaunchVerdict.STABLE.value,
        LaunchVerdict.FROZE.value,
        LaunchVerdict.NEVER_LIVE.value,
        LaunchVerdict.WEDGED_INIT.value,
    }
)
FREEZE_VERDICTS = frozenset({LaunchVerdict.FROZE.value, LaunchVerdict.WEDGED_INIT.value})


class _ContentManagerRestartTimeout(RuntimeError):
    """A killed Content Manager never released its process/IPC identity."""


class _AcsCleanupTimeout(RuntimeError):
    """A killed Assetto Corsa process remained alive past the cleanup deadline."""


class _Car0ProbeCleanupError(RuntimeError):
    """The temporary Custom-AI drivability mapping could not be released safely."""

    def __init__(self, message: str, controller: object) -> None:
        super().__init__(message)
        self.controller = controller


class _Car0ProbeTelemetryCleanupError(RuntimeError):
    """CarControls released, but a read-only Car data mapping must remain retained for retry."""

    def __init__(self, message: str, controller: object) -> None:
        super().__init__(message)
        self.controller = controller


class _Car0NotDrivable(RuntimeError):
    """The one bounded Car0 handshake completed without a drivable car."""


class _OperatorRelease(RuntimeError):
    """Game Point explicitly requested release of resilient rig ownership."""


@dataclass(frozen=True)
class Sample:
    """One observation of the sim's render liveness.

    ``gfx_packet`` is ``acpmf_graphics.packetId`` — it advances once per rendered frame, so a
    frozen render loop pins it while the process stays alive. ``entry_ready`` preserves the
    graphics page's LIVE + not-in-pit predicate. ``drivable`` is the stronger, rig-proven Car0
    handshake: the CSP pre-drive overlay can report LIVE + not-in-pit while remaining non-drivable.
    ``phys_packet`` is ``acpmf_physics.packetId``: it keeps advancing during a genuine render wedge
    (#627 §2) but STOPS at a pause/menu, so its stagnation is the reliable pause signal — AC often
    leaves ``status`` at LIVE when paused (``shared_memory`` documents this), which is why status
    alone cannot tell a pause from a freeze (#630 Part B). ``None`` means the field was not read.
    """

    t: float
    gfx_packet: int | None
    acs_alive: bool
    entry_ready: bool | None = True
    drivable: bool | None = True
    phys_packet: int | None = None


def classify(
    samples: Sequence[Sample],
    *,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    stall_samples: int = DEFAULT_STALL_SAMPLES,
    started_at: float | None = None,
    pause_budget: float = DEFAULT_PAUSE_BUDGET,
    pause_sink: list[float] | None = None,
) -> LaunchVerdict:
    """Classify one launch attempt from its liveness trace. Pure — no I/O, no clock.

    Semantics:

    * **go-live** is the first sample whose ``gfx_packet`` advanced over the previous sample while
      ``acs_alive``. No go-live within ``go_live_timeout`` of the first sample → ``WEDGED_INIT``
      when ``acs.exe`` was observed alive during the wait AND its render stream never advanced
      (it appeared and burned the whole budget without publishing — the #627 init livelock), else
      ``NEVER_LIVE``: the process never appeared, appeared and exited during load, or rendered
      happily without ever reaching readiness (a stuck pre-drive menu is launch plumbing, not a
      wedge — putting it in the wedge bucket would pollute the #627 rate from the other side)
      (#630 Part C).
    * after go-live, ``stall_samples`` consecutive samples with an unchanged ``gfx_packet`` while
      ``acs_alive`` → ``FROZE`` (this is the delayed init livelock the other launchers miss).
    * surviving ``stability_window`` seconds past go-live without stalling → ``STABLE``.
    * a **pause** (physics packet stagnant post-go-live, #630 Part B) is never credited toward
      the stability window, and its freeze counters stay cleared for up to ``pause_budget``
      cumulative seconds. Beyond the budget the ordinary stall/not-ready paths resume — an
      unbounded hold would make a real hang undetectable — and ``STABLE`` always requires
      physics ADVANCING, so a session that never resumed cannot hand off.

    ``acs`` disappearing after go-live is reported as ``FROZE`` rather than ``STABLE``: the session
    did not survive, and the caller must retry either way.

    When ``pause_sink`` is provided and the trace is still ``PENDING`` past go-live, the cumulative
    held-pause seconds are appended to it. ``_watch_live`` extends its wall-clock budget by exactly
    this much so a held pause cannot FROZE a healthy paused session at a fixed deadline.
    """
    if not samples:
        return LaunchVerdict.PENDING
    if go_live_timeout <= 0:
        raise ValueError("go_live_timeout must be > 0")
    if stability_window <= 0:
        raise ValueError("stability_window must be > 0")
    if stall_samples <= 0:
        raise ValueError("stall_samples must be > 0")
    if pause_budget <= 0:
        raise ValueError("pause_budget must be > 0")

    # ``_watch_live`` supplies its pre-probe start so a blocking readiness handshake consumes the
    # go-live budget. Pure/unit callers may omit it and retain the trace-relative behavior.
    t0 = samples[0].t if started_at is None else started_at
    live_since: float | None = None
    prev_packet: int | None = None
    prev_phys: int | None = None
    prev_t: float | None = None
    stall_run = 0
    not_ready_run = 0
    paused_total = 0.0
    seen_acs_alive = False
    seen_stream_advance = False
    alive_pre_live_samples = 0

    for sample in samples:
        ready = sample.entry_ready is True and sample.drivable is True
        not_ready = sample.entry_ready is False or sample.drivable is False
        advanced = (
            sample.acs_alive
            and sample.gfx_packet is not None
            and prev_packet is not None
            and sample.gfx_packet > prev_packet
        )
        regressed = (
            sample.gfx_packet is not None
            and prev_packet is not None
            and sample.gfx_packet < prev_packet
        )
        # A pause/menu is read from PHYSICS stagnation, not status: a render wedge (#627 §2) keeps
        # physics advancing while the graphics packet pins, whereas a pause stops physics — and AC
        # often leaves status at LIVE when paused. Unknown physics (None) degrades to the
        # graphics-only behavior so off-rig traces without a physics page are unaffected.
        phys_stagnant = (
            sample.phys_packet is not None
            and prev_phys is not None
            and sample.phys_packet == prev_phys
        )
        if live_since is None:
            if seen_acs_alive and not sample.acs_alive:
                return LaunchVerdict.NEVER_LIVE
            seen_acs_alive = seen_acs_alive or sample.acs_alive
            seen_stream_advance = seen_stream_advance or advanced
            if sample.acs_alive:
                alive_pre_live_samples += 1
            if sample.t - t0 >= go_live_timeout:
                # #630 Part C — the go-live timeout has two very different causes and they must
                # not share a bucket. acs.exe alive through the budget without EVER advancing its
                # render stream is the init livelock (#627 §2 landing DURING session init — it
                # never reaches a packet-advancing sample, so the FROZE branch below is
                # unreachable for it). Everything else stays NEVER_LIVE: the process never
                # appearing is launch plumbing (a cold/stale Content Manager); a crash during
                # load exits via the early return above; and a stream that ADVANCED but never
                # reached readiness is a stuck pre-drive menu — rendering, therefore not wedged.
                # The wedge claim needs SUSTAINED evidence — at least two alive observations with
                # no advance between any of them. A timeout whose only alive sample is the final
                # one (e.g. a blocking readiness probe consumed the budget) proves nothing about
                # publication and stays NEVER_LIVE. Only the proven never-published shape may
                # count toward the #627 freeze rate.
                if alive_pre_live_samples >= 2 and not seen_stream_advance:
                    return LaunchVerdict.WEDGED_INIT
                return LaunchVerdict.NEVER_LIVE
            # A regression BEFORE go-live is a hand-over, not a failure — there is no accumulated
            # stability to protect yet, so it is deliberately not checked here. Measured on the
            # rig, the previous session's acpmf_graphics section stays mapped for ~6 s INTO the new
            # acs.exe's lifetime: the process exists and is loading but has not yet published its
            # own stream, so the reader still sees the dead session's high packet id.
            #
            #   t=0.0  acs=None   gfx=16983   <- corpse
            #   t=2.0  acs=14020  gfx=16983   <- new acs alive, section STILL the corpse
            #   t=8.0  acs=14020  gfx=121     <- new session finally publishes
            #
            # Failing on that threw away a launch that was loading perfectly normally. Rebasing is
            # implicit: ``prev_packet`` is reassigned at the end of this iteration, and a regressed
            # sample can never also be ``advanced``. The go-live timeout above remains the only
            # pre-live failure. The post-go-live guard is deliberately left as-is — a regression
            # THERE really does mean a replacement session must not inherit its progress. See #628.
            if advanced and ready:
                live_since = sample.t
        else:
            if not sample.acs_alive:
                return LaunchVerdict.FROZE
            if regressed:
                # packetId reset means the render stream/session was replaced; never let a new
                # acs.exe inherit stability time accumulated by its predecessor.
                return LaunchVerdict.FROZE
            if phys_stagnant and prev_t is not None:
                # Physics pinned: this interval is NEVER credited as proven-live time, whatever
                # the budget — STABLE must be earned with physics RUNNING, so a pause that
                # outlasts the budget cannot hand off on wall-clock accumulation (#637 daemon).
                live_since += sample.t - prev_t
                paused_total += sample.t - prev_t
            if phys_stagnant and paused_total <= pause_budget:
                # #630 Part B — physics stopped advancing: the sim is paused or at a menu (the
                # graphics packet may pin OR keep animating; either way this is NOT a render wedge,
                # which holds physics ADVANCING). Hold: clear the freeze counters so an alt-tab
                # cannot trip a false FROZE + taskkill. The counter-clearing is BOUNDED by
                # ``pause_budget``: a hang that pins both streams while acs.exe stays enumerated
                # is indistinguishable from a pause at any single instant, so past the budget the
                # sample falls through to the ordinary stall/not-ready paths and the attempt still
                # fails (#637 daemon MEDIUM).
                not_ready_run = 0
                stall_run = 0
            else:
                if not_ready:
                    not_ready_run += 1
                    if not_ready_run >= stall_samples:
                        return LaunchVerdict.FROZE
                elif ready:
                    not_ready_run = 0
                else:
                    # An unavailable graphics observation cannot extend a consecutive run.
                    not_ready_run = 0
                if advanced:
                    stall_run = 0
                elif sample.gfx_packet is not None and sample.gfx_packet == prev_packet:
                    stall_run += 1
                    if stall_run >= stall_samples:
                        return LaunchVerdict.FROZE
                else:
                    # Missing shared memory is unknown, not another observation of the same packet.
                    stall_run = 0
                # STABLE additionally requires physics ADVANCING when a physics reading exists:
                # an animating graphics stream with pinned physics past the pause budget is a
                # session that never resumed, not a proven-live one (#637 daemon HIGH).
                if (
                    advanced
                    and ready
                    and not phys_stagnant
                    and sample.t - live_since >= stability_window
                ):
                    return LaunchVerdict.STABLE
        # Only a reading correlated with a LIVE acs.exe may seed the comparison baseline.
        # ``acpmf_*`` is a shared section that survives its creator: a hard kill leaves it mapped
        # by whatever else has it open (measured on the rig: still PRESENT 14 s after taskkill),
        # still holding the dead session's high packet id. Seeding ``prev_packet`` from that corpse
        # makes the NEXT acs.exe — rendering its own stream from ~0 — look like a regression, and a
        # perfectly healthy launch is thrown away as NEVER_LIVE. That is trap §7.1 of the #627
        # brief reaching the shipped verdict logic, not just the ad-hoc probes. See #628.
        if sample.gfx_packet is not None and sample.acs_alive:
            prev_packet = sample.gfx_packet
        if sample.phys_packet is not None and sample.acs_alive:
            prev_phys = sample.phys_packet
        prev_t = sample.t

    if live_since is None:
        return LaunchVerdict.PENDING
    # The trace ended before either terminal threshold. A short hitch is not a freeze, and an
    # advancing live session is not a never-live failure merely because its window is unfinished.
    if pause_sink is not None:
        pause_sink.append(paused_total)
    return LaunchVerdict.PENDING


class SectionOwnershipGate:
    """Trust shared-memory readings only once the render packet proves a LIVE writer owns them.

    ``acpmf_graphics`` outlives its creator and stays mapped for several seconds INTO the next
    ``acs.exe``'s lifetime (#628). Every field is stale in that window — not just ``packet_id`` but
    ``is_live`` / ``is_in_pit`` too — so a corpse reports the session as ready before AC has even
    started. Acting on that fired the Car0 drivability handshake against a session that did not
    exist yet; measured on the rig, the shipped launcher failed 6/6 attempts in ~7 s each that way.

    The load-bearing insight: **a packet id can only advance if a live process wrote it.** A corpse
    is a frozen snapshot; it never advances on its own. So packet advancement is itself the proof
    of a live owner — no separate process-liveness probe is needed, and earlier revisions that
    consulted one only introduced strict-vs-debounced disagreement (a raw enumeration miss wrongly
    revoking trust on a healthy session). This gate consults ONLY the packet stream:

    * an **advance** proves a live writer  -> trust the section;
    * a **regression** is a new generation (``classify`` treats a post-go-live regression the same
      way) -> revoke, so a fast restart re-earns trust and ``AttemptReadiness`` re-runs the Car0
      handshake rather than inheriting the dead generation's verdict.

    Real process death is handled where it belongs — ``classify`` ends the attempt on the debounced
    ``Sample.acs_alive`` — so this gate never needs to observe liveness directly.
    """

    def __init__(self) -> None:
        self._prev_packet: int | None = None
        self._publishing = False

    @property
    def publishing(self) -> bool:
        return self._publishing

    def observe(self, packet: int | None) -> bool:
        """Record one packet observation; return whether readings may now be trusted."""
        if packet is not None and self._prev_packet is not None:
            if packet > self._prev_packet:
                self._publishing = True
            elif packet < self._prev_packet:
                self._publishing = False
        if packet is not None:
            self._prev_packet = packet
        return self._publishing


class AttemptReadiness:
    """Per-attempt readiness: section ownership plus the TTL-cached Car0 handshake.

    These two pieces of state are coupled and must be revoked together. The Car0 result is cached
    so the (expensive, blocking) handshake does not run every sample, but that cache is only valid
    for the generation it was probed against: if acs.exe dies and restarts inside one attempt, a
    stale ``True`` would let a brand-new session skip the handshake and be treated as drivable.
    Keeping the cache next to the gate that revokes ownership makes that invariant enforceable
    instead of a comment.

    The cache additionally EXPIRES after ``reprobe_seconds`` (#630 Part D): a pure one-shot latch
    meant a session that renders frames but loses Car0 drivability after go-live was still
    declared STABLE, because the handshake could never run a second time. Expiry re-earns the
    verdict on the live session within the stability window; a failed re-probe raises the same
    :class:`_Car0NotDrivable` as the first. Pass ``reprobe_seconds=None`` to restore the one-shot
    behavior (used by callers that must not touch CarControls again).
    """

    def __init__(
        self,
        probe: Callable[[], bool],
        *,
        reprobe_seconds: float | None = DEFAULT_CAR0_REPROBE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if reprobe_seconds is not None and reprobe_seconds <= 0:
            raise ValueError("reprobe_seconds must be > 0 or None")
        self._gate = SectionOwnershipGate()
        self._probe = probe
        self._reprobe_seconds = reprobe_seconds
        self._clock = clock
        self._probed_at: float | None = None
        self.car0_ready: bool | None = None

    @property
    def publishing(self) -> bool:
        return self._gate.publishing

    def observe(
        self, *, packet: int | None, entry_ready: bool | None
    ) -> tuple[bool | None, bool | None]:
        """Return ``(entry_ready, drivable)`` for this sample, or ``(None, None)`` if unproven.

        Raises :class:`_Car0NotDrivable` when the handshake runs and the car is not drivable.
        """
        if not self._gate.observe(packet):
            # Ownership has not been earned yet, or it was revoked by a packet regression (a new
            # generation). Either way a later generation must re-run the handshake rather than
            # inherit this one's verdict.
            self.car0_ready = None
            self._probed_at = None
            return None, None
        if entry_ready is True:
            expired = (
                self.car0_ready is not None
                and self._reprobe_seconds is not None
                and self._probed_at is not None
                and self._clock() - self._probed_at >= self._reprobe_seconds
            )
            if self.car0_ready is None or expired:
                self.car0_ready = self._probe()
                # Stamp AFTER the (blocking, up-to-5 s) probe returns so the TTL measures time
                # since the verdict was current, not since the handshake started.
                self._probed_at = self._clock()
                if not self.car0_ready:
                    raise _Car0NotDrivable
        return entry_ready, (self.car0_ready if entry_ready is True else None)


#: seconds a held session's render packet may stay pinned — while physics keeps advancing —
#: before the hold reports a post-handoff wedge. Well past any frame-time hitch, and #627 §3.2
#: records a wedge as terminal once it lands, so a conservative window rules out false alarms.
DEFAULT_HOLD_WEDGE_SECONDS = 20.0


class StableSessionWatch:
    """Detect a render freeze that lands AFTER the stable session was handed to the operator.

    The hold loop polls only process liveness and the release sentinel, so a render-thread wedge
    that pins the graphics packet while ``acs.exe`` stays alive — the #627 §2 signature, and the
    operator's literal "the video freezes but the tool says everything's fine" report — is
    invisible: the launcher holds a dead session as healthy indefinitely (#630 Part A).

    The wedge test is the same discriminator ``classify`` uses (#630 Part B): **graphics pinned
    while PHYSICS keeps advancing**. Watching the graphics packet alone would latch a false wedge
    on an ordinary alt-tab, because a pause pins graphics too — it just stops physics as well. So a
    pause can never trip this, and only a genuine render-thread stall can.
    """

    def __init__(self, wedge_seconds: float = DEFAULT_HOLD_WEDGE_SECONDS) -> None:
        if wedge_seconds <= 0:
            raise ValueError("wedge_seconds must be > 0")
        self._wedge_seconds = wedge_seconds
        self._prev_gfx: int | None = None
        self._prev_phys: int | None = None
        self._prev_t: float | None = None
        self._wedged_since: float | None = None
        self._wedged = False

    @property
    def wedged(self) -> bool:
        return self._wedged

    def observe(self, *, gfx_packet: int | None, phys_packet: int | None, now: float) -> bool:
        """Record one held-session sample; return True once a sustained render wedge is proven.

        Latches, so the caller surfaces the wedge exactly once. An unreadable packet neither
        advances nor confirms; a pause (physics stagnant) clears the wedge clock.
        """
        if self._wedged:
            return True
        gfx_known = gfx_packet is not None and self._prev_gfx is not None
        phys_known = phys_packet is not None and self._prev_phys is not None
        gfx_pinned = gfx_known and gfx_packet == self._prev_gfx
        gfx_moved = gfx_known and gfx_packet != self._prev_gfx
        phys_advancing = phys_known and phys_packet > self._prev_phys
        phys_stagnant = phys_known and phys_packet == self._prev_phys
        if gfx_pinned and phys_advancing:
            # Anchor at the previous sample: the packet was already pinned at that value then, so
            # the stall is measured from when it stopped moving, not from the first repeat we saw.
            if self._wedged_since is None:
                self._wedged_since = self._prev_t if self._prev_t is not None else now
        elif gfx_moved or phys_stagnant:
            # Positive evidence that no wedge is in progress: the render advanced, or physics
            # stopped (a pause). Only these clear the clock — an UNREADABLE sample must not, or a
            # momentary shared-memory blip would restart the window and could defer, or with
            # periodic blips entirely defeat, detection of a real wedge. This is the "neither
            # advances nor confirms" contract in the docstring.
            self._wedged_since = None
        # An armed clock expires on ANY sample, including a neutral one. Once the wedge has been
        # confirmed at least once, a shared-memory blackout must not postpone reporting it: the
        # surfacing is non-destructive (a log plus a phase), so erring toward reporting is right.
        if self._wedged_since is not None and now - self._wedged_since >= self._wedge_seconds:
            self._wedged = True
        if gfx_packet is not None:
            self._prev_gfx = gfx_packet
        if phys_packet is not None:
            self._prev_phys = phys_packet
        if gfx_packet is not None:
            # Only a readable graphics sample may move the anchor. The anchor means "when the
            # render packet was last seen at this value"; letting an unreadable blip carry it
            # forward would measure the stall from the blip instead of the last observed pin and
            # defer detection by the whole blip gap.
            self._prev_t = now
        return self._wedged


@dataclass(frozen=True)
class AttemptRecord:
    """One launch attempt's machine-readable outcome (#630 Part E, #627 §9.2).

    #627 §9.2 requires every trial to be recorded with its verdict AND its conditions — the
    per-launch freeze rate rises with accumulated uptime/launches, so a verdict without a
    recorded denominator and uptime is unusable for rate measurement. ``uptime_h`` is machine
    uptime at attempt start (``None`` when unavailable, e.g. off-rig tests).
    """

    attempt: int
    verdict: LaunchVerdict
    started_at_utc: str
    elapsed_s: float
    uptime_h: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "verdict": str(self.verdict),
            "started_at_utc": self.started_at_utc,
            "elapsed_s": round(self.elapsed_s, 3),
            "uptime_h": None if self.uptime_h is None else round(self.uptime_h, 4),
        }


@dataclass(frozen=True)
class LaunchReport:
    """Summary of a full retry run, with the per-attempt log #627 §9.2 requires (#630 Part E)."""

    verdict: LaunchVerdict
    attempts: int
    froze: int
    never_live: int
    wedged_init: int = 0
    stable: int = 0
    attempts_log: tuple[AttemptRecord, ...] = field(default=())
    launch: dict[str, object] | None = None

    @property
    def succeeded(self) -> bool:
        return self.verdict is LaunchVerdict.STABLE

    def _counts(self) -> str:
        return f"froze {self.froze}, wedged_init {self.wedged_init}, never_live {self.never_live}"

    def summary(self) -> str:
        if self.succeeded:
            return (
                f"stable drivable session held on attempt {self.attempts} "
                f"({self._counts()}) — AC left LIVE"
            )
        return (
            f"no stable session in {self.attempts} attempt(s) ({self._counts()}); "
            "a reboot lowers the per-launch freeze rate — rerun after one"
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serializable report — the machine-readable record #627 §9.2 asks for."""
        payload: dict[str, object] = {
            "schema": REPORT_SCHEMA,
            "verdict": str(self.verdict),
            "attempts": self.attempts,
            "counts": {
                "stable": self.stable,
                "froze": self.froze,
                "wedged_init": self.wedged_init,
                "never_live": self.never_live,
            },
            "attempts_log": [record.as_dict() for record in self.attempts_log],
        }
        if self.launch is not None:
            payload["launch"] = self.launch
        return payload


def _utc_stamp(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def run_retry_loop(
    watch_attempt: Callable[[int], LaunchVerdict],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    on_never_live_streak: Callable[[], None] | None = None,
    never_live_before_restart: int = NEVER_LIVE_BEFORE_CM_RESTART,
    stop_on_stable: bool = True,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    uptime_hours: Callable[[], float | None] | None = None,
) -> LaunchReport:
    """Drive attempts until one is ``STABLE`` or the budget is spent. Pure control flow.

    ``watch_attempt(attempt_number)`` performs one launch+watch and returns its verdict.
    ``on_never_live_streak`` is invoked once a run of ``never_live_before_restart`` consecutive
    ``NEVER_LIVE`` verdicts is seen — the hook the CLI uses to cold-restart a stale Content
    Manager (#537/#558) rather than pointlessly re-sending the same URL. A ``WEDGED_INIT``
    verdict resets that streak like ``FROZE`` does: acs.exe appeared, so CM delivered the launch
    and restarting it would only add kill-churn (#627 §6.5).

    With ``stop_on_stable=False`` every attempt in the budget runs regardless of verdict — the
    rate-measurement mode #627 §9.2 needs (``--trials``). Every attempt is recorded in the
    report's ``attempts_log`` with verdict, wall-clock start, elapsed seconds, and machine uptime
    (#630 Part E).
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be > 0")
    if never_live_before_restart <= 0:
        raise ValueError("never_live_before_restart must be > 0")

    def read_uptime() -> float | None:
        if uptime_hours is None:
            return None
        try:
            return uptime_hours()
        except OSError:
            return None

    records: list[AttemptRecord] = []
    stable = froze = never_live = wedged_init = 0
    never_live_run = 0
    last_verdict = LaunchVerdict.NEVER_LIVE
    attempts_run = 0
    for attempt in range(1, max_attempts + 1):
        started_wall = wall_clock()
        started = clock()
        uptime = read_uptime()
        verdict = watch_attempt(attempt)
        if verdict is LaunchVerdict.PENDING:
            raise ValueError("watch_attempt returned a non-terminal PENDING verdict")
        records.append(
            AttemptRecord(
                attempt=attempt,
                verdict=verdict,
                started_at_utc=_utc_stamp(started_wall),
                elapsed_s=clock() - started,
                uptime_h=uptime,
            )
        )
        last_verdict = verdict
        attempts_run = attempt
        if verdict is LaunchVerdict.STABLE:
            stable += 1
            never_live_run = 0
            if stop_on_stable:
                break
        elif verdict is LaunchVerdict.NEVER_LIVE:
            never_live += 1
            never_live_run += 1
            if never_live_run >= never_live_before_restart and on_never_live_streak is not None:
                on_never_live_streak()
                never_live_run = 0
        else:
            # FROZE and WEDGED_INIT both prove CM delivered a real acs.exe.
            if verdict is LaunchVerdict.FROZE:
                froze += 1
            else:
                wedged_init += 1
            never_live_run = 0
    return LaunchReport(
        last_verdict,
        attempts_run,
        froze,
        never_live,
        wedged_init=wedged_init,
        stable=stable,
        attempts_log=tuple(records),
    )


# --------------------------------------------------------------------------------------
# Rig side (Windows-only; imported lazily so the pure logic above stays unit-testable).
# --------------------------------------------------------------------------------------


def _log(msg: str) -> None:  # pragma: no cover - rig-only progress trace
    print(f"[resilient-launch {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _machine_uptime_hours() -> float | None:  # pragma: no cover - rig-only
    """Machine uptime in hours via ``GetTickCount64`` — the #627 §9.2 per-trial condition.

    The per-launch freeze rate rises with accumulated uptime (#627 §3.4), so a verdict recorded
    without uptime cannot be compared across sessions. ``None`` off-Windows or on API failure.
    """
    if sys.platform != "win32":
        return None
    import ctypes

    try:
        tick_count = ctypes.windll.kernel32.GetTickCount64
        # ctypes reads an undeclared return as a signed C int: this 64-bit millisecond count
        # would go negative after ~24.9 days of uptime — exactly the long-uptime regime #627
        # §3.4 needs measured (#646 review P1).
        tick_count.restype = ctypes.c_ulonglong
        tick_count.argtypes = []
        return float(tick_count()) / 3_600_000.0
    except (AttributeError, OSError):
        return None


def repo_checkout_root() -> Path:
    """The checkout this module runs from — a FIXED approved output root, unlike the CWD.

    Anchoring on the module's own location (``tools/ac_harness/`` → two parents up) keeps the
    established ``.scratch`` measurement-artifact workflow working from any invocation directory,
    while an arbitrary caller CWD (e.g. a Downloads directory) is never trusted as a write root
    (#646 review — the CWD root was caller-controlled and therefore no boundary at all).
    """
    return Path(__file__).resolve().parents[2]


def resolve_report_path(raw: Path, approved_roots: Sequence[Path]) -> Path:
    """Resolve the ``--json`` destination and require it inside an approved output root.

    #646 review: an absolute path or a ``..`` traversal would let this rig tool create parent
    directories and overwrite files at arbitrary writable locations. Callers approve the per-user
    Harness root and the checkout's gitignored ``.scratch`` tree — never the whole repo root.
    A relative path still resolves against the caller's CWD — but it only passes when that
    resolution lands inside a fixed root.
    """
    resolved = raw.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved = resolved.resolve(strict=False)
    for root in approved_roots:
        anchored = root.resolve(strict=False)
        if resolved == anchored or anchored in resolved.parents:
            return resolved
    raise ValueError(
        f"--json destination {resolved} is outside every approved output root "
        f"({', '.join(str(root) for root in approved_roots)})"
    )


# Back-compat aliases for callers/tests that still use the private names.
_repo_checkout_root = repo_checkout_root
_resolve_report_path = resolve_report_path


def stable_session_exit_code(*, report_written: bool, intentional_release: bool = True) -> int:
    """Exit code after a STABLE gate when an optional ``--json`` artifact was requested.

    A failed exclusive report publish must not claim success (#657 / #625), but the live session
    still continues into hold / ``--no-hold`` — we do not tear down solely for a missing artifact.
    """
    if not report_written:
        return 1
    return 0 if intentional_release else 1


def _write_report_json(report: LaunchReport, path: Path) -> bool:
    """Write the machine-readable run record; report success so measurement runs can gate on it.

    A failure never masks the verdict in the log — but in ``--trials`` mode the record IS the
    deliverable, so the caller converts ``False`` into a nonzero exit (#646 review P1) instead of
    letting an automated measurement run read as successful with no record produced.

    Publishes via a complete temp file + exclusive hardlink (Windows: exclusive rename). A finished
    trial report is immutable evidence and must not be silently replaced (#657 / #625 A/B). The
    destination is never created until the payload is fully written, so a crash cannot leave an
    empty ``open(..., "x")`` tombstone that blocks retries (#657 daemon).
    """
    payload = json.dumps(report.as_dict(), indent=2) + "\n"
    tmp: Path | None = None
    fd: int | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp = Path(tmp_name)
        # Take ownership of ``fd`` before writing so an ``fdopen`` failure cannot leak it
        # (#657 Qodo — raw descriptor must close even when the wrapper never runs).
        handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        fd = None
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            _log(f"report exists, refusing overwrite: {path}")
            return False
        except OSError as link_exc:
            if sys.platform != "win32":
                _log(f"WARNING: could not publish report JSON {path}: {link_exc}")
                return False
            # Windows rename fails when the destination already exists (exclusive publish).
            try:
                os.rename(tmp, path)
            except FileExistsError:
                _log(f"report exists, refusing overwrite: {path}")
                return False
            tmp = None
        else:
            try:
                tmp.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                _log(f"WARNING: could not remove report temp {tmp}: {cleanup_exc}")
            tmp = None
        _log(f"report -> {path}")
        return True
    except OSError as exc:
        _log(f"WARNING: could not write report JSON {path}: {exc}")
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                _log(f"WARNING: could not remove report temp {tmp}: {cleanup_exc}")


def _sample_now(
    read_state: Callable[
        [],
        tuple[int | None, bool | None]
        | tuple[int | None, bool | None, bool | None]
        | tuple[int | None, bool | None, bool | None, int | None],
    ],
    acs_alive: Callable[[], bool],
) -> Sample:  # pragma: no cover - rig-only
    # The Car0 handshake can block for up to five seconds. Read it first, then stamp process
    # liveness and time together: readiness is proven only when that handshake returns, so an
    # observation that completes after the go-live budget cannot be backdated into the budget or
    # shorten the stability window by the probe duration.
    state = read_state()
    observed_alive = acs_alive()
    observed_at = time.monotonic()
    phys_packet: int | None = None
    if len(state) == 2:
        packet, entry_ready = state
        drivable = entry_ready
    elif len(state) == 3:
        packet, entry_ready, drivable = state
    else:
        packet, entry_ready, drivable, phys_packet = state
    return Sample(
        t=observed_at,
        gfx_packet=packet,
        acs_alive=observed_alive,
        entry_ready=entry_ready,
        drivable=drivable,
        phys_packet=phys_packet,
    )


def _process_running(image: str) -> bool:  # pragma: no cover - rig-only
    from tools.ac_harness.entry_launcher import running_process_ids

    try:
        return bool(running_process_ids(image, strict=True))
    except OSError as exc:
        _log(f"WARNING: process enumeration failed for {image}; treating it as running: {exc}")
        return True


def _strict_process_running(image: str) -> bool:  # pragma: no cover - rig-only
    """Return process presence without converting enumeration failure into a boolean."""
    from tools.ac_harness.entry_launcher import running_process_ids

    return bool(running_process_ids(image, strict=True))


def _make_process_liveness_probe(
    image: str,
    *,
    absent_confirmations: int = 2,
    process_ids: Callable[[str], Sequence[int]] | None = None,
) -> Callable[[], bool]:
    """Return a fail-closed process probe with consecutive absence confirmation."""
    if absent_confirmations < 1:
        raise ValueError("absent_confirmations must be >= 1")
    list_process_ids = process_ids
    if list_process_ids is None:
        from tools.ac_harness.entry_launcher import running_process_ids

        def strict_process_ids(name: str) -> Sequence[int]:
            return running_process_ids(name, strict=True)

        list_process_ids = strict_process_ids
    absent_run = 0
    seen_present = False

    def is_alive() -> bool:
        nonlocal absent_run, seen_present
        try:
            found = list_process_ids(image)
        except OSError as exc:
            absent_run = 0
            _log(f"WARNING: process enumeration failed for {image}; retaining ownership: {exc}")
            # Fail closed only after this probe has observed the process. Before the first real
            # sighting, inventing presence turns the next ordinary startup absence into a false
            # process-exit edge and makes classify() report NEVER_LIVE immediately.
            return seen_present
        if found:
            absent_run = 0
            seen_present = True
            return True
        if not seen_present:
            # Before the process has appeared, absence is ordinary launch startup—not a synthetic
            # one-sample "alive" grace that classify() could mistake for an early process exit.
            return False
        absent_run += 1
        return absent_run < absent_confirmations

    return is_alive


class _ResettableProcessLivenessProbe:
    """A process probe whose sighting/absence history can be scoped to one launch attempt."""

    def __init__(
        self,
        image: str,
        *,
        absent_confirmations: int = 2,
        process_ids: Callable[[str], Sequence[int]] | None = None,
    ) -> None:
        self.image = image
        self.absent_confirmations = absent_confirmations
        self.process_ids = process_ids
        self._probe: Callable[[], bool]
        self.reset()

    def reset(self) -> None:
        self._probe = _make_process_liveness_probe(
            self.image,
            absent_confirmations=self.absent_confirmations,
            process_ids=self.process_ids,
        )

    def __call__(self) -> bool:
        return self._probe()


def _ensure_cm_running(  # pragma: no cover - rig-only
    cm_exe: Path,
    *,
    timeout: float = 45.0,
    settle: float = 8.0,
    poll: float = 1.0,
    release_requested: Callable[[], bool] | None = None,
    process_running: Callable[[str], bool] | None = None,
) -> bool:
    """Make sure Content Manager is up **before** an ``acmanager://`` URL is sent to it.

    CM processes the quick-drive URL through **single-instance IPC** — it is handed to an
    ALREADY-RUNNING CM. Firing the URL at a cold/absent CM merely opens CM's window and never
    starts a session, so every attempt reports ``never_live`` and ``acs.exe`` never appears.

    This bit us for real: the ``never_live`` cold-restart path killed CM and then immediately sent
    the next URL into the void, so the launcher spent whole runs shooting at nothing. Any A/B
    measured through that state is invalid, not just slow.
    """
    import subprocess

    if release_requested is not None and release_requested():
        raise _OperatorRelease
    if not cm_exe.is_file():
        _log(f"WARNING: Content Manager executable not found: {cm_exe}")
        return False
    process_name = cm_exe.name
    probe = process_running or _strict_process_running
    try:
        already_running = probe(process_name)
    except OSError as exc:
        _log(f"WARNING: Content Manager process enumeration failed: {exc}")
        return False
    if already_running:
        return True
    _log("Content Manager not running — starting it before sending the quick-drive URL")
    if release_requested is not None and release_requested():
        raise _OperatorRelease
    try:
        subprocess.Popen([str(cm_exe)])
    except OSError as exc:
        _log(f"WARNING: Content Manager failed to start: {exc}")
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        try:
            observed_running = probe(process_name)
        except OSError as exc:
            _log(f"WARNING: Content Manager process enumeration failed after start: {exc}")
            return False
        if observed_running:
            settle_deadline = time.monotonic() + settle
            while time.monotonic() < settle_deadline:
                if release_requested is not None and release_requested():
                    raise _OperatorRelease
                remaining = settle_deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(poll, remaining))
            try:
                survived_settle = probe(process_name)
            except OSError as exc:
                _log(f"WARNING: Content Manager settle verification failed: {exc}")
                return False
            if survived_settle:
                return True
            _log("WARNING: Content Manager exited during startup settle")
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll, remaining))
    _log("WARNING: Content Manager did not start; the launch URL will not be honored")
    return False


def _wait_process_exit(  # pragma: no cover - rig-only
    image: str,
    *,
    timeout: float = 15.0,
    poll: float = 0.25,
    release_requested: Callable[[], bool] | None = None,
) -> bool:
    """Wait until a killed Windows process has left the table before reusing its IPC name."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        if not _process_running(image):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll, remaining))
    if release_requested is not None and release_requested():
        raise _OperatorRelease
    return not _process_running(image)


def _ensure_acs_gone(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    timeout: float = 15.0,
    poll: float = 1.0,
    release_requested: Callable[[], bool] | None = None,
) -> bool:
    """Kill any surviving ``acs.exe`` and wait until it has really left the process table.

    A wedged sim keeps its window and shared-memory section, so launching on top of it makes
    Content Manager's next start fail to reach LIVE. ``taskkill`` returning is not sufficient —
    the process can linger — so poll (bounded) until it is actually gone. The caller must abort
    rather than relaunch when this returns ``False``.
    """
    from tools.ac_harness.entry_launcher import terminate_process_tree_confirmed_absent

    if release_requested is not None and release_requested():
        raise _OperatorRelease

    def observe() -> bool:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        return acs_alive()

    safe = terminate_process_tree_confirmed_absent(
        "acs.exe",
        is_running=observe,
        timeout=timeout,
        poll=poll,
        absent_confirmations=2,
        clock=time.monotonic,
        sleep=time.sleep,
        log=lambda message: _log(f"acs.exe cleanup: {message}"),
    )
    if not safe:
        _log("ERROR: acs.exe absence could not be confirmed; relaunch aborted")
    return safe


def _hold_rig_until_acs_gone(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    retry_cleanup: Callable[[Callable[[], bool]], bool] | None = None,
    release_requested: Callable[[], bool] | None = None,
    poll: float = 1.0,
    allow_operator_release: bool = True,
    timeout: float | None = None,
) -> bool:
    """Keep machine-wide ownership after cleanup fails until the unsafe sim is gone.

    Returning from the launcher would release the OS lock and let a peer inherit a known-wedged
    ``acs.exe``. Keep retrying teardown while ownership is held. Ctrl-C is the only explicit
    operator escape hatch; as elsewhere in this launcher, it deliberately releases ownership.
    """
    _log(
        "UNSAFE RIG: acs.exe survived cleanup; retaining ownership and retrying "
        "(Ctrl-C explicitly releases)"
    )

    def cleanup() -> bool:
        if retry_cleanup is not None:
            return retry_cleanup(acs_alive)
        return _ensure_acs_gone(
            acs_alive,
            release_requested=release_requested if allow_operator_release else None,
        )

    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            _log("FATAL cleanup hold timed out; forcing process exit with rig lock retained")
            return False
        try:
            alive = acs_alive()
        except OSError as exc:
            _log(f"WARNING: acs.exe enumeration failed during cleanup hold: {exc}")
            alive = True
        if not alive:
            return True
        if allow_operator_release and release_requested is not None and release_requested():
            _log("Game Point explicitly released unsafe rig ownership; acs.exe may still be alive")
            return False
        try:
            cleaned = cleanup()
            if cleaned:
                try:
                    still_alive = acs_alive()
                except OSError as exc:
                    _log(f"WARNING: acs.exe cleanup confirmation failed: {exc}")
                    still_alive = True
                if not still_alive:
                    return True
            time.sleep(poll)
        except _OperatorRelease:
            if allow_operator_release:
                _log(
                    "Game Point explicitly released unsafe rig ownership; "
                    "acs.exe may still be alive"
                )
                return False
            _log("ignoring release during fatal controller cleanup; acs.exe must exit first")
            time.sleep(poll)
        except KeyboardInterrupt:
            if allow_operator_release:
                _log(
                    "operator explicitly released unsafe rig ownership; acs.exe may still be alive"
                )
                return False
            _log("ignoring Ctrl-C during fatal controller cleanup; acs.exe must exit first")
            time.sleep(poll)


def _hold_stable_session(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    release_requested: Callable[[], bool],
    *,
    poll: float = 1.0,
    maintenance: Callable[[], None] | None = None,
    read_state: Callable[[], tuple[int | None, bool | None, int | None]] | None = None,
    set_phase: Callable[[str], None] | None = None,
    wedge_seconds: float = DEFAULT_HOLD_WEDGE_SECONDS,
) -> bool:
    """Hold rig ownership for a stable session and report whether release was intentional.

    While holding, watch for a post-handoff render wedge (#630 Part A): graphics pinned while
    physics keeps advancing. On one, say so loudly and republish the rig phase as ``wedged`` so
    Game Point renders a distinct recovery state instead of continuing to present a frozen session
    as a healthy hold. Ownership is deliberately retained either way — a wedged ``acs.exe`` must
    not be inherited by a peer harness — so recovery stays the operator's/supervisor's call.
    """
    watch = StableSessionWatch(wedge_seconds) if read_state is not None else None
    wedge_phase_published = False
    try:
        while acs_alive() and not release_requested():
            if maintenance is not None:
                maintenance()
            if watch is not None and read_state is not None:
                if not watch.wedged:
                    gfx_packet, _ready, phys_packet = read_state()
                    if watch.observe(
                        gfx_packet=gfx_packet, phys_packet=phys_packet, now=time.monotonic()
                    ):
                        _log(
                            "WARNING: the handed-off session has WEDGED — the render packet has "
                            f"been pinned for >={wedge_seconds:.0f}s while PHYSICS keeps advancing "
                            "and acs.exe is alive (#627 §2 render freeze, not a pause). Holding "
                            "rig ownership; the session needs a relaunch to recover."
                        )
                # Keep retrying the durable phase write until it lands. A single swallowed OSError
                # would leave the lock metadata reading "stable" while the session is frozen — Game
                # Point would keep presenting a healthy handoff, which is precisely the #630 failure
                # this detection exists to end. The latch is never cleared by a retry.
                if watch.wedged and not wedge_phase_published and set_phase is not None:
                    try:
                        set_phase("wedged")
                        wedge_phase_published = True
                    except OSError as exc:
                        _log(f"WARNING: could not publish the wedged rig phase; retrying: {exc}")
            time.sleep(poll)
    except KeyboardInterrupt:
        _log("operator released rig ownership; AC left LIVE")
        return True
    if release_requested():
        _log("Game Point explicitly released rig ownership; AC left LIVE")
        return True
    _log("ERROR: stable AC session exited without an operator release")
    return False


def _make_rig_safe(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    release_requested: Callable[[], bool] | None = None,
    allow_operator_release: bool = True,
    hold_timeout: float | None = None,
) -> bool:
    """Attempt cleanup before allowing a release to drop machine-wide ownership."""
    # A pre-stability release reaches this path with its durable sentinel still present. Do not
    # pass that callback into the first cleanup: _ensure_acs_gone would raise before taskkill and
    # let a live/wedged acs.exe outlast the rig lock. Only the subsequent unsafe-hold loop treats
    # the sentinel as the operator's explicit escape hatch after one real teardown attempt.
    try:
        initially_alive = acs_alive()
    except OSError:
        initially_alive = True
    if not initially_alive:
        return True
    try:
        safe = _ensure_acs_gone(acs_alive)
    except (KeyboardInterrupt, _OperatorRelease):
        if allow_operator_release:
            raise
        _log("ignoring operator interrupt during fatal controller cleanup")
        safe = False
    if not safe:
        return _hold_rig_until_acs_gone(
            acs_alive,
            release_requested=release_requested,
            allow_operator_release=allow_operator_release,
            timeout=hold_timeout,
        )
    return True


def _run_with_safe_release(
    run: Callable[[], LaunchReport],
    acs_alive: Callable[[], bool],
    *,
    release_requested: Callable[[], bool] | None = None,
) -> LaunchReport:
    """Run the retry engine and make the rig safe before propagating any abnormal exit."""
    try:
        return run()
    except _OperatorRelease:
        # Release is only a safe "leave AC live" operation after the stability gate. During
        # retries, attempt cleanup first. The durable callback remains the no-console operator's
        # explicit escape hatch if taskkill cannot remove a wedged process.
        _make_rig_safe(acs_alive, release_requested=release_requested)
        raise
    except BaseException:
        _make_rig_safe(acs_alive, release_requested=release_requested)
        raise


def _probe_car0_drivable(  # pragma: no cover - Windows/rig-only
    *,
    timeout: float = 5.0,
    poll: float = 0.1,
    controller_factory: Callable[[], object] | None = None,
    release_requested: Callable[[], bool] | None = None,
    retain_telemetry_controller: Callable[[object], None] | None = None,
) -> bool:
    """Briefly handshake CSP Car0, the established oracle for a drivable session (#466).

    Creating ``CarControls0`` asks CSP to expose ``Car0``. The known pre-drive overlay never does,
    despite LIVE/not-in-pit and advancing packets. Close immediately after the probe so control is
    returned to the human driver before the stability window continues.
    """
    from tools.ac_harness.custom_ai import (
        ControllerCloseRetryError,
        close_controller_with_retries,
    )
    from tools.ac_harness.shared_memory import SharedMemoryUnavailable

    controller: object | None = None
    drivable = False
    try:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        if controller_factory is None:
            from tools.ac_harness.custom_ai import CustomAIController

            controller = CustomAIController(0)
        else:
            controller = controller_factory()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            if controller.read_car_data() is not None:  # type: ignore[attr-defined]
                drivable = True
                break
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll, remaining))
        else:
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            drivable = controller.read_car_data() is not None  # type: ignore[attr-defined]
    except (SharedMemoryUnavailable, OSError) as exc:
        _log(f"Car0 drivability probe unavailable: {exc}")
        drivable = False
    finally:
        if controller is not None:
            try:
                close_controller_with_retries(controller)  # type: ignore[arg-type]
            except ControllerCloseRetryError as exc:
                if exc.controls_retained:
                    raise _Car0ProbeCleanupError(
                        f"could not close Car0 drivability probe: {exc}",
                        controller,
                    ) from exc
                if retain_telemetry_controller is None:
                    raise _Car0ProbeTelemetryCleanupError(
                        f"Car0 probe retained a read-only telemetry mapping: {exc}",
                        controller,
                    ) from exc
                retain_telemetry_controller(controller)
                _log(
                    "WARNING: Car0 probe released control ownership but retained a read-only "
                    f"telemetry mapping after retries: {exc}"
                )
            except BaseException as exc:
                raise _Car0ProbeCleanupError(
                    "Car0 probe cleanup was interrupted with control ownership unknown: "
                    f"{type(exc).__name__}: {exc}",
                    controller,
                ) from exc
    return drivable


def _retry_telemetry_cleanup_holds(controllers: list[object]) -> None:
    """Retry retained read-only controller mappings without losing their owning references."""
    from tools.ac_harness.custom_ai import (
        ControllerCloseRetryError,
        close_controller_with_retries,
    )

    retained: list[object] = []
    for controller in controllers:
        try:
            close_controller_with_retries(controller)  # type: ignore[arg-type]
        except ControllerCloseRetryError as exc:
            if exc.controls_retained:
                raise _Car0ProbeCleanupError(
                    f"retained telemetry cleanup regained CarControls ownership: {exc}",
                    controller,
                ) from exc
            retained.append(controller)
    controllers[:] = retained


def _watch_live(  # pragma: no cover - rig-only
    read_state: Callable[
        [],
        tuple[int | None, bool | None]
        | tuple[int | None, bool | None, bool | None]
        | tuple[int | None, bool | None, bool | None, int | None],
    ],
    acs_alive: Callable[[], bool],
    *,
    go_live_timeout: float,
    stability_window: float,
    poll_interval: float = 1.0,
    pause_budget: float = DEFAULT_PAUSE_BUDGET,
) -> LaunchVerdict:
    """Sample until the attempt resolves, then classify. Streams samples into :func:`classify`.

    The wall-clock budget is ``go_live_timeout + stability_window + 30`` **plus the pause hold**
    ``classify`` reports (capped at ``pause_budget``): a long alt-tab must stay PENDING, never
    FROZE a healthy paused session at a fixed deadline — the exact failure #630 Part B set out to
    stop (#637 Codex P1 + self-hosted daemon HIGH). A dual-stream hang outlasting the pause
    budget stops being a hold inside ``classify`` and fails via the ordinary stall/not-ready
    paths, so the extension cannot hide a real freeze either.
    """
    samples: list[Sample] = []
    started_at = time.monotonic()
    budget = go_live_timeout + stability_window + 30.0
    paused = 0.0
    while time.monotonic() < started_at + budget + min(paused, pause_budget):
        samples.append(_sample_now(read_state, acs_alive))
        sink: list[float] = []
        verdict = classify(
            samples,
            go_live_timeout=go_live_timeout,
            stability_window=stability_window,
            started_at=started_at,
            pause_budget=pause_budget,
            pause_sink=sink,
        )
        if verdict is not LaunchVerdict.PENDING:
            return verdict
        if sink:
            paused = sink[-1]
        time.sleep(poll_interval)
    return LaunchVerdict.FROZE


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and >= 0")
    return parsed


def _publish_stable_phase(set_phase: Callable[[str], None]) -> bool:
    """Publish READY metadata without destroying an already-proven live session on I/O failure."""
    try:
        set_phase("stable")
    except OSError as exc:
        _log(
            "WARNING: could not publish stable rig phase; retaining the proven live session "
            f"under stabilizing ownership: {exc}"
        )
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only entrypoint
    parser = argparse.ArgumentParser(
        description="Launch AC, retry past the CSP init livelock (#619), hold a stable session"
    )
    parser.add_argument("--car", required=True, help="car id, e.g. ks_porsche_911_gt3_r_2016")
    parser.add_argument("--track", required=True, help="track id, e.g. spa")
    parser.add_argument("--layout", default=None, help="track layout for multi-layout circuits")
    parser.add_argument(
        "--cm-exe",
        type=Path,
        default=None,
        help="Content Manager.exe path (default: standard Program Files install)",
    )
    parser.add_argument(
        "--stability-window", type=_positive_float, default=DEFAULT_STABILITY_WINDOW
    )
    parser.add_argument("--go-live-timeout", type=_positive_float, default=DEFAULT_GO_LIVE_TIMEOUT)
    parser.add_argument("--max-attempts", type=_positive_int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--rig-lock-timeout",
        type=_non_negative_float,
        default=1.0,
        help="seconds to wait for the machine-wide rig lock (default: 1.0)",
    )
    parser.add_argument(
        "--trials",
        type=_positive_int,
        default=None,
        help=(
            "measurement mode (#627 §9.2): run exactly N attempts regardless of verdict, record "
            "verdict + uptime + launch index for every trial, tear the rig down at the end, and "
            "exit 0 once all N verdicts are recorded. WARNING: hard-kills acs.exe between trials "
            "(#627 §6.5) — the measurement itself may degrade the rig"
        ),
    )
    parser.add_argument(
        "--no-hold",
        action="store_true",
        help=(
            "exit immediately after the stability gate instead of holding rig ownership: AC is "
            "left LIVE but unowned (scripted/measurement use — a peer harness may claim it)"
        ),
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_path",
        help="write the machine-readable run report (per-attempt log included) to this path",
    )
    parser.add_argument("--rig-lock-path", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--rig-release-path", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    from tools.ac_harness.entry_launcher import (
        ContentManagerActuator,
        EntryLaunchUnsupported,
    )
    from tools.ac_harness.preset_utils import build_practice_preset
    from tools.ac_harness.rig_lock import (
        RigSessionBusy,
        RigSessionLock,
        RigSessionOwner,
        default_rig_session_lock_path,
    )
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable
    from tools.ac_harness.window_utils import minimize_foreground_window

    def read_state() -> tuple[int | None, bool | None, int | None]:
        """Render packet, LIVE+not-in-pit readiness, and the PHYSICS packet from one snapshot.

        The physics packetId is the reliable pause signal (it stops at a pause/menu but keeps
        advancing during a render wedge); ``classify`` uses its stagnation for #630 Part B.
        """
        try:
            reader = SharedMemoryReader(with_physics=True)
        except (SharedMemoryUnavailable, OSError):
            return None, None, None
        try:
            graphics = reader.read_graphics()
            physics = reader.read_physics()
            ready = graphics.is_live and not graphics.is_in_pit
            return graphics.packet_id, ready, (physics.packet_id if physics else None)
        except (SharedMemoryUnavailable, OSError):
            return None, None, None
        finally:
            reader.close()

    acs_alive = _ResettableProcessLivenessProbe("acs.exe")
    telemetry_cleanup_holds: list[object] = []

    def acs_present() -> bool:
        return _strict_process_running("acs.exe")

    lock_path = args.rig_lock_path or default_rig_session_lock_path()
    release_path = args.rig_release_path or (lock_path.parent / "rig-session.release")

    if args.json_path is not None:
        try:
            # Checkout writes are limited to gitignored ``.scratch`` — never the whole tree
            # (tracked files / ``.git``) (#657 Qodo).
            args.json_path = resolve_report_path(
                args.json_path,
                approved_roots=(lock_path.parent, repo_checkout_root() / ".scratch"),
            )
        except ValueError as exc:
            _log(f"launch aborted: {exc}")
            return 2

    def release_requested() -> bool:
        return release_path.exists()

    rig_lock = RigSessionLock(
        lock_path,
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd=str(Path.cwd()),
            car=args.car,
            track=args.track,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            session_kind="resilient_launch",
            phase="stabilizing",
        ),
        timeout=args.rig_lock_timeout,
    )
    try:
        rig_lock.acquire()
    except RigSessionBusy as exc:
        _log(f"RIG BUSY — {exc}")
        return 3
    _log(f"rig lock acquired -> {rig_lock.path}")
    preset: Path | None = None
    try:
        if args.rig_release_path is None:
            try:
                release_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"WARNING: could not clear stale release request {release_path}: {exc}")
        # The generated preset is application state: keep it under the same approved per-user
        # Harness root as the cross-worktree lock, and create it only after ownership is acquired.
        # A PID-scoped filename also prevents stale runs from sharing one mutable preset path.
        preset_dir = lock_path.parent / "presets"
        preset_dir.mkdir(parents=True, exist_ok=True)
        preset = preset_dir / f"resilient-launch-{os.getpid()}.cmpreset"
        preset.write_text(
            build_practice_preset(args.car, args.track, start_type="START", layout=args.layout),
            encoding="utf-8",
        )
        _log(f"preset -> {preset}")

        cm_exe = args.cm_exe or ContentManagerActuator.DEFAULT_CM_EXE
        actuator = ContentManagerActuator(preset=preset, cm_exe=cm_exe)
        if not actuator.cm_exe.is_file():
            _log(f"launch aborted: Content Manager executable not found: {actuator.cm_exe}")
            return 1

        def watch_attempt(attempt: int) -> LaunchVerdict:
            if release_requested():
                raise _OperatorRelease
            _log(f"attempt {attempt}/{args.max_attempts}: launching via Content Manager")
            # A wedged acs from the previous attempt must be GONE before relaunching.
            if not _ensure_acs_gone(acs_present, release_requested=release_requested):
                raise _AcsCleanupTimeout("acs.exe remained alive after the bounded cleanup wait")
            # The previous attempt's real process sighting must not leak into the next attempt's
            # pre-spawn absence. Reset only AFTER cleanup has used that history to confirm the old
            # process is gone; this attempt then earns its own first real acs.exe sighting.
            acs_alive.reset()
            # The quick-drive URL is IPC to a RUNNING CM. Do not spend a full attempt when its
            # executable is absent or startup failed.
            if not _ensure_cm_running(
                actuator.cm_exe,
                release_requested=release_requested,
            ):
                return LaunchVerdict.NEVER_LIVE
            if release_requested():
                raise _OperatorRelease
            minimize_foreground_window()
            if release_requested():
                raise _OperatorRelease
            try:
                # Cleanup already normalized acs.exe above. Calling relaunch() here would add a
                # second uninterruptible taskkill window between the final release check and launch.
                actuator.launch()
            except (OSError, EntryLaunchUnsupported) as exc:
                _log(f"attempt {attempt}: Content Manager launch failed: {exc}")
                return LaunchVerdict.NEVER_LIVE
            readiness = AttemptReadiness(
                lambda: _probe_car0_drivable(
                    release_requested=release_requested,
                    retain_telemetry_controller=telemetry_cleanup_holds.append,
                )
            )

            def read_attempt_state() -> tuple[int | None, bool | None, bool | None, int | None]:
                """Report shared memory; trust readiness only once the packet proves a live owner.

                No process-liveness probe is consulted here on purpose (see
                :class:`SectionOwnershipGate`): a corpse's fields — including ``is_live`` — are
                trusted only after the render packet ADVANCES, which only a live process can do.
                ``read_state`` degrades a shared-memory failure to ``(None, None, None)``, which
                ``classify`` treats as "no observation"; process death is ended by ``classify`` via
                the debounced ``Sample.acs_alive``. The physics packet rides straight through so
                ``classify`` can read a pause from its stagnation (#630 Part B).
                """
                _retry_telemetry_cleanup_holds(telemetry_cleanup_holds)
                if release_requested():
                    raise _OperatorRelease

                packet, entry_ready, phys_packet = read_state()
                ready, drivable = readiness.observe(packet=packet, entry_ready=entry_ready)
                return packet, ready, drivable, phys_packet

            try:
                verdict = _watch_live(
                    read_attempt_state,
                    acs_alive,
                    go_live_timeout=args.go_live_timeout,
                    stability_window=args.stability_window,
                )
            except _Car0NotDrivable:
                # CM did start a LIVE session; only the Car0 handoff failed. Treat this as a bad
                # rendered attempt so it cannot advance the stale-CM/never-live restart streak.
                verdict = LaunchVerdict.FROZE
            _log(f"attempt {attempt}: {verdict}")
            return verdict

        def cold_restart_cm() -> None:
            _log("two consecutive never_live — cold-restarting Content Manager (stale preset IPC)")
            if release_requested():
                raise _OperatorRelease
            actuator.restart_content_manager()
            if not _wait_process_exit(
                actuator.cm_exe.name,
                release_requested=release_requested,
            ):
                raise _ContentManagerRestartTimeout(
                    "Content Manager remained alive after the bounded shutdown wait"
                )

        trials_mode = args.trials is not None
        try:
            report = _run_with_safe_release(
                lambda: run_retry_loop(
                    watch_attempt,
                    max_attempts=args.trials if trials_mode else args.max_attempts,
                    on_never_live_streak=cold_restart_cm,
                    stop_on_stable=not trials_mode,
                    uptime_hours=_machine_uptime_hours,
                ),
                acs_present,
                release_requested=release_requested,
            )
        except _OperatorRelease:
            _log("Game Point release interrupted launch; AC was made safe before ownership release")
            return 1
        except _Car0ProbeCleanupError as exc:
            _log(f"launch aborted: {exc}")
            # close() retained a native CarControls mapping. Normal return would run the finally
            # block and release the machine lock first; terminate the process so Windows closes
            # mapping and lock together. The exception retains the controller until that boundary.
            # Re-confirm AC teardown here even though _run_with_safe_release already attempted it:
            # this fatal boundary ignores both Game Point release and Ctrl-C, and cannot make
            # ownership available while a surviving acs.exe could inherit the stale mapping.
            _make_rig_safe(
                acs_present,
                allow_operator_release=False,
                hold_timeout=30.0,
            )
            os._exit(1)
        except _AcsCleanupTimeout as exc:
            _log(f"launch aborted: {exc}")
            return 1
        except _ContentManagerRestartTimeout as exc:
            _log(f"restart aborted: {exc}")
            return 1
        report = replace(
            report,
            launch={
                "car": args.car,
                "track": args.track,
                "layout": args.layout,
                "stability_window": args.stability_window,
                "go_live_timeout": args.go_live_timeout,
                "trials_per_invocation": int(args.trials) if args.trials is not None else 1,
            },
        )
        report_written = True
        if args.json_path is not None:
            report_written = _write_report_json(report, args.json_path)
            if not report_written and not trials_mode:
                # Do not tear down a STABLE session over a missing artifact — that contradicts
                # --no-hold (leave AC LIVE for a peer) and kills the operator's earned session
                # (#657 daemon HIGH). Exit nonzero later so we never claim a clean measurement.
                _log(
                    "WARNING: report JSON could not be written — continuing hold/--no-hold "
                    "without claiming a clean measurement artifact"
                )
        if trials_mode:
            # #627 §9.2 — the deliverable of a measurement run is the recorded denominator, not a
            # held session. Say every verdict out loud, leave the rig CLEAN (a stable final trial
            # must not strand an unowned acs.exe), and exit 0 because the measurement completed.
            for record in report.attempts_log:
                uptime = "?" if record.uptime_h is None else f"{record.uptime_h:.3f}h"
                _log(
                    f"trial {record.attempt}/{args.trials}: {record.verdict} "
                    f"elapsed={record.elapsed_s:.1f}s uptime={uptime}"
                )
            _log(
                f"trials complete: stable {report.stable}/{report.attempts} "
                f"({report._counts()}); hard kills between trials — see #627 §6.5"
            )
            rig_safe = _make_rig_safe(acs_present, release_requested=release_requested)
            if not rig_safe:
                # The advertised end-of-run teardown failed: a live (possibly wedged) acs.exe is
                # about to outlast the released rig lock. A measurement run must not read as
                # successful over that (#646 review P1, round 2).
                _log("TRIALS FAILED: end-of-run teardown could not confirm acs.exe exit")
                return 1
            if not report_written:
                # In measurement mode the machine-readable record IS the deliverable. An
                # automated run must not read as successful when the requested record was never
                # produced (#646 review P1) — the per-trial log lines above remain as salvage.
                _log("TRIALS FAILED: the requested report JSON could not be written")
                return 1
            return 0
        _log(report.summary())
        if not report.succeeded:
            # A FROZE terminal verdict deliberately leaves acs.exe alive so the watcher can
            # diagnose it. Once the attempt budget is exhausted, kill that corpse while the
            # machine-wide lock is still held; peers must never inherit a wedged sim.
            _make_rig_safe(acs_present, release_requested=release_requested)
            return 1

        phase_published = _publish_stable_phase(rig_lock.set_phase)

        if args.no_hold:
            # Scripted/measurement callers own their own lifecycle. AC is left LIVE; the rig lock
            # releases in the finally block, so a peer harness may legitimately claim the session.
            _log(
                "stability gate passed; exiting without hold (--no-hold) — AC left LIVE, "
                "rig ownership released"
            )
            return stable_session_exit_code(report_written=report_written)

        # The stable session belongs to this operator-facing launcher until AC exits. Releasing
        # the cross-worktree lock immediately after the gate would let a peer harness kill the
        # human driver's live session. Ctrl-C is an explicit ownership release and leaves AC up.
        _log(
            "stable session handed to operator; holding rig ownership until AC exits "
            f"(Ctrl-C releases; phase={'stable' if phase_published else 'stabilizing'})"
        )
        try:
            intentional_release = _hold_stable_session(
                acs_alive,
                release_requested,
                maintenance=lambda: _retry_telemetry_cleanup_holds(telemetry_cleanup_holds),
                read_state=read_state,
                set_phase=rig_lock.set_phase,
            )
        except _Car0ProbeCleanupError as exc:
            _log(f"stable-session cleanup aborted: {exc}")
            _make_rig_safe(
                acs_present,
                allow_operator_release=False,
                hold_timeout=30.0,
            )
            os._exit(1)
        return stable_session_exit_code(
            report_written=report_written,
            intentional_release=intentional_release,
        )
    finally:
        if preset is not None:
            try:
                preset.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"WARNING: could not remove generated preset {preset}: {exc}")
        try:
            release_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log(f"WARNING: could not remove release request {release_path}: {exc}")
        rig_lock.release()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
