"""Completed-human-lap evidence adapter for the existing coaching ledger's drill block."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

from tools.ai_sidecar.coachable_frontier import FrontierError, build_human_drill_target
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.lap_dynamics import CornerSignature
from tools.lap_qualification import Qualification, archive_combo


def _number(value: Any) -> float | None:
    try:
        return float(value) if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


@dataclass
class _LapWindow:
    start_min: float
    start_max: float
    last_tick: float
    full_start: bool
    continuous: bool = True
    end_min: float | None = None
    end_max: float | None = None


@dataclass
class PracticeSession:
    """One bounded practice block; the ledger remains the trial/state authority.

    Live identity windows join actual local voice dispatches to native archive ordinals.
    An interval with a transport gap or an ambiguous boundary cannot certify a trial.
    Baseline/target observations come from completed immutable human archives only.
    """

    ledger: CoachingLedger
    combo: tuple[str, str, str]
    reference_signatures: dict[int, CornerSignature]
    reference_qualification: Qualification
    reference_identity: str
    drill_id: str
    reason: str = "qualified_human_lap_required"
    _phase: str = "warmup"
    _session: str | None = None
    _first_ordinal: int | None = None
    _context: tuple[str, int] | None = None
    _windows: dict[tuple[str, int], _LapWindow] = field(default_factory=dict)
    _voice: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=256))
    _seen: set[tuple[str, int]] = field(default_factory=set)
    _baselines: list[tuple[str, Qualification, dict[int, tuple[CornerSignature, float]]]] = field(
        default_factory=list
    )
    _hold: str = "native_lap_context_required"
    _terminal: bool = False
    _evidence: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.reference_signatures = {
            key: replace(value) for key, value in self.reference_signatures.items()
        }
        self.ledger.drills_enabled = True
        if (
            not self.reference_qualification.allowed
            or self.reference_qualification.authority != "human"
        ):
            self._terminal, self._phase, self.reason = (
                True,
                "unavailable",
                "qualified_human_reference_required",
            )

    @property
    def instruction_allowed(self) -> bool:
        if self.ledger.drill is None:
            return not self._terminal  # The comparator remains the ordinary unlocked coach.
        return bool(self.ledger.drill_active and not self.ledger.drill_retention and not self._hold)

    def abort(self, reason: str) -> None:
        if self._terminal:
            return
        self._terminal, self._phase, self.reason = True, "aborted", reason
        if self.ledger.drill is not None:
            self.ledger.drill.abort(reason)

    def status(self) -> dict[str, Any]:
        state = self.ledger.drill_status()
        state.update(
            configured=True,
            active=self.ledger.drill_active and not self._terminal,
            phase=self.ledger.drill.phase if self.ledger.drill is not None else self._phase,
            reason=self._hold if self.ledger.drill_active and self._hold else self.reason,
            observed_laps=len(self._seen),
            baseline_laps=len(self._baselines),
            baseline_identities=[row[0] for row in self._baselines],
            evidence=[dict(row) for row in self._evidence],
            voice_evidence=[dict(event) for event in self._voice],
        )
        return state

    def observe_native(
        self,
        payload: dict[str, Any],
        *,
        condition_eligible: bool,
        ineligible_reason: str,
        now: float | None = None,
    ) -> None:
        if self._terminal:
            return
        now = time.monotonic() if now is None else now
        if ineligible_reason in {"tyre_temp_overheat", "tyre_temp_critical"}:
            self.abort(ineligible_reason)
            return
        self._hold = "" if condition_eligible else ineligible_reason or "thermal_evidence_required"
        session, ordinal = payload.get("archive_session_uuid"), payload.get("archive_lap_n")
        if not isinstance(session, str) or not session or type(ordinal) is not int or ordinal <= 0:
            self._hold = "native_lap_context_required"
            return
        if self._session is not None and session != self._session:
            self.abort("drill_session_changed")
            return
        self._session = session
        if self._first_ordinal is None:
            self._first_ordinal = ordinal
        if ordinal - self._first_ordinal >= 10:
            self._hold = "lap_budget_exhausted"
        key = (session, ordinal)
        if key != self._context:
            previous = self._windows.get(self._context) if self._context is not None else None
            continuous_boundary = previous is not None and 0 <= now - previous.last_tick <= 0.30
            if previous is not None:
                if ordinal != self._context[1] + 1:
                    self.abort("native_lap_context_gap")
                    return
                previous.end_min, previous.end_max = previous.last_tick, now
                if not continuous_boundary:
                    previous.continuous = False
            elapsed = _number(payload.get("lap_time_ms"))
            if len(self._windows) >= 11:
                self.abort("lap_budget_exhausted")
                return
            self._windows[key] = _LapWindow(
                previous.last_tick if previous is not None else now,
                now,
                now,
                continuous_boundary
                or (previous is None and elapsed is not None and 0 <= elapsed <= 250),
            )
            self._context = key
            # Only this bounded block's ten laps and their closing boundary are retained.
        else:
            window = self._windows[key]
            if now - window.last_tick > 0.30 or now < window.last_tick:
                window.continuous = False
            window.last_tick = now

    def note_voice_dispatch(self, payload: dict[str, Any]) -> None:
        if self._terminal:
            return
        if len(self._voice) == self._voice.maxlen:
            self.abort("voice_evidence_capacity_exceeded")
            return
        self._voice.append(dict(payload))

    def note_voice_cancel(self, payload: dict[str, Any]) -> None:
        if self._terminal:
            return
        for event in reversed(self._voice):
            if (
                event.get("seq") == payload.get("seq")
                and event.get("clip_id") == payload.get("clip_id")
                and event.get("t_mono_ms") == payload.get("dispatch_t_mono_ms")
                and all(
                    payload.get(key) is not None for key in ("seq", "clip_id", "dispatch_t_mono_ms")
                )
            ):
                # Any interruption attempt invalidates full-clip proof. Keep the original
                # duration for conservative retention contamination; backend acknowledgement
                # does not prove acoustic silence.
                event["cancellation"] = dict(payload)
                return
        self.abort("voice_evidence_unmatched_cancel")

    @staticmethod
    def _off_track(record: dict[str, Any]) -> bool | None:
        trace = record.get("trace")
        summary = trace.get("off_track_observation") if isinstance(trace, dict) else None
        if not isinstance(summary, dict) or summary.get("complete") is not True:
            return None
        if (
            type(summary.get("schema_version")) is not int
            or summary.get("schema_version") != 1
            or summary.get("source") != "car.wheelsOutside"
            or type(summary.get("sample_count")) is not int
            or summary["sample_count"] <= 0
            or type(summary.get("unknown_count")) is not int
            or summary["unknown_count"] != 0
        ):
            return None
        maximum, events = summary.get("max_wheels_outside"), summary.get("event_count")
        if type(maximum) is not int or not 0 <= maximum <= 4:
            return None
        if type(events) is not int or events < 0:
            return None
        return maximum > 0 or events > 0

    def _delivery(self, window: _LapWindow, corner: int, root: str) -> tuple[bool, bool] | None:
        if (
            not window.full_start
            or not window.continuous
            or window.end_min is None
            or window.end_max is None
        ):
            return None
        matching, any_instruction = False, False
        for event in self._voice:
            if event.get("instructional") is False:
                continue  # SAVE remains available and never masquerades as a practice instruction.
            timestamp, duration = _number(event.get("t_mono_ms")), _number(event.get("duration_ms"))
            if timestamp is None:
                return None
            start = timestamp / 1000.0
            if start > window.end_max:
                continue
            if duration is None or duration < 0:
                # Without a duration, even a clip started earlier might span this lap.
                return None
            end = start + duration / 1000.0
            if end < window.start_min:
                continue
            instructional = event.get("instructional")
            if type(instructional) is not bool:
                return None
            if instructional:
                any_instruction = True
                if (
                    event.get("corner") == corner
                    and event.get("kind") == root
                    and "cancellation" not in event
                    and start >= window.start_max
                    and end <= window.end_min
                ):
                    matching = True
        return matching, any_instruction

    def complete_archive(
        self,
        record: dict[str, Any],
        qualification: Qualification,
        observations: dict[int, tuple[CornerSignature, float]],
        *,
        labels: dict[int, str],
        condition_eligible: bool,
        voice_ready: bool,
    ) -> dict[str, Any]:
        if self._terminal:
            return self.status()
        lap = record.get("lap")
        lap = lap if isinstance(lap, dict) else {}
        session, ordinal = record.get("session_uuid"), lap.get("lap_n")
        if not isinstance(session, str) or not session or type(ordinal) is not int or ordinal <= 0:
            self.reason = "lap_identity_unavailable"
            return self.status()
        key = (session, ordinal)
        window = self._windows.get(key)
        if self._terminal or key in self._seen:
            return self.status()
        if window is None or window.end_min is None or session != self._session:
            self.reason = "native_lap_window_unavailable"
            return self.status()
        self._seen.add(key)
        if len(self._seen) > 10:
            self.abort("lap_budget_exhausted")
            return self.status()
        actual = archive_combo(record)
        combo = (actual[0], actual[1], actual[2] or "") if actual is not None else None
        valid_human = (
            qualification.allowed
            and qualification.authority == "human"
            and lap.get("is_valid") is True
            and combo == self.combo
        )
        off_track = self._off_track(record)
        lap_id = str(record.get("lap_uuid") or "")
        # This bounded private receipt reports the ledger decision and its immutable inputs;
        # it is never loaded as progression authority or persisted over the source archive.
        receipt = {
            "lap_uuid": lap_id,
            "session_uuid": session,
            "lap_n": ordinal,
            "qualification": {
                "allowed": qualification.allowed,
                "authority": qualification.authority,
                "reason": qualification.reason,
            },
            "off_track": off_track,
            "condition_eligible": condition_eligible,
            "voice_ready": voice_ready,
            "phase_before": self.ledger.drill.phase
            if self.ledger.drill is not None
            else self._phase,
        }
        self._evidence.append(receipt)
        if off_track is True and self.ledger.drill is None:
            self._terminal, self._phase, self.reason = True, "failed", "off_track"
            receipt.update(phase_after="failed", reason="off_track", advanced=False)
            return self.status()
        if self.ledger.drill is None:
            if len(self._seen) <= 2:
                self.reason = "warmup_laps"
                return self.status()
            self._phase = "baseline"
            if not valid_human or off_track is not False or not condition_eligible or not lap_id:
                self.reason = "qualified_human_baseline_required"
                return self.status()
            if len(self._baselines) < 3:
                self._baselines.append((lap_id, qualification, observations))
            if len(self._baselines) < 3:
                self.reason = "baseline_laps"
                return self.status()
            if not voice_ready:
                self.reason = "voice_output_required"
                return self.status()
            if 10 - len(self._seen) < 5:
                self.abort("remaining_lap_budget_insufficient")
                return self.status()
            for corner in sorted(labels):
                samples = [row for row in self._baselines if corner in row[2]]
                if len(samples) != 3 or corner not in self.reference_signatures:
                    continue
                samples.sort(key=lambda row: row[2][corner][1])
                baseline_id, baseline_q, baseline = samples[1]
                signature, elapsed = baseline[corner]
                try:
                    target = build_human_drill_target(
                        self.reference_signatures[corner],
                        signature,
                        reference_qualification=self.reference_qualification,
                        baseline_qualification=baseline_q,
                        drill_id=self.drill_id,
                        combo=self.combo,
                        baseline_corner_time_s=elapsed,
                        reference_identity=self.reference_identity,
                        baseline_identity=baseline_id,
                    )
                    self.ledger.start_drill(target, max_laps=10 - len(self._seen))
                except (FrontierError, ValueError) as exc:
                    self.reason = str(exc)
                    continue
                self.reason = "cued_trials"
                return self.status()  # The final baseline is never also a practice trial.
            self._terminal, self._phase = True, "unavailable"
            self.reason = self.reason or "no_curriculum_gap"
            return self.status()
        target = self.ledger.drill_target
        if target is None:
            return self.status()
        if target.corner in observations and lap_id:
            signature, elapsed = observations[target.corner]
            self.ledger.stage_drill_pass(
                signature, corner_time_s=elapsed, lap_uuid=lap_id, off_track=off_track
            )
        label = labels.get(target.corner, "")
        spoken_corner = int(label[1:]) if label.startswith("T") and label[1:].isdigit() else -1
        delivery = self._delivery(window, spoken_corner, target.root)
        cued = (
            delivery[1]
            if self.ledger.drill_retention and delivery is not None
            else (delivery[0] if delivery is not None else False)
        )
        state = self.ledger.complete_drill_lap(
            lap_uuid=lap_id,
            session_uuid=session,
            combo=combo,
            qualification=qualification,
            valid=valid_human,
            off_track=off_track,
            cued=cued,
            condition_eligible=condition_eligible and voice_ready and delivery is not None,
        )
        self.reason = (
            state["reason"] if delivery is not None else "voice_delivery_evidence_unavailable"
        )
        if state["phase"] in {"passed", "failed", "aborted"}:
            self._terminal, self._phase = True, state["phase"]
        receipt.update(
            phase_after=state["phase"],
            reason=self.reason,
            instruction_delivered=delivery[0] if delivery is not None else None,
            instruction_overlap=delivery[1] if delivery is not None else None,
            advanced=state["advanced"],
            observed_signature=observations[target.corner][0].__dict__.copy()
            if target.corner in observations
            else None,
            corner_time_s=observations[target.corner][1] if target.corner in observations else None,
        )
        return self.status()
