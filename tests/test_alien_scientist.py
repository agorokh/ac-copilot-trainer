"""EPIC #529 P4: evidence-gated alien scientist setup experiments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ac_harness.alien_scientist import (
    ScientistError,
    append_ledger,
    build_plan,
    evaluate_experiment,
    load_ledger,
    persist_completed_run,
    write_candidate_setup,
)
from tools.ai_sidecar.car_schema import CarSetupSchema


def _schema() -> CarSetupSchema:
    return CarSetupSchema.from_spinners_dump(
        "car_a",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1, "value": 10},
            {"name": "FRONT_BIAS", "min": 50, "max": 70, "step": 1, "value": 60},
            {"name": "READ_ONLY", "min": 0, "max": 10, "step": 1, "readOnly": True},
        ],
    )


def _lap(lap_uuid: str, lap_ms: int, *, wing: int = 10, bias: int = 60) -> dict:
    return {
        "schema_version": 1,
        "lap_uuid": lap_uuid,
        "session_uuid": "session-1",
        "exported_at": f"2026-07-22T00:00:{lap_uuid[-1]}Z",
        "car": {"id": "car_a"},
        "track": {"id": "track_a", "layout": None},
        "lap": {"lap_n": int(lap_uuid[-1]), "lap_ms": lap_ms, "is_valid": True},
        "setup": {
            "hash": f"setup-{wing}-{bias}",
            "path": f"C:/setups/car_a/track_a/setup-{wing}-{bias}.ini",
            "snapshot": {"WING_2.VALUE": wing, "FRONT_BIAS.VALUE": bias},
        },
    }


_SCOPE = {
    "mechanical_platform": "gt3",
    "aero_platform": "gt",
    "tyre_family": "slick",
    "track_archetype": "short-technical",
}
_COMBO = {"car": "car_a", "track": "track_a", "layout": None}


def test_plan_turns_prose_into_one_schema_valid_parameter() -> None:
    plan = build_plan(
        trigger="pace plateau after self-play",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000), _lap("lap-2", 100_100)],
        schema=_schema(),
    )

    assert plan["trigger"] == "pace plateau after self-play"
    assert len(plan["experiments"]) == 1
    assert plan["experiments"][0]["changed_params"] == {"WING_2.VALUE": {"from": 10.0, "to": 9.0}}


def test_falsified_constraint_is_suppressed_for_same_platform_scope() -> None:
    first = build_plan(
        trigger="pace plateau",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
    )
    constraint = first["experiments"][0]["constraint_key"]

    with pytest.raises(ScientistError, match="scientist_constraints_suppressed"):
        build_plan(
            trigger="pace plateau again",
            combo=_COMBO,
            scope=_SCOPE,
            baseline_payloads=[_lap("lap-1", 100_000)],
            schema=_schema(),
            ledger=[
                {
                    "scope_key": first["scope_key"],
                    "constraint_key": constraint,
                    "verdict": "falsified",
                }
            ],
        )


def test_rejected_batch_does_not_suppress_unmeasured_constraint() -> None:
    first = _plan()
    rebuilt = build_plan(
        trigger="pace plateau retry",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
        ledger=[
            {
                "scope_key": first["scope_key"],
                "constraint_key": first["experiments"][0]["constraint_key"],
                "verdict": "rejected",
            }
        ],
    )
    assert rebuilt["experiments"]


def test_explicit_proposals_fail_closed_on_empty_unknown_or_duplicate() -> None:
    common = {
        "trigger": "pace plateau",
        "combo": _COMBO,
        "scope": _SCOPE,
        "baseline_payloads": [_lap("lap-1", 100_000)],
        "schema": _schema(),
    }
    with pytest.raises(ScientistError, match="scientist_hypothesis_count_out_of_range"):
        build_plan(**common, proposed_hypotheses=[])
    unknown = {"id": "unknown", "mechanism": "test", "parameter": "NOPE", "direction": 1}
    with pytest.raises(ScientistError, match="scientist_hypothesis_outside_schema"):
        build_plan(**common, proposed_hypotheses=[unknown])
    duplicate = {
        "id": "wing",
        "mechanism": "test",
        "parameter": "WING_2",
        "direction": -1,
    }
    with pytest.raises(ScientistError, match="scientist_hypothesis_duplicate"):
        build_plan(**common, proposed_hypotheses=[duplicate, duplicate])


@pytest.mark.parametrize(
    "proposal",
    [
        {"id": "x", "mechanism": "m", "parameter": "WING_2", "direction": float("nan")},
        {"id": "x", "mechanism": "", "parameter": "WING_2", "direction": 1},
        {"id": "x", "mechanism": "m", "parameter": "WING_2", "direction": 2},
        {"id": "../escape", "mechanism": "m", "parameter": "WING_2", "direction": 1},
    ],
)
def test_malformed_model_hypothesis_never_reaches_setup(proposal: dict) -> None:
    with pytest.raises(ScientistError, match="scientist_hypothesis_malformed"):
        build_plan(
            trigger="plateau",
            combo=_COMBO,
            scope=_SCOPE,
            baseline_payloads=[_lap("lap-1", 100_000)],
            schema=_schema(),
            proposed_hypotheses=[proposal],
        )


def test_candidate_writer_changes_exactly_one_parameter_under_ac_documents(tmp_path: Path) -> None:
    user_dir = tmp_path / "Assetto Corsa"
    baseline = user_dir / "setups" / "car_a" / "track_a" / "baseline.ini"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("[WING_2]\nVALUE=10\n\n[FRONT_BIAS]\nVALUE=60\n", encoding="utf-8")
    experiment = {
        "hypothesis_id": "plateau_rear_wing",
        "constraint_key": "0123456789abcdef",
        "changed_params": {"WING_2.VALUE": {"from": 10, "to": 9}},
    }

    candidate = write_candidate_setup(
        baseline, user_dir=user_dir, plan_id="0123456789abcdef", experiment=experiment
    )

    assert candidate.parent == baseline.parent
    assert "VALUE=9" in candidate.read_text(encoding="utf-8")
    assert "[FRONT_BIAS]\nVALUE=60" in candidate.read_text(encoding="utf-8")
    assert baseline.read_text(encoding="utf-8").startswith("[WING_2]\nVALUE=10")
    assert (
        write_candidate_setup(
            baseline, user_dir=user_dir, plan_id="0123456789abcdef", experiment=experiment
        )
        == candidate
    )
    candidate.write_text("[WING_2]\nVALUE=999\n", encoding="utf-8")
    with pytest.raises(ScientistError, match="scientist_candidate_conflicts"):
        write_candidate_setup(
            baseline, user_dir=user_dir, plan_id="0123456789abcdef", experiment=experiment
        )


def test_candidate_writer_rejects_baseline_drift_since_measured_batch(tmp_path: Path) -> None:
    user_dir = tmp_path / "Assetto Corsa"
    baseline = user_dir / "setups" / "car_a" / "baseline.ini"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("[WING_2]\nVALUE=11\n", encoding="utf-8")

    with pytest.raises(ScientistError, match="scientist_baseline_setup_drifted"):
        write_candidate_setup(
            baseline,
            user_dir=user_dir,
            plan_id="0123456789abcdef",
            experiment={
                "constraint_key": "0123456789abcdef",
                "changed_params": {"WING_2.VALUE": {"from": 10, "to": 9}},
            },
        )


def test_candidate_writer_rejects_baseline_outside_ac_documents(tmp_path: Path) -> None:
    user_dir = tmp_path / "Assetto Corsa"
    (user_dir / "setups").mkdir(parents=True)
    outside = tmp_path / "outside.ini"
    outside.write_text("[WING_2]\nVALUE=10\n", encoding="utf-8")

    with pytest.raises(ScientistError, match="scientist_baseline_outside_setups_root"):
        write_candidate_setup(
            outside,
            user_dir=user_dir,
            plan_id="0123456789abcdef",
            experiment={
                "hypothesis_id": "x",
                "constraint_key": "0123456789abcdef",
                "changed_params": {"WING_2.VALUE": {"from": 10, "to": 9}},
            },
        )


def _plan() -> dict:
    return build_plan(
        trigger="pace plateau",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000), _lap("lap-2", 101_000)],
        schema=_schema(),
    )


def test_measured_significant_single_parameter_gain_is_promoted() -> None:
    plan = _plan()
    outcome = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[_lap("lap-1", 100_000), _lap("lap-2", 101_000)],
        candidate_payloads=[_lap("lap-3", 90_000, wing=9), _lap("lap-4", 91_000, wing=9)],
        candidate_valid=True,
        candidate_reason="two valid laps",
    )

    assert outcome["verdict"] == "promoted"
    assert outcome["promoted"] is True
    assert outcome["comparison"]["significant"] is True


def test_confounded_or_invalid_batch_keeps_last_valid_setup() -> None:
    plan = _plan()
    confounded = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[_lap("lap-1", 100_000), _lap("lap-2", 101_000)],
        candidate_payloads=[
            _lap("lap-3", 90_000, wing=9, bias=61),
            _lap("lap-4", 91_000, wing=9, bias=61),
        ],
        candidate_valid=True,
        candidate_reason="two valid laps",
    )
    invalid = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[_lap("lap-1", 100_000), _lap("lap-2", 101_000)],
        candidate_payloads=[],
        candidate_valid=False,
        candidate_reason="spin recovery",
    )

    assert confounded["reason"] == "candidate_batch_confounded"
    assert confounded["promoted"] is False
    assert invalid["verdict"] == "rejected"
    assert invalid["promoted"] is False


def test_completed_run_persists_plan_outcomes_and_append_only_ledger(tmp_path: Path) -> None:
    plan = _plan()
    outcome = {
        "constraint_key": plan["experiments"][0]["constraint_key"],
        "verdict": "falsified",
        "promoted": False,
        "reason": "candidate_not_significantly_faster",
    }

    run_path = persist_completed_run(
        tmp_path,
        plan=plan,
        outcomes=[outcome],
        created_utc="20260722T000000Z",
    )

    payload = json.loads(run_path.read_text(encoding="utf-8"))
    assert payload["plan"]["plan_id"] == plan["plan_id"]
    assert payload["outcomes"] == [outcome]
    ledger = load_ledger(tmp_path / "journal" / "alien_scientist" / "experiments.jsonl")
    assert ledger[0]["verdict"] == "falsified"
    with pytest.raises(ScientistError, match="scientist_experiment_already_recorded"):
        append_ledger(tmp_path / "journal" / "alien_scientist" / "experiments.jsonl", ledger[0])

    with pytest.raises(ScientistError, match="scientist_run_already_exists"):
        persist_completed_run(
            tmp_path,
            plan=plan,
            outcomes=[outcome],
            created_utc="20260722T000000Z",
        )


def test_completed_run_rejects_unsafe_timestamp_and_empty_outcomes(tmp_path: Path) -> None:
    plan = _plan()
    with pytest.raises(ScientistError, match="scientist_created_utc_invalid"):
        persist_completed_run(
            tmp_path,
            plan=plan,
            outcomes=[{"verdict": "rejected"}],
            created_utc="../../outside",
        )
    with pytest.raises(ScientistError, match="scientist_completed_outcomes_missing"):
        persist_completed_run(
            tmp_path,
            plan=plan,
            outcomes=[],
            created_utc="20260722T000001Z",
        )
