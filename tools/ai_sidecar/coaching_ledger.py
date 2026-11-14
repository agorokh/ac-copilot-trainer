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

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from tools.ai_sidecar.coachable_frontier import HumanDrillTarget
from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError, severity
from tools.ai_sidecar.lap_dynamics import CornerSignature
from tools.lap_qualification import Qualification

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
    register: str = "urgent"  # magnitude tier of the latest diagnosis (P2/#381)
    intensity: float = 0.5


@dataclass
class CueEvent:
    """A speech the ledger decided to emit outside the PRIME path (acknowledge)."""

    corner: int
    root: RootError
    kind: str  # 'confirm' (the session-arc 'refocus' cue is a deferred follow-up, not yet emitted)


@dataclass
class DrillBlock:
    """One frozen corner/stage, three cued trials then two retention trials.

    Staging is not a valid trial. Only a distinct completed, qualified human lap
    can commit it. Every distinct completion consumes the bounded lap budget,
    including invalid, undelivered, missing and otherwise rejected observations.
    """

    target: HumanDrillTarget
    max_laps: int = 10
    practice_permit: Any = field(default=None, repr=False)
    phase: str = "cued"
    reason: str = "awaiting_completed_human_lap"
    attempted_laps: int = 0
    cued_trials: list[bool] = field(default_factory=list)
    retention_trials: list[bool] = field(default_factory=list)
    _session_uuid: str | None = None
    _seen_laps: set[str] = field(default_factory=set)
    _pending: dict[str, tuple[CornerSignature, float, bool] | None] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.phase in {"cued", "retention"}

    @property
    def retention(self) -> bool:
        return self.phase == "retention"

    @property
    def suppress_instructional_cues(self) -> bool:
        # A finished/aborted experiment stays silent until its owner resets it.
        return self.phase != "cued"

    def abort(self, reason: str) -> None:
        if self.active:
            self.phase, self.reason = "aborted", reason
            self._pending.clear()

    def stage(
        self,
        signature: CornerSignature,
        *,
        corner_time_s: float,
        lap_uuid: str,
        off_track: bool = False,
    ) -> bool:
        if not self.active or signature.index != self.target.corner or not lap_uuid:
            return False
        if lap_uuid in self._seen_laps:
            return False
        if lap_uuid in self._pending:
            self._pending[lap_uuid] = None
            self.reason = "duplicate_corner_observation"
            return False
        self._pending[lap_uuid] = (replace(signature), corner_time_s, off_track)
        return True

    def _result(self, reason: str, *, advanced: bool = False) -> dict[str, Any]:
        self.reason = reason
        if self.active and self.attempted_laps >= self.max_laps:
            self.abort("lap_budget_exhausted")
        return {"advanced": advanced, **self.to_dict()}

    def complete_lap(
        self,
        *,
        lap_uuid: str,
        session_uuid: str,
        combo: tuple[str, str, str],
        qualification: Qualification,
        valid: bool,
        off_track: bool = False,
        cued: bool = False,
        condition_eligible: bool = False,
    ) -> dict[str, Any]:
        if not self.active:
            return {"advanced": False, **self.to_dict()}
        if not isinstance(lap_uuid, str) or not lap_uuid:
            self.attempted_laps += 1
            return self._result("lap_identity_unavailable")
        if lap_uuid in self._seen_laps:
            return self._result("duplicate_lap")
        self._seen_laps.add(lap_uuid)
        self.attempted_laps += 1
        pending = self._pending.pop(lap_uuid, None)
        if not isinstance(combo, (tuple, list)) or tuple(combo) != self.target.combo:
            return self._result("drill_combo_mismatch")
        if (
            not isinstance(session_uuid, str)
            or not session_uuid
            or (self._session_uuid is not None and session_uuid != self._session_uuid)
        ):
            self.abort("drill_session_changed")
            return self._result(self.reason)
        if off_track is True or (pending is not None and pending[2] is True):
            self.phase = "failed"
            return self._result("off_track")
        if off_track is not False or (pending is not None and pending[2] is not False):
            return self._result("off_track_evidence_unavailable")
        accepted = (
            getattr(qualification, "allowed", False) is True
            and getattr(qualification, "authority", None) == "human"
        )
        if self.target.practice_only and self.practice_permit is not None:
            from tools.human_session import HumanSessionPermit
            from tools.lap_qualification import is_practice_human

            accepted = (
                isinstance(self.practice_permit, HumanSessionPermit)
                and getattr(qualification, "allowed", False) is True
                and is_practice_human(qualification)
            )
        if not accepted or valid is not True:
            return self._result("completed_qualified_human_lap_required")
        if condition_eligible is not True:
            return self._result("condition_ineligible")
        if pending is None:
            return self._result("target_corner_observation_missing_or_duplicate")
        if self.phase == "cued" and cued is not True:
            return self._result("instruction_not_delivered")
        if self.phase == "retention" and cued is not False:
            return self._result("retention_instruction_contamination")
        self._session_uuid = session_uuid
        signature, corner_time_s, _ = pending
        assessment = self.target.assess(signature, corner_time_s=corner_time_s)
        if not assessment["eligible"]:
            return self._result(assessment["reason"])
        if assessment["reason"] in {"exit_speed_degraded", "corner_time_degraded"}:
            self.phase = "failed"
            return self._result(assessment["reason"])
        if self.phase == "cued":
            self.cued_trials.append(bool(assessment["success"]))
            if len(self.cued_trials) == 3:
                if sum(self.cued_trials) < 2:
                    self.phase = "failed"
                    return self._result("cued_target_not_demonstrated", advanced=True)
                self.phase = "retention"
        else:
            self.retention_trials.append(bool(assessment["success"]))
            if len(self.retention_trials) == 2:
                self.phase = "passed" if all(self.retention_trials) else "failed"
                return self._result(
                    "retention_demonstrated"
                    if self.phase == "passed"
                    else "retention_target_reverted",
                    advanced=True,
                )
        return self._result(assessment["reason"], advanced=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": True,
            "active": self.active,
            "phase": self.phase,
            "reason": self.reason,
            "target": self.target.to_dict(),
            "attempted_laps": self.attempted_laps,
            "max_laps": self.max_laps,
            "cued_attempts": len(self.cued_trials),
            "cued_successes": sum(self.cued_trials),
            "retention_attempts": len(self.retention_trials),
            "retention_successes": sum(self.retention_trials),
            "instructional_cues_suppressed": self.suppress_instructional_cues,
        }


@dataclass
class CoachingLedger:
    hysteresis: int = HYSTERESIS_PASSES
    lap_budget: int = LAP_CUE_BUDGET
    retire_after: int = RETIRE_AFTER_FIXES
    assess_laps: int = ASSESS_LAPS
    drills_enabled: bool = False
    _states: dict[int, CornerState] = field(default_factory=dict)
    _lap: int = 0
    _spoken_this_lap: int = 0
    _speak_set: set[int] = field(default_factory=set)
    drill: DrillBlock | None = field(default=None, init=False)

    @property
    def drill_active(self) -> bool:
        return self.drill is not None and self.drill.active

    @property
    def drill_retention(self) -> bool:
        return self.drill is not None and self.drill.retention

    @property
    def drill_target(self) -> HumanDrillTarget | None:
        return self.drill.target if self.drill is not None else None

    @property
    def suppress_instructional_cues(self) -> bool:
        return self.drill is not None and self.drill.suppress_instructional_cues

    def drill_status(self) -> dict[str, Any]:
        if self.drill is None:
            return {
                "configured": self.drills_enabled,
                "active": False,
                "reason": "no_drill_started",
            }
        return self.drill.to_dict()

    def start_drill(
        self, target: HumanDrillTarget, *, max_laps: int = 10, practice_permit: Any = None
    ) -> DrillBlock:
        if not self.drills_enabled:
            raise ValueError("drills_disabled")
        if self.drill is not None:
            raise ValueError("drill_already_started")
        if type(max_laps) is not int or not 1 <= max_laps <= 10:
            raise ValueError("drill_lap_budget_invalid")
        if target.practice_only:
            from tools.human_session import HumanSessionPermit

            if not isinstance(practice_permit, HumanSessionPermit):
                raise ValueError("practice_permit_required")
        self.drill = DrillBlock(target, max_laps=max_laps, practice_permit=practice_permit)
        self._states[target.corner] = CornerState(
            target.corner, root=RootError(target.root), status=Status.ARMED
        )
        return self.drill

    def stage_drill_pass(
        self,
        signature: CornerSignature,
        *,
        corner_time_s: float,
        lap_uuid: str,
        off_track: bool = False,
    ) -> bool:
        return self.drill is not None and self.drill.stage(
            signature, corner_time_s=corner_time_s, lap_uuid=lap_uuid, off_track=off_track
        )

    def complete_drill_lap(self, **kwargs: Any) -> dict[str, Any]:
        if self.drill is None:
            return self.drill_status()
        return self.drill.complete_lap(**kwargs)

    def clear_session(self) -> None:
        """Reset on pit-exit / session restart — the driver and conditions are starting fresh."""
        self._states.clear()
        self._lap = 0
        self._spoken_this_lap = 0
        self._speak_set.clear()
        if self.drill is not None:
            self.drill.abort("session_reset")

    def begin_lap(self, lap: int) -> None:
        """Start a lap: reset the per-lap budget and pick the speak-set (top armed corners)."""
        self._lap = lap
        self._spoken_this_lap = 0
        if self.drill is not None:
            self._speak_set = {self.drill.target.corner} if self.drill.phase == "cued" else set()
            return
        # this lap we will SPEAK only corners that are armed or still-unfixed-primed, ranked by loss
        speakable = [
            s
            for s in self._states.values()
            if s.status == Status.ARMED or (s.status == Status.PRIMED and s.clean_streak == 0)
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
        if self.drill is not None or not valid:
            return []
        st = self._states.setdefault(corner, CornerState(corner))
        events: list[CueEvent] = []
        root = diag.root
        if root != RootError.NONE:
            st.time_lost_s = time_lost_s
            st.register, st.intensity = severity(diag)  # magnitude tier for the next PRIME (P2)

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
        if self.drill is not None:
            if (
                self.drill.phase != "cued"
                or corner != self.drill.target.corner
                or self._spoken_this_lap >= 1
            ):
                return None
            self._spoken_this_lap += 1
            return RootError(self.drill.target.root)
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
        if self.drill is not None:
            if self.drill.phase == "cued" and corner == self.drill.target.corner:
                return RootError(self.drill.target.root)
            return None
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
        if self.drill is not None:
            return self.drill.target.corner if self.drill.active else None
        live = [
            s
            for s in self._states.values()
            if s.status in (Status.ARMED, Status.PRIMED) and s.root != RootError.NONE
        ]
        if not live:
            return None
        return max(live, key=lambda s: s.time_lost_s).corner
