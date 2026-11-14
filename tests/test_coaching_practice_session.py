"""Adversarial completed-lap evidence through the real practice adapter and ledger.

All archives/qualification decisions are synthetic. These tests do not certify a
real human session, speaker output, microphone timing, or physical off-track rate.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import pytest

from tests.test_coaching_v2 import _sig
from tools.ai_sidecar.coaching.practice import PracticeSession
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.lap_qualification import Qualification

COMBO = ("synthetic-car", "synthetic-track", "")
HUMAN = Qualification(True, "eligible", (), True, "human")
SESSION = "native-synthetic-session"
SUMMARY = {
    "schema_version": 1,
    "sample_count": 100,
    "unknown_count": 0,
    "max_wheels_outside": 0,
    "event_count": 0,
    "complete": True,
    "source": "car.wheelsOutside",
    "event_count_basis": "positive_runs_unknown_breaks_run",
}


def _archive(ordinal: int) -> dict:
    return {
        "schema_version": 1,
        "source": "in_game",
        "session_uuid": SESSION,
        "lap_uuid": f"immutable-lap-{ordinal}",
        "car": {"id": COMBO[0]},
        "track": {"id": COMBO[1], "layout": COMBO[2]},
        "lap": {"lap_n": ordinal, "lap_ms": 10_000, "is_valid": True},
        "trace": {"off_track_observation": dict(SUMMARY)},
    }


@dataclass
class NativePractice:
    session: PracticeSession = field(
        default_factory=lambda: PracticeSession(
            CoachingLedger(),
            COMBO,
            {0: _sig()},
            HUMAN,
            "qualified-reference-hash",
            "trail-brake-entry",
        )
    )
    ordinal: int = 1
    start: float = 100.0

    def __post_init__(self):
        self.tick(self.ordinal, self.start, elapsed=0)

    def tick(self, ordinal, now, *, elapsed=100, eligible=True, reason="", session=SESSION):
        self.session.observe_native(
            {"archive_session_uuid": session, "archive_lap_n": ordinal, "lap_time_ms": elapsed},
            condition_eligible=eligible,
            ineligible_reason=reason,
            now=now,
        )

    def dispatch(self, *, at=2.0, duration=500, instructional=True, corner=7, **extra):
        payload = {
            "seq": self.ordinal,
            "clip_id": f"clip-{self.ordinal}",
            "t_mono_ms": (self.start + at) * 1000,
            "duration_ms": duration,
            "instructional": instructional,
            "corner": corner,
            "kind": "no_trail",
        }
        payload.update(extra)
        self.session.note_voice_dispatch(payload)
        return payload

    def close_native_window(self, *, gap_at_boundary=0, gap_inside=False):
        for index in range(1, 100):
            if gap_inside and index in (40, 41, 42, 43):
                continue
            self.tick(self.ordinal, self.start + index / 10, elapsed=index * 100)
        self.tick(self.ordinal + 1, self.start + 10 + gap_at_boundary, elapsed=0)

    def complete(
        self,
        *,
        record=None,
        qualification=HUMAN,
        signature=None,
        elapsed=8.0,
        condition_eligible=True,
        voice_ready=True,
        gap_at_boundary=0,
        gap_inside=False,
    ):
        record = copy.deepcopy(record) if record is not None else _archive(self.ordinal)
        self.close_native_window(gap_at_boundary=gap_at_boundary, gap_inside=gap_inside)
        status = self.session.complete_archive(
            record,
            qualification,
            {0: (signature or _sig(), elapsed)},
            labels={0: "T7"},  # Internal index zero must join actual spoken canonical turn seven.
            condition_eligible=condition_eligible,
            voice_ready=voice_ready,
        )
        self.ordinal += 1
        self.start += 10 + gap_at_boundary
        return status

    def prime(self):
        baseline = _sig(trail_brake_frac=0.1, min_speed_kmh=70)
        for _ in range(5):
            status = self.complete(signature=baseline)
        assert status["phase"] == "cued" and status["baseline_laps"] == 3
        assert status["cued_attempts"] == 0  # The final baseline is not also a trial.
        return self

    def to_retention(self):
        self.prime()
        for _ in range(3):
            self.dispatch()
            status = self.complete()
        assert status["phase"] == "retention" and status["cued_successes"] == 3
        return self


def test_complete_native_ten_lap_unit_requires_three_delivered_and_two_silent_trials():
    rig = NativePractice().prime()
    assert rig.session.instruction_allowed
    for index in range(3):
        rig.dispatch()
        status = rig.complete(signature=_sig(trail_brake_frac=0.1) if index == 1 else _sig())
    assert status["phase"] == "retention" and not rig.session.instruction_allowed
    # Emergency SAVE is allowed; it cannot masquerade as a drill instruction.
    rig.dispatch(instructional=False, kind="save", duration=None, t_mono_ms=None)
    status = rig.complete()
    assert status["retention_attempts"] == 1
    status = rig.complete()
    assert status["phase"] == "passed"
    assert status["observed_laps"] == 10 and status["baseline_laps"] == 3
    assert status["cued_successes"] == 2 and status["retention_successes"] == 2
    assert status["active"] is False and not rig.session.instruction_allowed
    assert [row["lap_uuid"] for row in status["evidence"]] == [
        f"immutable-lap-{number}" for number in range(1, 11)
    ]
    assert all(row["qualification"]["authority"] == "human" for row in status["evidence"])


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown", "legacy_unknown"])
def test_no_native_record_or_supported_flag_promotes_assisted_trial(authority):
    rig = NativePractice().prime()
    rig.dispatch()
    status = rig.complete(qualification=Qualification(True, "claimed", (), True, authority))
    assert status["cued_attempts"] == 0
    assert status["reason"] == "completed_qualified_human_lap_required"


@pytest.mark.parametrize(
    "defect", ["missing", "incomplete", "unknown", "zero_samples", "bool_count"]
)
def test_ac_valid_lap_and_zero_downsampled_rows_do_not_replace_offtrack_proof(defect):
    rig = NativePractice().prime()
    rig.dispatch()
    record = _archive(rig.ordinal)
    record["trace"].update(fields=["wheelsOutside"], samples=[[0], [0]])
    observation = record["trace"]["off_track_observation"]
    if defect == "missing":
        del record["trace"]["off_track_observation"]
    elif defect == "incomplete":
        observation["complete"] = False
    elif defect == "unknown":
        observation["unknown_count"] = 1
    elif defect == "zero_samples":
        observation["sample_count"] = 0
    else:
        observation["max_wheels_outside"] = False
    status = rig.complete(record=record)
    assert status["cued_attempts"] == 0 and status["reason"] == "off_track_evidence_unavailable"


def test_positive_full_capture_event_fails_even_if_retained_column_is_all_zero():
    rig = NativePractice().prime()
    rig.dispatch()
    record = _archive(rig.ordinal)
    record["trace"].update(fields=["wheelsOutside"], samples=[[0], [0]])
    record["trace"]["off_track_observation"].update(max_wheels_outside=2, event_count=1)
    status = rig.complete(record=record)
    assert status["phase"] == "failed" and status["reason"] == "off_track"


@pytest.mark.parametrize("ordinal", [1, 2, 3, 5])
def test_positive_event_during_warmup_or_baseline_fails_the_whole_bounded_unit(ordinal):
    rig = NativePractice()
    for _ in range(ordinal - 1):
        rig.complete(signature=_sig(trail_brake_frac=0.1))
    record = _archive(rig.ordinal)
    record["trace"]["off_track_observation"].update(max_wheels_outside=1, event_count=1)
    status = rig.complete(record=record, signature=_sig(trail_brake_frac=0.1))
    assert status["phase"] == "failed" and status["reason"] == "off_track"
    assert rig.session.ledger.drill is None
    assert status["evidence"][-1]["off_track"] is True


def test_unknown_warmup_observation_stays_unknown_in_private_evidence():
    rig = NativePractice()
    record = _archive(rig.ordinal)
    record["trace"] = {}
    status = rig.complete(record=record)
    assert status["evidence"][-1]["off_track"] is None
    assert status["observed_laps"] == 1


@pytest.mark.parametrize("gap_at_boundary,gap_inside", [(5, False), (0, True)])
def test_transport_gap_inside_or_across_boundary_cannot_certify_a_cued_trial(
    gap_at_boundary, gap_inside
):
    rig = NativePractice().prime()
    rig.dispatch()
    status = rig.complete(gap_at_boundary=gap_at_boundary, gap_inside=gap_inside)
    assert status["cued_attempts"] == 0
    assert status["reason"] == "voice_delivery_evidence_unavailable"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_corner",
        "wrong_root",
        "overlaps_start",
        "overlaps_end",
        "missing_duration",
        "unknown_instruction",
    ],
)
def test_only_exact_complete_instruction_inside_conservative_native_window_counts(defect):
    rig = NativePractice().prime()
    changes = {
        "wrong_corner": {"corner": 1},
        "wrong_root": {"kind": "slow_apex"},
        "overlaps_start": {"at": -0.02, "duration": 500},
        "overlaps_end": {"at": 9.8, "duration": 500},
        "missing_duration": {"duration": None},
        "unknown_instruction": {"instructional": None},
    }
    rig.dispatch(**changes[defect])
    status = rig.complete()
    assert status["cued_attempts"] == 0
    assert status["reason"] in {"instruction_not_delivered", "voice_delivery_evidence_unavailable"}


def test_partly_overlapping_instruction_contaminates_uncued_retention():
    rig = NativePractice().to_retention()
    rig.dispatch(at=-0.02, duration=500)
    status = rig.complete()
    assert status["retention_attempts"] == 0
    assert status["reason"] == "retention_instruction_contamination"


def test_duplicate_archive_and_wrong_native_session_or_ordinal_do_not_spend_extra_trial():
    rig = NativePractice().prime()
    rig.dispatch()
    record = _archive(rig.ordinal)
    status = rig.complete(record=record)
    assert status["cued_attempts"] == 1
    for replay in (
        record,
        record | {"session_uuid": "other-session"},
        record | {"lap": {"lap_n": 100, "is_valid": True}},
    ):
        status = rig.session.complete_archive(
            replay,
            HUMAN,
            {0: (_sig(), 8)},
            labels={0: "T7"},
            condition_eligible=True,
            voice_ready=True,
        )
        assert status["cued_attempts"] == 1 and status["attempted_laps"] == 1


def test_cold_or_unready_voice_holds_without_recording_a_clean_trial():
    rig = NativePractice().prime()
    rig.tick(rig.ordinal, rig.start + 0.01, eligible=False, reason="tyre_temp_cold")
    assert not rig.session.instruction_allowed
    rig.dispatch()
    status = rig.complete(condition_eligible=False)
    assert status["cued_attempts"] == 0
    assert status["reason"] == "condition_ineligible"


@pytest.mark.parametrize("reason", ["tyre_temp_overheat", "tyre_temp_critical"])
def test_thermal_abort_is_terminal_and_later_context_cannot_grow_evidence(reason):
    rig = NativePractice().prime()
    rig.tick(rig.ordinal, rig.start + 0.01, eligible=False, reason=reason)
    assert rig.session.status()["phase"] == "aborted"
    count = len(rig.session._windows)
    for offset in range(1, 20):
        rig.tick(rig.ordinal + offset, rig.start + offset * 10, elapsed=0)
    assert len(rig.session._windows) == count
    assert not rig.session.instruction_allowed


def test_new_native_session_and_ordinal_jump_abort_the_existing_block():
    rig = NativePractice().prime()
    rig.tick(rig.ordinal, rig.start + 0.01, session="new-native-session")
    assert rig.session.status()["phase"] == "aborted"
    assert rig.session.status()["reason"] == "drill_session_changed"
    rig = NativePractice().prime()
    rig.tick(rig.ordinal + 2, rig.start + 20, elapsed=0)
    assert rig.session.status()["phase"] == "aborted"
    assert rig.session.status()["reason"] == "native_lap_context_gap"


def test_bad_baseline_cannot_extend_experiment_beyond_its_ten_lap_budget():
    rig = NativePractice()
    baseline = _sig(trail_brake_frac=0.1)
    for _ in range(2):
        rig.complete(signature=baseline)
    missing = _archive(rig.ordinal)
    missing["trace"] = {}
    rig.complete(record=missing, signature=baseline)
    for _ in range(3):
        status = rig.complete(signature=baseline)
    assert status["phase"] == "aborted" and status["reason"] == "remaining_lap_budget_insufficient"
    assert rig.session.ledger.drill is None


@pytest.mark.parametrize("succeeded", [True, False])
def test_correlated_cancellation_attempt_prevents_full_instruction_credit(succeeded):
    rig = NativePractice().prime()
    dispatch = rig.dispatch(duration=1000)
    rig.session.note_voice_cancel(
        {
            "seq": dispatch["seq"],
            "clip_id": dispatch["clip_id"],
            "dispatch_t_mono_ms": dispatch["t_mono_ms"],
            "cancel_attempted_at_mono_ms": dispatch["t_mono_ms"] + 200,
            "canceled_at_mono_ms": dispatch["t_mono_ms"] + 250 if succeeded else None,
            "cancel_succeeded": succeeded,
        }
    )
    status = rig.complete()
    assert status["cued_attempts"] == 0


def test_unmatched_cancellation_cannot_silently_preserve_delivered_credit():
    rig = NativePractice().prime()
    rig.dispatch()
    rig.session.note_voice_cancel(
        {"seq": 999, "clip_id": "unmatched", "dispatch_t_mono_ms": 0, "cancel_succeeded": True}
    )
    assert rig.session.status()["phase"] == "aborted"
    assert rig.session.status()["reason"] == "voice_evidence_unmatched_cancel"


def test_acknowledged_cancel_does_not_relabel_overlapping_instruction_as_uncued():
    rig = NativePractice().to_retention()
    dispatch = rig.dispatch(at=-0.02, duration=500)
    rig.session.note_voice_cancel(
        {
            "seq": dispatch["seq"],
            "clip_id": dispatch["clip_id"],
            "dispatch_t_mono_ms": dispatch["t_mono_ms"],
            "cancel_attempted_at_mono_ms": dispatch["t_mono_ms"] + 10,
            "canceled_at_mono_ms": dispatch["t_mono_ms"] + 20,
            "cancel_succeeded": True,
        }
    )
    status = rig.complete()
    assert status["retention_attempts"] == 0
    assert status["reason"] == "retention_instruction_contamination"


def test_native_boundary_clock_rollback_is_not_a_valid_dispatch_window():
    rig = NativePractice().prime()
    rig.dispatch()
    status = rig.complete(gap_at_boundary=-1)
    assert (
        status["cued_attempts"] == 0 and status["reason"] == "voice_delivery_evidence_unavailable"
    )


def test_invalid_or_other_combo_human_archive_cannot_count_a_trial():
    for defect in ("invalid", "wrong_combo"):
        rig = NativePractice().prime()
        rig.dispatch()
        record = _archive(rig.ordinal)
        if defect == "invalid":
            record["lap"]["is_valid"] = False
        else:
            record["car"]["id"] = "another-car"
        status = rig.complete(record=record)
        assert status["cued_attempts"] == 0


def test_unready_voice_cannot_be_replaced_by_a_favorable_corner_metric():
    rig = NativePractice().prime()
    rig.dispatch()
    status = rig.complete(voice_ready=False)
    assert status["cued_attempts"] == 0 and status["reason"] == "condition_ineligible"


@pytest.mark.parametrize("late_event", ["dispatch", "cancel", "abort"])
def test_terminal_thermal_reason_and_evidence_survive_late_voice_events(late_event):
    rig = NativePractice().prime()
    rig.session.abort("tyre_temp_critical")
    before = copy.deepcopy(rig.session.status())
    if late_event == "dispatch":
        for _ in range(300):
            rig.dispatch()
    elif late_event == "cancel":
        rig.session.note_voice_cancel({"seq": 999, "clip_id": "late", "dispatch_t_mono_ms": 1})
    else:
        rig.session.abort("voice_evidence_capacity_exceeded")
    assert rig.session.status() == before


def test_successful_block_is_frozen_against_later_native_and_voice_evidence():
    rig = NativePractice().to_retention()
    rig.complete()
    assert rig.complete()["phase"] == "passed"
    before = copy.deepcopy(rig.session.status())
    windows = len(rig.session._windows)
    for _ in range(300):
        rig.dispatch()
    rig.session.note_voice_cancel({"seq": 999, "clip_id": "late", "dispatch_t_mono_ms": 1})
    rig.tick(12, rig.start + 20)
    rig.session.abort("lap_budget_exhausted")
    assert rig.session.status() == before
    assert len(rig.session._windows) == windows
