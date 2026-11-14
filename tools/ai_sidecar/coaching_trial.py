"""Cue-exposure journal for the coaching-effect trial layer (issue #989, stage 0).

Nothing persisted which corner pass received which cue: :class:`CoachingLedger` is in-memory.
This module records it by composition, without editing the runtime or the ledger:

* :class:`ExposureJournal` is an append-only JSONL sink. A failed write latches the journal
  and raises on every later append, so cues can never continue unrecorded.
* :class:`RecordingLedger` subclasses :class:`CoachingLedger` and never changes a decision. It
  journals each ARMED approach when the runtime first peeks it (``armed_root``), each ledger
  commit (``due_prime``) and the pass outcome (``record_pass``).
* :class:`TrialRecorder` wraps ``CoachRuntime.observe``. It supplies the frame clock, measures
  corner time and journals the PRIME advisories the runtime actually emitted.

Stage 0 scope: assignment is always ``as_delivered``. There is no randomizing or withholding
mode here; that is stage 1 and needs a hook in the runtime.

What the ledger seam can and cannot see (verified in ``tests/test_coaching_trial.py``):

* Every (lap, corner) the ledger arms is journaled, and so is every commit.
* The runtime gates some PRIMEs *before* asking the ledger (capability, traffic, practice
  hold). Such an approach is journaled with no commit; the instant its anchor was crossed is
  not visible from the ledger. Stage 1 must log assignment before the anchor, so it needs the
  runtime hook.
* The runtime also drops a committed PRIME when the reference is off pace. That is visible
  only in the advisory stream, which is why ``emitted`` is journaled separately from ``commit``.

The continuous pass measurements read the runtime's per-pass accumulator (``_pass``) and
``_signature_from_pass``. Both are private to ``coaching_runtime``; a missing seam raises
:class:`TrialSeamError` instead of journaling a guess.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger, CueEvent
from tools.ai_sidecar.coaching_runtime import CoachRuntime, _signature_from_pass
from tools.ai_sidecar.lap_dynamics import CornerSignature
from tools.ai_sidecar.realtime_observer import Advisory

JOURNAL_SCHEMA = "coaching_trial_journal_v1"
ASSIGNMENT_AS_DELIVERED = "as_delivered"
#: The runtime opens a pass window this far (spline) before the brake anchor.
_PASS_WINDOW_LEAD = 0.04
_LAP_WRAP_DROP = 0.5

#: Unit of each root's targeted-error magnitude.
TARGETED_ERROR_UNIT: dict[str, str] = {
    str(RootError.EARLY_BRAKE): "spline",
    str(RootError.LATE_BRAKE): "spline",
    str(RootError.NO_TRAIL): "trail_fraction",
    str(RootError.SLOW_APEX): "km/h",
    str(RootError.LATE_THROTTLE): "spline",
}


class JournalWriteError(RuntimeError):
    """The exposure journal could not record an event. Recording must stop, not continue."""


class TrialSeamError(RuntimeError):
    """The runtime no longer exposes the state the journal reads. Fail loudly, never guess."""


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class ExposureJournal:
    """Append-only JSONL journal. ``path=None`` keeps events in memory (tests, dry runs).

    A file journal is created exclusively: an existing file is never opened, truncated or
    appended to, so a replay cannot overwrite earlier evidence.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.events: list[dict[str, Any]] = []
        self.failed = False
        self._seq = 0
        self._handle = None
        if self.path is not None:
            try:
                self._handle = self.path.open("x", encoding="utf-8", newline="\n")
            except OSError as exc:
                self.failed = True
                raise JournalWriteError(f"journal_open_failed: {exc}") from exc

    def append(self, event: str, **body: Any) -> dict[str, Any]:
        if self.failed:
            raise JournalWriteError("journal_failed_earlier")
        record = {"schema": JOURNAL_SCHEMA, "seq": self._seq, "event": event, **body}
        try:
            line = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if self._handle is not None:
                self._handle.write(line + "\n")
                self._handle.flush()
        except (OSError, ValueError, TypeError) as exc:
            self.failed = True
            raise JournalWriteError(f"journal_append_failed: {exc}") from exc
        self._seq += 1
        self.events.append(json.loads(line))
        return record

    def close(self) -> None:
        if self._handle is not None:
            handle, self._handle = self._handle, None
            try:
                handle.close()
            except OSError as exc:
                self.failed = True
                raise JournalWriteError(f"journal_close_failed: {exc}") from exc


def pass_margins(sig: CornerSignature, ref: CornerSignature) -> dict[str, float | None]:
    """Signed technique margins of one pass against the reference (``None`` = not measurable).

    The same quantities :func:`classify_root_error` thresholds, but all four at once, so a
    root's magnitude stays measurable on a pass where another root (or none) was diagnosed.
    """
    brake = (
        sig.brake_point_spline - ref.brake_point_spline
        if sig.brake_point_spline is not None and ref.brake_point_spline is not None
        else None
    )
    throttle = (
        sig.throttle_on_spline - ref.throttle_on_spline
        if sig.throttle_on_spline is not None and ref.throttle_on_spline is not None
        else None
    )
    return {
        "brake_delta_spline": _finite(brake),
        "trail_deficit": _finite(ref.trail_brake_frac - sig.trail_brake_frac),
        "apex_deficit_kmh": _finite(ref.min_speed_kmh - sig.min_speed_kmh),
        "throttle_delta_spline": _finite(throttle),
    }


def targeted_error(root: str, margins: Mapping[str, float | None]) -> float | None:
    """Magnitude (>= 0) of the error ``root`` targets on a pass; ``None`` if not measurable."""
    key, sign = {
        str(RootError.EARLY_BRAKE): ("brake_delta_spline", -1.0),
        str(RootError.LATE_BRAKE): ("brake_delta_spline", 1.0),
        str(RootError.NO_TRAIL): ("trail_deficit", 1.0),
        str(RootError.SLOW_APEX): ("apex_deficit_kmh", 1.0),
        str(RootError.LATE_THROTTLE): ("throttle_delta_spline", 1.0),
    }.get(root, (None, 1.0))
    value = _finite(margins.get(key)) if key else None
    return None if value is None else max(0.0, sign * value)


@dataclass
class _Approach:
    approach_id: str
    lap: int
    corner: int
    root: str
    committed: bool = False


@dataclass
class RecordingLedger(CoachingLedger):
    """A :class:`CoachingLedger` that journals what it is asked. It never alters a decision:
    every override returns exactly what the base class returns.
    """

    journal: ExposureJournal | None = None
    session_id: str = ""
    _runtime: CoachRuntime | None = field(default=None, repr=False)
    _epoch: int = 0
    _open: dict[int, _Approach] = field(default_factory=dict)
    _journaled: set[int] = field(default_factory=set)
    _clock: tuple[float | None, float | None] = (None, None)
    _corner_time_s: dict[int, float] = field(default_factory=dict)

    @classmethod
    def adopt(
        cls, ledger: CoachingLedger, *, journal: ExposureJournal | None, session_id: str
    ) -> RecordingLedger:
        """Copy an existing ledger's configuration and state into a recording ledger."""
        if ledger.drill is not None:
            raise ValueError("recording_ledger_cannot_adopt_an_active_drill")
        new = cls(journal=journal, session_id=session_id)
        for spec in fields(CoachingLedger):
            setattr(new, spec.name, copy.deepcopy(getattr(ledger, spec.name)))
        return new

    # --- recorder context -------------------------------------------------------------------
    def bind_runtime(self, runtime: CoachRuntime) -> None:
        self._runtime = runtime

    def set_clock(self, t_ms: float | None, spline: float | None) -> None:
        self._clock = (t_ms, spline)

    def set_corner_time(self, corner: int, seconds: float) -> None:
        self._corner_time_s[corner] = seconds

    def _write(self, event: str, **body: Any) -> None:
        if self.journal is None:
            return
        t_ms, spline = self._clock
        self.journal.append(event, session=self.session_id, t_ms=t_ms, spline=spline, **body)

    def _approach(self, corner: int, root: RootError) -> _Approach:
        approach = self._open.get(corner)
        if approach is not None:
            return approach
        approach = _Approach(
            approach_id=f"{self.session_id}:{self._epoch}:{self._lap}:{corner}",
            lap=self._lap,
            corner=corner,
            root=str(root),
        )
        self._open[corner] = approach
        self._journaled.add(corner)
        state = self._states.get(corner)
        self._write(
            "armed",
            approach_id=approach.approach_id,
            lap=approach.lap,
            corner=corner,
            root=approach.root,
            ledger_status=str(state.status) if state is not None else None,
            eligibility="ledger_armed",
            assignment=ASSIGNMENT_AS_DELIVERED,
        )
        return approach

    def close_open(self, reason: str) -> None:
        """Journal every approach that never received a pass, then forget it."""
        for corner in sorted(self._open):
            approach = self._open[corner]
            self._write(
                "closed",
                approach_id=approach.approach_id,
                lap=approach.lap,
                corner=corner,
                reason=reason,
            )
        self._open.clear()

    # --- journaled ledger surface -----------------------------------------------------------
    def begin_lap(self, lap: int) -> None:
        self.close_open("lap_ended_without_pass")
        self._journaled.clear()
        self._corner_time_s.clear()
        super().begin_lap(lap)

    def clear_session(self) -> None:
        self.close_open("session_reset")
        self._journaled.clear()
        self._corner_time_s.clear()
        self._epoch += 1
        super().clear_session()

    def armed_root(self, corner: int) -> RootError | None:
        root = super().armed_root(corner)
        # One approach per (lap, corner). A corner that stays PRIMED after its pass keeps
        # returning its root for the rest of the lap; that is not a second approach.
        if root is not None and corner not in self._journaled:
            self._approach(corner, root)
        return root

    def due_prime(self, corner: int) -> RootError | None:
        root = super().due_prime(corner)
        approach = self._open.get(corner)
        if approach is None and root is not None and corner not in self._journaled:
            approach = self._approach(corner, root)
        if approach is not None:
            approach.committed = approach.committed or root is not None
            self._write(
                "commit",
                approach_id=approach.approach_id,
                lap=approach.lap,
                corner=corner,
                committed=root is not None,
                root=str(root) if root is not None else None,
                lap_cues_spent=self._spoken_this_lap,
            )
        return root

    def note_emitted(self, advisory: Advisory) -> None:
        """Journal a PRIME the runtime actually returned for delivery."""
        approach = self._open.get(advisory.corner)
        self._write(
            "emitted",
            approach_id=approach.approach_id if approach is not None else None,
            lap=self._lap,
            corner=advisory.corner,
            root=str(advisory.detail.get("root")),
            register=advisory.register,
            cue_spline=advisory.spline,
        )

    def record_pass(
        self, corner: int, diag: Diagnosis, *, time_lost_s: float, valid: bool
    ) -> list[CueEvent]:
        approach = self._open.pop(corner, None)
        measured = self._measure_pass(corner) if approach is not None else None
        events = super().record_pass(corner, diag, time_lost_s=time_lost_s, valid=valid)
        if approach is None:
            return events
        margins = measured["margins"] if measured is not None else {}
        state = self._states.get(corner)
        capability = (
            dict(self._runtime.last_pass_capability.get(corner) or {})
            if self._runtime is not None
            else {}
        )
        # The traffic gate only enforces in replay mode; in shadow mode its reason is advisory.
        traffic_enforced = getattr(self._runtime, "traffic_gate_mode", "shadow") == "replay"
        self._write(
            "outcome",
            approach_id=approach.approach_id,
            lap=approach.lap,
            corner=corner,
            root=approach.root,
            pass_root=str(diag.root),
            pass_valid=bool(valid),
            pass_measured=bool(measured["measured"]) if measured is not None else None,
            margins=margins,
            targeted_error=targeted_error(approach.root, margins),
            targeted_error_unit=TARGETED_ERROR_UNIT.get(approach.root),
            corner_time_s=_finite(self._corner_time_s.get(corner)),
            apex_deficit_proxy_kmh=_finite(time_lost_s),
            gate_reason=str(
                capability.get("ineligible_reason")
                or (capability.get("traffic_reason") if traffic_enforced else "")
                or ""
            ),
            traffic_shadow_reason=str(capability.get("traffic_reason") or ""),
            confirm=any(e.kind == "confirm" for e in events),
            ledger_status_after=str(state.status) if state is not None else None,
        )
        return events

    def _measure_pass(self, corner: int) -> dict[str, Any] | None:
        runtime = self._runtime
        if runtime is None:
            return None
        try:
            state = runtime._pass[corner]  # noqa: SLF001 - documented stage 0 seam
            reference = next(r for r in runtime.refs if r.index == corner)
            signature = _signature_from_pass(state, reference)
            measured = state.entry_count > 0 and state.min_speed_kmh < 1e9
        except (AttributeError, KeyError, StopIteration, TypeError) as exc:
            raise TrialSeamError(f"runtime_pass_state_unavailable: {exc!r}") from exc
        ref_sig = runtime.ref_sigs.get(corner)
        if ref_sig is None or not measured:
            return {"measured": False, "margins": {}}
        return {"measured": True, "margins": pass_margins(signature, ref_sig)}


def attach_recording_ledger(
    runtime: CoachRuntime,
    *,
    journal: ExposureJournal | None,
    session_id: str,
    context: Mapping[str, Any] | None = None,
) -> RecordingLedger:
    """Swap ``runtime.ledger`` for a recording copy. Refuses a runtime with a practice session,
    which holds its own reference to the original ledger.
    """
    if runtime.practice is not None:
        raise ValueError("recording_ledger_cannot_attach_to_a_practice_runtime")
    ledger = RecordingLedger.adopt(runtime.ledger, journal=journal, session_id=session_id)
    ledger.bind_runtime(runtime)
    runtime.ledger = ledger
    if journal is not None:
        journal.append(
            "session",
            session=session_id,
            assignment_policy=ASSIGNMENT_AS_DELIVERED,
            ledger={
                "hysteresis": ledger.hysteresis,
                "lap_budget": ledger.lap_budget,
                "retire_after": ledger.retire_after,
                "assess_laps": ledger.assess_laps,
            },
            corners=sorted(r.index for r in runtime.refs),
            context=dict(context or {}),
        )
    return ledger


class TrialRecorder:
    """Drive a :class:`CoachRuntime` and journal cue exposure. ``observe`` returns exactly what
    the runtime returns.
    """

    def __init__(
        self,
        runtime: CoachRuntime,
        *,
        journal: ExposureJournal | None,
        session_id: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.journal = journal
        self.ledger = attach_recording_ledger(
            runtime, journal=journal, session_id=session_id, context=context
        )
        # Frozen at attach: live brake calibration moves the anchors, and a corner-time segment
        # that moves between passes is not comparable across them.
        self._windows = {
            r.index: (runtime.anchors[r.index].brake - _PASS_WINDOW_LEAD, r.spline_hi)
            for r in runtime.refs
        }
        self._entered_ms: dict[int, float] = {}
        self._prev: tuple[float, float] | None = None

    def observe(self, frame: dict[str, Any], *, t_ms: float | None = None) -> list[Advisory]:
        payload = frame.get("payload") if isinstance(frame.get("payload"), Mapping) else frame
        spline = _finite(payload.get("spline"))
        clock = _finite(t_ms) if t_ms is not None else _finite(payload.get("eMs"))
        self.ledger.set_clock(clock, spline)
        if spline is not None and clock is not None:
            self._time_corners(spline, clock)
        out = self.runtime.observe(frame)
        for advisory in out:
            if advisory.detail.get("coach") == "prime":
                self.ledger.note_emitted(advisory)
        return out

    def note_lap(self, **body: Any) -> None:
        """Journal a completed lap's identity (lap number, duration, source hash)."""
        if self.journal is not None:
            self.journal.append("lap", session=self.ledger.session_id, **body)

    def finish(self) -> None:
        """Close approaches that never received a pass. Does not close the journal file."""
        self.ledger.close_open("recording_finished")

    def _time_corners(self, spline: float, clock: float) -> None:
        prev = self._prev
        self._prev = (spline, clock)
        if prev is None:
            return
        p_spline, p_clock = prev
        if p_spline - spline > _LAP_WRAP_DROP or clock < p_clock:
            self._entered_ms.clear()  # new lap or rewind: no segment spans it
            return
        if spline <= p_spline:
            return
        for corner, (lo, hi) in self._windows.items():
            if lo < 0.0:
                continue  # window wraps start/finish: corner time is not measured
            if p_spline < lo <= spline:
                self._entered_ms[corner] = _interpolate(p_spline, p_clock, spline, clock, lo)
            if p_spline <= hi < spline and corner in self._entered_ms:
                exit_ms = _interpolate(p_spline, p_clock, spline, clock, hi)
                self.ledger.set_corner_time(
                    corner, (exit_ms - self._entered_ms.pop(corner)) / 1000.0
                )


def _interpolate(s0: float, t0: float, s1: float, t1: float, target: float) -> float:
    return t0 + (t1 - t0) * ((target - s0) / (s1 - s0))


def read_journal(path: Path | str) -> list[dict[str, Any]]:
    """Load a journal file. Any malformed line is an error: evidence is never skipped."""
    events: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: journal_line_invalid") from exc
            if not isinstance(record, dict) or record.get("schema") != JOURNAL_SCHEMA:
                raise ValueError(f"{path}:{number}: journal_schema_unsupported")
            events.append(record)
    return events


def assemble_approaches(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold journal events into one record per ARMED approach.

    Raises ``ValueError`` on a duplicate approach identity or a non-finite magnitude, so a
    corrupt journal cannot reach the analysis.
    """
    approaches: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event.get("event")
        approach_id = event.get("approach_id")
        if kind == "armed":
            if not isinstance(approach_id, str) or approach_id in approaches:
                raise ValueError(f"duplicate_or_missing_approach_identity: {approach_id!r}")
            approaches[approach_id] = {
                "approach_id": approach_id,
                "session": event.get("session"),
                "lap": event.get("lap"),
                "corner": event.get("corner"),
                "root": event.get("root"),
                "ledger_status": event.get("ledger_status"),
                "assignment": event.get("assignment"),
                "commit_requested": False,
                "committed": False,
                "emitted": False,
                "outcome": None,
                "closed_reason": None,
            }
            continue
        record = approaches.get(approach_id) if isinstance(approach_id, str) else None
        if record is None:
            if kind in {"commit", "outcome", "closed"}:
                raise ValueError(f"{kind}_without_armed_approach: {approach_id!r}")
            continue
        if kind == "commit":
            record["commit_requested"] = True
            record["committed"] = record["committed"] or event.get("committed") is True
        elif kind == "emitted":
            record["emitted"] = True
        elif kind == "closed":
            record["closed_reason"] = event.get("reason")
        elif kind == "outcome":
            if record["outcome"] is not None:
                raise ValueError(f"duplicate_pass_outcome: {approach_id!r}")
            magnitude = event.get("targeted_error")
            if magnitude is not None and (_finite(magnitude) is None or magnitude < 0):
                raise ValueError(f"non_finite_or_negative_targeted_error: {approach_id!r}")
            record["outcome"] = {
                key: event.get(key)
                for key in (
                    "pass_root",
                    "pass_valid",
                    "pass_measured",
                    "margins",
                    "targeted_error",
                    "targeted_error_unit",
                    "corner_time_s",
                    "apex_deficit_proxy_kmh",
                    "gate_reason",
                    "confirm",
                    "ledger_status_after",
                )
            }
    for record in approaches.values():
        outcome = record["outcome"] or {}
        if record["committed"]:
            record["eligibility"] = "eligible"
        elif record["commit_requested"]:
            record["eligibility"] = "ledger_declined"
        elif outcome.get("gate_reason"):
            record["eligibility"] = "runtime_gated:" + str(outcome["gate_reason"])
        else:
            record["eligibility"] = "not_committed_gated_or_anchor_not_crossed"
    return list(approaches.values())
