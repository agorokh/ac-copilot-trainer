"""Coaching ledger: the pass-to-pass memory that makes the coach *paced* and *self-silencing*.

This is the bridge the council called the keystone — it sits between the per-corner diagnosis
(:mod:`coaching_diagnosis`) and the anticipatory voice. It holds, per corner, the root error the
driver keeps making, and decides WHEN to actually speak:

* **Hysteresis** — a root earns a spoken PRIME only after it is the #1 error for
  ``hysteresis`` consecutive *valid* passes (kills single-noisy-lap flip-flop; council Mistral 4A).
* **Lap budget** — at most ``lap_budget`` non-emergency cues per lap, spent on the highest
  time-loss corners (council: don't drown the driver).
* **Assess laps** — the first ``assess_laps`` laps are silent (a real instructor watches first; and
  there is no prior pass to coach from).
* **Acknowledge & retire** — when a primed root is fixed, say it once ("Good.") then go silent;
  silence is the reward. **Retention**: a retired corner is still monitored and re-arms instantly if
  the habit regresses (anti-amnesia; council Gemini).

Pure stdlib, no telemetry, no I/O — fully unit-tested in isolation. The realtime observer drives it:
``begin_lap`` → (per corner exit) ``record_pass`` → (per corner approach) ``due_prime``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError

HYSTERESIS_PASSES = 2  # consecutive valid passes a root must lead before it earns a PRIME
LAP_CUE_BUDGET = 4  # max non-SAVE cues spoken per lap
RETIRE_AFTER_FIXES = 2  # consecutive clean passes before a corner retires to silence
ASSESS_LAPS = 2  # leading laps that stay silent (watch first)


class Status(StrEnum):
    DETECTING = "detecting"  # accumulating hysteresis; not yet eligible to speak
    ARMED = "armed"  # hysteresis met; will PRIME on next approach (budget permitting)
    PRIMED = "primed"  # PRIME spoken; the driver is still making the mistake
    HEALING = "healing"  # the primed root just cleared — silent, confirming the fix holds
    RETIRED = "retired"  # fixed and silent — still monitored for regression


@dataclass
class CornerState:
    corner: int
    root: RootError = RootError.NONE
    consecutive: int = 0  # consecutive valid passes the current root has led
    status: Status = Status.DETECTING
    time_lost_s: float = 0.0
    coached_count: int = 0
    clean_streak: int = 0  # consecutive passes the primed root was absent (fixed)


@dataclass
class CueEvent:
    """A speech the ledger decided to emit outside the PRIME path (acknowledge / refocus)."""

    corner: int
    root: RootError
    kind: str  # 'confirm' | 'refocus'


@dataclass
class CoachingLedger:
    hysteresis: int = HYSTERESIS_PASSES
    lap_budget: int = LAP_CUE_BUDGET
    retire_after: int = RETIRE_AFTER_FIXES
    assess_laps: int = ASSESS_LAPS
    _states: dict[int, CornerState] = field(default_factory=dict)
    _lap: int = 0
    _spoken_this_lap: int = 0
    _speak_set: set[int] = field(default_factory=set)

    def clear_session(self) -> None:
        """Reset on pit-exit / session restart — the driver and conditions are starting fresh."""
        self._states.clear()
        self._lap = 0
        self._spoken_this_lap = 0
        self._speak_set.clear()

    def begin_lap(self, lap: int) -> None:
        """Start a lap: reset the per-lap budget and pick the speak-set (top armed corners)."""
        self._lap = lap
        self._spoken_this_lap = 0
        # this lap we will SPEAK only corners that are armed or still-unfixed-primed, ranked by loss
        speakable = [
            s
            for s in self._states.values()
            if s.status == Status.ARMED
            or (s.status == Status.PRIMED and s.clean_streak == 0)
        ]
        speakable.sort(key=lambda s: s.time_lost_s, reverse=True)
        self._speak_set = {s.corner for s in speakable[: self.lap_budget]}

    def record_pass(
        self, corner: int, diag: Diagnosis, *, time_lost_s: float, valid: bool
    ) -> list[CueEvent]:
        """Record a corner pass (call on corner exit). ``valid`` is the lap-validity gate — an
        off-track / out-lap / much-slower pass must not poison the ledger (council Gemini §1).
        Returns acknowledge cues to speak on the following straight.
        """
        if not valid:
            return []
        st = self._states.setdefault(corner, CornerState(corner))
        events: list[CueEvent] = []
        root = diag.root
        if root != RootError.NONE:
            st.time_lost_s = time_lost_s

        # --- was this corner being coached, and did the coached root clear? ---
        being_coached = st.status in (Status.PRIMED, Status.HEALING)
        if being_coached:
            if root == st.root:  # still making the same mistake → regression/persistence
                st.clean_streak = 0
                st.status = Status.PRIMED
                st.consecutive += 1
                return events
            # the coached root is absent this pass → a clean pass
            st.clean_streak += 1
            if st.clean_streak == 1:
                events.append(CueEvent(corner, st.root, "confirm"))  # "Good." once
                st.status = Status.HEALING
            if st.clean_streak >= self.retire_after:
                st.status = Status.RETIRED
            return events

        # --- a RETIRED corner regressing into a real error → re-arm immediately (anti-amnesia) ---
        if st.status == Status.RETIRED:
            if root != RootError.NONE:
                st.root = root
                st.consecutive = 1
                st.clean_streak = 0
                st.status = Status.ARMED
            return events

        # --- DETECTING / ARMED: accumulate hysteresis on the current root ---
        if root == RootError.NONE:
            st.root = RootError.NONE
            st.consecutive = 0
            return events
        if root == st.root:
            st.consecutive += 1
        else:
            st.root = root
            st.consecutive = 1
        if st.consecutive >= self.hysteresis and st.status == Status.DETECTING:
            st.status = Status.ARMED
        return events

    def due_prime(self, corner: int) -> RootError | None:
        """Call when the car reaches a corner's PRIME anchor. Returns the root to SPEAK now (and
        marks it spoken, spending lap budget), or ``None`` to stay silent.
        """
        if self._lap <= self.assess_laps:  # watch-first laps
            return None
        if corner not in self._speak_set or self._spoken_this_lap >= self.lap_budget:
            return None
        st = self._states.get(corner)
        if st is None or st.status not in (Status.ARMED, Status.PRIMED):
            return None
        self._spoken_this_lap += 1
        st.status = Status.PRIMED
        st.coached_count += 1
        return st.root

    def armed_root(self, corner: int) -> RootError | None:
        """Peek the root this corner would PRIME this lap (no side effect) — the observer uses it to
        know WHICH action-point anchor to fire at before committing via :meth:`due_prime`.
        """
        if self._lap <= self.assess_laps or corner not in self._speak_set:
            return None
        st = self._states.get(corner)
        if st is None or st.status not in (Status.ARMED, Status.PRIMED):
            return None
        return st.root

    # --- introspection (debrief screen / tests) ---
    def state(self, corner: int) -> CornerState | None:
        return self._states.get(corner)

    def focus_corner(self) -> int | None:
        """The single biggest remaining un-retired root — the lap's headline focus (ARC cue)."""
        live = [
            s
            for s in self._states.values()
            if s.status in (Status.ARMED, Status.PRIMED) and s.root != RootError.NONE
        ]
        if not live:
            return None
        return max(live, key=lambda s: s.time_lost_s).corner
