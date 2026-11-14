"""Frozen human technique and completed-lap drill/retention acceptance (#529 G3)."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from tests.test_coaching_v2 import _sig
from tools.ai_sidecar.coachable_frontier import FrontierError, build_human_drill_target
from tools.ai_sidecar.coaching.between_lap import select_between_lap_advice
from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.track_reference import CornerReference
from tools.lap_qualification import Qualification

COMBO = ("synthetic-car", "synthetic-track", "")
HUMAN = Qualification(True, "eligible", (), True, "human")


def _target(drill_id="trail-brake-entry", **overrides):
    args = {
        "reference_qualification": HUMAN,
        "baseline_qualification": HUMAN,
        "drill_id": drill_id,
        "combo": COMBO,
        "baseline_corner_time_s": 8.0,
        "reference_identity": "reference-raw-hash",
        "baseline_identity": "baseline-raw-hash",
    }
    args.update(overrides)
    return build_human_drill_target(
        _sig(),
        _sig(
            min_speed_kmh=70.0,
            trail_brake_frac=0.1,
            brake_point_spline=0.22,
            throttle_on_spline=0.39,
        ),
        **args,
    )


def _ledger(*, max_laps=10, target=None):
    ledger = CoachingLedger(drills_enabled=True)
    ledger.start_drill(target or _target(), max_laps=max_laps)
    return ledger


def _complete(ledger, lap, *, signature=None, stage=True, **overrides):
    if stage:
        ledger.stage_drill_pass(signature or _sig(), corner_time_s=8.0, lap_uuid=lap)
    args = {
        "lap_uuid": lap,
        "session_uuid": "synthetic-session",
        "combo": COMBO,
        "qualification": HUMAN,
        "valid": True,
        "cued": not ledger.drill_retention,
        "condition_eligible": True,
    }
    args.update(overrides)
    return ledger.complete_drill_lap(**args)


@pytest.mark.parametrize(
    "drill_id,metric,root",
    [
        ("apex-foundation", "min_speed_kmh", "slow_apex"),
        ("throttle-to-apex", "throttle_on_spline", "late_throttle"),
        ("trail-brake-entry", "trail_brake_frac", "no_trail"),
        ("brake-later-with-control", "brake_point_spline", "early_brake"),
    ],
)
def test_one_frozen_human_metric_per_existing_curriculum(drill_id, metric, root):
    target = _target(drill_id)
    assert target.metric == metric and target.root == root
    assert target.brake_point_spline == 0.25
    assert target.throttle_on_spline == 0.36
    assert target.trail_brake_frac == 0.4
    assert target.to_dict()["source"] == "qualified_human_reference"
    with pytest.raises(FrozenInstanceError):
        target.trail_brake_frac = 0.1
    json.dumps(target.to_dict(), allow_nan=False)


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown", "legacy_unknown"])
@pytest.mark.parametrize("boundary", ["reference_qualification", "baseline_qualification"])
def test_source_flags_cannot_promote_nonhuman_technique(authority, boundary):
    with pytest.raises(FrontierError, match="qualified_human"):
        _target(**{boundary: Qualification(True, "claimed", (), True, authority)})


def test_a_target_requires_a_measured_baseline_gap_and_known_curriculum():
    with pytest.raises(FrontierError, match="already_in_target_band"):
        build_human_drill_target(
            _sig(),
            _sig(),
            reference_qualification=HUMAN,
            baseline_qualification=HUMAN,
            drill_id="trail-brake-entry",
            combo=COMBO,
            baseline_corner_time_s=8.0,
            reference_identity="ref",
            baseline_identity="baseline",
        )
    with pytest.raises(ValueError, match="unknown_curriculum"):
        _target("invented-drill")


def test_zero_and_finish_wrap_are_real_human_spline_values():
    target = build_human_drill_target(
        _sig(apex_spline=0.94, throttle_on_spline=0.0),
        _sig(apex_spline=0.94, throttle_on_spline=0.04),
        reference_qualification=HUMAN,
        baseline_qualification=HUMAN,
        drill_id="throttle-to-apex",
        combo=COMBO,
        baseline_corner_time_s=8.0,
        reference_identity="ref",
        baseline_identity="baseline",
    )
    assert target.throttle_on_spline == 0.0
    assert target.assess(_sig(apex_spline=0.94, throttle_on_spline=0.999), corner_time_s=8.0)[
        "success"
    ]


def _direction_target(reference, baseline, drill_id):
    return build_human_drill_target(
        reference,
        baseline,
        reference_qualification=HUMAN,
        baseline_qualification=HUMAN,
        drill_id=drill_id,
        combo=COMBO,
        baseline_corner_time_s=8.0,
        reference_identity="reference",
        baseline_identity="baseline",
    )


@pytest.mark.parametrize(
    "drill_id,reference,baseline",
    [
        ("apex-foundation", _sig(min_speed_kmh=80.0), _sig(min_speed_kmh=90.0)),
        ("trail-brake-entry", _sig(trail_brake_frac=0.4), _sig(trail_brake_frac=0.7)),
        ("throttle-to-apex", _sig(throttle_on_spline=0.38), _sig(throttle_on_spline=0.34)),
        # The baseline mark has a bigger raw spline but is EARLIER after its apex.
        (
            "throttle-to-apex",
            _sig(apex_spline=0.3, throttle_on_spline=0.36),
            _sig(apex_spline=0.35, throttle_on_spline=0.39),
        ),
        (
            "throttle-to-apex",
            _sig(apex_spline=0.94, throttle_on_spline=0.04),
            _sig(apex_spline=0.94, throttle_on_spline=0.0),
        ),
    ],
)
def test_already_better_baselines_never_get_an_opposing_instruction(drill_id, reference, baseline):
    with pytest.raises(FrontierError, match="drill_reference_not_a_directional_improvement"):
        _direction_target(reference, baseline, drill_id)


@pytest.mark.parametrize(
    "reference,baseline,root",
    [
        (_sig(brake_point_spline=0.25), _sig(brake_point_spline=0.22), "early_brake"),
        (_sig(brake_point_spline=0.25), _sig(brake_point_spline=0.28), "brake_late"),
        (
            _sig(apex_spline=0.02, brake_point_spline=0.0),
            _sig(apex_spline=0.02, brake_point_spline=0.98),
            "early_brake",
        ),
        (
            _sig(apex_spline=0.02, brake_point_spline=0.98),
            _sig(apex_spline=0.02, brake_point_spline=0.0),
            "brake_late",
        ),
    ],
)
def test_brake_instruction_direction_comes_from_signed_human_mark_gap(reference, baseline, root):
    assert _direction_target(reference, baseline, "brake-later-with-control").root == root


@pytest.mark.parametrize(
    "drill_id,reference,baseline,reason",
    [
        (
            "brake-later-with-control",
            _sig(brake_point_spline=0.75),
            _sig(brake_point_spline=0.25),
            "drill_phase_ambiguous",
        ),
        (
            "brake-later-with-control",
            _sig(brake_point_spline=0.4),
            _sig(brake_point_spline=0.25),
            "drill_stage_phase_unavailable",
        ),
        (
            "throttle-to-apex",
            _sig(throttle_on_spline=0.2),
            _sig(throttle_on_spline=0.36),
            "drill_stage_phase_unavailable",
        ),
        (
            "throttle-to-apex",
            _sig(apex_spline=float("nan")),
            _sig(throttle_on_spline=0.39),
            "drill_stage_phase_unavailable",
        ),
        (
            "throttle-to-apex",
            _sig(throttle_on_spline=None),
            _sig(throttle_on_spline=0.39),
            "drill_primary_metric_unavailable",
        ),
        (
            "throttle-to-apex",
            _sig(throttle_on_spline=0.8),
            _sig(throttle_on_spline=0.39),
            "drill_phase_ambiguous",
        ),
    ],
)
def test_missing_wrong_or_halftrack_phase_is_never_assumed(drill_id, reference, baseline, reason):
    with pytest.raises(FrontierError, match=reason):
        _direction_target(reference, baseline, drill_id)


def test_staging_cannot_advance_before_whole_qualified_human_lap():
    ledger = _ledger()
    assert ledger.stage_drill_pass(_sig(), corner_time_s=8.0, lap_uuid="lap-1")
    assert ledger.drill_status()["cued_attempts"] == 0
    result = _complete(ledger, "lap-1", stage=False, valid=False)
    assert not result["advanced"] and result["cued_attempts"] == 0
    assert result["attempted_laps"] == 1


def test_three_cued_attempts_are_distinct_from_success_then_two_uncued_retention():
    ledger = _ledger(max_laps=5)
    _complete(ledger, "lap-1", signature=_sig(trail_brake_frac=0.1))
    _complete(ledger, "lap-2")
    result = _complete(ledger, "lap-3")
    assert result["phase"] == "retention"
    assert result["cued_attempts"] == 3 and result["cued_successes"] == 2
    result = _complete(ledger, "lap-4", cued=False)
    assert result["phase"] == "retention" and result["retention_attempts"] == 1
    result = _complete(ledger, "lap-5", cued=False)
    assert result["phase"] == "passed" and result["retention_successes"] == 2
    assert result["attempted_laps"] == 5
    json.dumps(result, allow_nan=False)


def test_two_primary_misses_fail_at_three_cued_trials_without_counting_successes_as_attempts():
    ledger = _ledger()
    _complete(ledger, "lap-1", signature=_sig(trail_brake_frac=0.1))
    _complete(ledger, "lap-2", signature=_sig(trail_brake_frac=0.1))
    result = _complete(ledger, "lap-3")
    assert result["phase"] == "failed" and result["cued_attempts"] == 3
    assert result["cued_successes"] == 1 and result["retention_attempts"] == 0


def test_a_retention_reversion_is_a_failed_block():
    ledger = _ledger()
    for number in range(3):
        _complete(ledger, f"cued-{number}")
    _complete(ledger, "retention-1", cued=False, signature=_sig(trail_brake_frac=0.1))
    result = _complete(ledger, "retention-2", cued=False)
    assert result["phase"] == "failed" and result["retention_successes"] == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            {"qualification": Qualification(True, "legacy", (), False, "legacy_unknown")},
            "qualified_human",
        ),
        ({"combo": ("other", "synthetic-track", "")}, "combo_mismatch"),
        ({"valid": False}, "qualified_human"),
        ({"cued": False}, "instruction_not_delivered"),
        ({"condition_eligible": False}, "condition_ineligible"),
        ({"off_track": None}, "off_track_evidence_unavailable"),
    ],
)
def test_rejected_laps_never_advance_but_consume_safety_cap(change, reason):
    ledger = _ledger(max_laps=2)
    first = _complete(ledger, "lap-1", **change)
    assert not first["advanced"] and reason in first["reason"]
    second = _complete(ledger, "lap-2", **change)
    assert second["phase"] == "aborted" and second["reason"] == "lap_budget_exhausted"
    assert second["cued_attempts"] == 0 and second["attempted_laps"] == 2


def test_duplicates_and_ambiguous_corner_observations_never_count_as_new_trials():
    ledger = _ledger()
    _complete(ledger, "lap-1")
    duplicate = _complete(ledger, "lap-1")
    assert duplicate["attempted_laps"] == 1 and duplicate["cued_attempts"] == 1
    assert not duplicate["advanced"]
    ledger.stage_drill_pass(_sig(), corner_time_s=8.0, lap_uuid="lap-2")
    assert not ledger.stage_drill_pass(_sig(), corner_time_s=8.0, lap_uuid="lap-2")
    ambiguous = _complete(ledger, "lap-2", stage=False)
    assert not ambiguous["advanced"] and ambiguous["cued_attempts"] == 1


@pytest.mark.parametrize(
    "signature,elapsed,off_track,reason",
    [
        (_sig(exit_speed_kmh=140.0), 8.0, False, "exit_speed_degraded"),
        (_sig(), 8.5, False, "corner_time_degraded"),
        (_sig(), 8.0, True, "off_track"),
    ],
)
def test_whole_corner_regressions_and_offtrack_fail_without_promoting_metric(
    signature, elapsed, off_track, reason
):
    ledger = _ledger()
    ledger.stage_drill_pass(signature, corner_time_s=elapsed, lap_uuid="lap-1")
    result = _complete(ledger, "lap-1", stage=False, off_track=off_track)
    assert result["phase"] == "failed" and result["reason"] == reason
    assert result["cued_attempts"] == 0


def test_reference_changes_and_other_corner_ranking_cannot_move_a_locked_target():
    ledger = _ledger()
    before = ledger.drill_target.to_dict()
    for number in range(3):
        ledger.begin_lap(number + 1)
        assert ledger.armed_root(0) == RootError.NO_TRAIL
        assert ledger.armed_root(1) is None
        assert (
            ledger.record_pass(0, Diagnosis(RootError.EARLY_BRAKE), time_lost_s=20.0, valid=True)
            == []
        )
        assert ledger.due_prime(0) == RootError.NO_TRAIL
        assert ledger.due_prime(0) is None
        _complete(ledger, f"lap-{number}")
    assert ledger.drill_target.to_dict() == before
    refs = [CornerReference(0, 0.3, 0.25, 0.4, 80.0)]
    assert ledger.drill_retention and ledger.suppress_instructional_cues
    assert ledger.armed_root(0) is None and ledger.due_prime(0) is None
    assert select_between_lap_advice(refs=refs, ledger=ledger, use_ollama=False) is None


def test_cued_advice_stays_on_locked_corner_with_existing_identity_guards():
    ledger = _ledger()
    refs = [CornerReference(0, 0.3, 0.25, 0.4, 80.0), CornerReference(1, 0.6, 0.5, 0.7, 90.0)]
    advice = select_between_lap_advice(
        refs=refs,
        ledger=ledger,
        improvement_ranking=[{"corner": 1}],
        use_ollama=False,
        corner_labels={0: "T5", 1: "T8"},
    )
    assert advice["corner"] == 0 and advice["corner_label"] == "T5"
    assert "TRAIL" in advice["text"].upper()
    assert (
        select_between_lap_advice(
            refs=refs,
            ledger=ledger,
            improvement_ranking=[{"corner": 1}],
            use_ollama=False,
            corner_labels={1: "T8"},
        )
        is None
    )


def test_retention_instruction_contamination_does_not_become_a_trial():
    ledger = _ledger()
    for number in range(3):
        _complete(ledger, f"cued-{number}")
    result = _complete(ledger, "retention-cued", cued=True)
    assert not result["advanced"] and result["retention_attempts"] == 0
    assert result["reason"] == "retention_instruction_contamination"


def test_drill_default_off_and_stopped_blocks_cannot_reset_the_cap():
    with pytest.raises(ValueError, match="drills_disabled"):
        CoachingLedger().start_drill(_target())
    ledger = _ledger(max_laps=1)
    _complete(ledger, "lap-1", valid=False)
    with pytest.raises(ValueError, match="already_started"):
        ledger.start_drill(replace(_target(), corner=1))
    assert ledger.suppress_instructional_cues and ledger.due_prime(0) is None


def test_session_restart_aborts_the_block_instead_of_reusing_an_old_goal():
    ledger = _ledger()
    _complete(ledger, "lap-1")
    result = _complete(ledger, "lap-2", session_uuid="replacement-session")
    assert result["phase"] == "aborted" and result["reason"] == "drill_session_changed"
