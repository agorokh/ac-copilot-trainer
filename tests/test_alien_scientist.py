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
    meta_priors,
    persist_completed_run,
    scope_key,
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
                    "baseline_flying_laps": 2,
                    "candidate_flying_laps": 2,
                }
            ],
            proposed_hypotheses=[
                {
                    "id": "renamed_same_adjustment",
                    "mechanism": "different prose, identical physical adjustment",
                    "parameter": "WING_2",
                    "direction": -1,
                }
            ],
        )


def test_meta_prior_transfers_across_combos_sharing_scope_key() -> None:
    """#674: falsified constraint for combo A suppresses the same META key on combo B."""
    first = build_plan(
        trigger="pace plateau",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
    )
    constraint = first["experiments"][0]["constraint_key"]
    other_combo = {"car": "car_b", "track": "track_b", "layout": "gp"}
    assert scope_key(_SCOPE) == first["scope_key"]

    ledger = [
        {
            "scope_key": first["scope_key"],
            "scope": dict(_SCOPE),
            "combo": dict(_COMBO),
            "constraint_key": constraint,
            "verdict": "falsified",
            "experiment_id": "run:0",
            "reason": "candidate_not_significantly_faster",
            "baseline_flying_laps": 2,
            "candidate_flying_laps": 2,
        }
    ]
    priors = meta_priors(ledger, scope=_SCOPE)
    assert len(priors) == 1
    assert priors[0]["source_combo"] == _COMBO

    # Wing is suppressed via cross-combo transfer; front bias remains a safe experiment.
    transferred = build_plan(
        trigger="pace plateau other combo",
        combo=other_combo,
        scope=_SCOPE,
        baseline_payloads=[
            {
                **_lap("lap-9", 100_000),
                "car": {"id": "car_b"},
                "track": {"id": "track_b", "layout": "gp"},
            }
        ],
        schema=_schema(),
        ledger=ledger,
        proposed_hypotheses=[
            {
                "id": "plateau_rear_wing",
                "mechanism": "transferred prior must suppress this",
                "parameter": "WING_2",
                "direction": -1,
            },
            {
                "id": "braking_stability_front_bias",
                "mechanism": "unrelated constraint remains available",
                "parameter": "FRONT_BIAS",
                "direction": 1,
            },
        ],
    )
    assert transferred["combo"] == other_combo
    assert transferred["experiments"][0]["parameter"] == "FRONT_BIAS.VALUE"
    assert transferred["suppressed"][0]["transfer"]["mode"] == "cross_combo"
    assert transferred["suppressed"][0]["transfer"]["source_combo"] == _COMBO
    assert transferred["meta_priors"][0]["constraint_key"] == constraint


def test_meta_prior_does_not_transfer_across_different_scope_dimensions() -> None:
    first = build_plan(
        trigger="pace plateau",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
    )
    other_scope = {**_SCOPE, "track_archetype": "long-fast"}
    assert scope_key(other_scope) != first["scope_key"]
    rebuilt = build_plan(
        trigger="pace plateau",
        combo=_COMBO,
        scope=other_scope,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
        ledger=[
            {
                "scope_key": first["scope_key"],
                "constraint_key": first["experiments"][0]["constraint_key"],
                "verdict": "falsified",
            }
        ],
    )
    assert rebuilt["experiments"]
    assert rebuilt["suppressed"] == []


def test_legacy_ledger_row_without_combo_still_suppresses() -> None:
    first = _plan()
    with pytest.raises(ScientistError, match="scientist_constraints_suppressed"):
        build_plan(
            trigger="pace plateau",
            combo={"car": "car_z", "track": "track_z", "layout": None},
            scope=_SCOPE,
            baseline_payloads=[_lap("lap-1", 100_000)],
            schema=_schema(),
            ledger=[
                {
                    "scope_key": first["scope_key"],
                    "constraint_key": first["experiments"][0]["constraint_key"],
                    "verdict": "falsified",
                    "baseline_flying_laps": 2,
                    "candidate_flying_laps": 2,
                }
            ],
            proposed_hypotheses=[
                {
                    "id": "plateau_rear_wing",
                    "mechanism": "legacy row transfer",
                    "parameter": "WING_2",
                    "direction": -1,
                }
            ],
        )


def test_under_evidenced_legacy_falsification_is_retryable_without_ledger_mutation() -> None:
    first = _plan()
    legacy_row = {
        "scope_key": first["scope_key"],
        "constraint_key": first["experiments"][0]["constraint_key"],
        "verdict": "falsified",
        "experiment_id": "legacy-plateau-rear-wing",
    }
    ledger = [legacy_row]

    rebuilt = build_plan(
        trigger="pace plateau retry",
        combo=_COMBO,
        scope=_SCOPE,
        baseline_payloads=[_lap("lap-1", 100_000)],
        schema=_schema(),
        ledger=ledger,
    )

    assert rebuilt["experiments"][0]["constraint_key"] == legacy_row["constraint_key"]
    assert rebuilt["meta_priors"] == []
    assert rebuilt["suppressed"] == []
    assert ledger == [legacy_row]


@pytest.mark.parametrize("bad_count", [True, 2.5, "2"])
def test_malformed_flying_lap_counts_cannot_create_suppressing_prior(bad_count) -> None:
    first = _plan()
    ledger = [
        {
            "scope_key": first["scope_key"],
            "constraint_key": first["experiments"][0]["constraint_key"],
            "verdict": "falsified",
            "baseline_flying_laps": bad_count,
            "candidate_flying_laps": 2,
        }
    ]
    assert meta_priors(ledger, scope=_SCOPE) == []


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
        build_plan(**common, proposed_hypotheses=[duplicate, {**duplicate, "id": "wing_renamed"}])


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
        baseline_payloads=[
            _lap("lap-1", 110_000),
            _lap("lap-2", 100_000),
            _lap("lap-3", 101_000),
        ],
        candidate_payloads=[
            _lap("lap-4", 100_000, wing=9),
            _lap("lap-5", 90_000, wing=9),
            _lap("lap-6", 91_000, wing=9),
        ],
        candidate_valid=True,
        candidate_reason="three valid laps",
    )

    assert outcome["verdict"] == "promoted"
    assert outcome["promoted"] is True
    assert outcome["comparison"]["significant"] is True


def test_experiment_excludes_each_arms_lowest_lap_n_from_comparison() -> None:
    plan = _plan()
    outcome = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[
            _lap("baseline-1", 10_000),
            _lap("baseline-2", 100_000),
            _lap("baseline-3", 100_100),
        ],
        candidate_payloads=[
            _lap("candidate-1", 400_000, wing=9),
            _lap("candidate-2", 90_000, wing=9),
            _lap("candidate-3", 90_100, wing=9),
        ],
        candidate_valid=True,
        candidate_reason="three valid laps",
    )

    assert outcome["verdict"] == "promoted"
    assert outcome["baseline_records"] == 2
    assert outcome["candidate_records"] == 2
    assert outcome["comparison"]["baseline"] == {
        "n": 2,
        "mean_ms": 100_050.0,
        "stdev_ms": pytest.approx(70.711),
    }
    assert outcome["comparison"]["candidate"] == {
        "n": 2,
        "mean_ms": 90_050.0,
        "stdev_ms": pytest.approx(70.711),
    }


def test_experiment_with_one_flying_lap_per_arm_returns_no_verdict() -> None:
    plan = _plan()
    outcome = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[_lap("baseline-1", 110_000), _lap("baseline-2", 100_000)],
        candidate_payloads=[
            _lap("candidate-1", 120_000, wing=9),
            _lap("candidate-2", 90_000, wing=9),
        ],
        candidate_valid=True,
        candidate_reason="two valid laps",
    )

    assert outcome["verdict"] == "no_verdict"
    assert outcome["promoted"] is False
    assert outcome["reason"] == "insufficient_flying_laps"
    assert outcome["baseline_flying_laps"] == 1
    assert outcome["candidate_flying_laps"] == 1
    assert "comparison" not in outcome


@pytest.mark.parametrize("bad_lap_n", [True, 1.5, "2", 2])
def test_experiment_rejects_malformed_or_duplicate_lap_numbers(bad_lap_n) -> None:
    plan = _plan()
    baseline = [
        _lap("baseline-1", 110_000),
        _lap("baseline-2", 100_000),
        _lap("baseline-3", 101_000),
    ]
    baseline[-1]["lap"]["lap_n"] = bad_lap_n

    outcome = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=baseline,
        candidate_payloads=[
            _lap("candidate-1", 100_000, wing=9),
            _lap("candidate-2", 90_000, wing=9),
            _lap("candidate-3", 91_000, wing=9),
        ],
        candidate_valid=True,
        candidate_reason="three valid laps",
    )

    assert outcome["verdict"] == "rejected"
    assert outcome["reason"] == "candidate_batch_lap_n_invalid"


def test_confounded_or_invalid_batch_keeps_last_valid_setup() -> None:
    plan = _plan()
    confounded = evaluate_experiment(
        plan=plan,
        experiment=plan["experiments"][0],
        baseline_payloads=[
            _lap("lap-1", 110_000),
            _lap("lap-2", 100_000),
            _lap("lap-3", 101_000),
        ],
        candidate_payloads=[
            _lap("lap-4", 100_000, wing=9, bias=61),
            _lap("lap-5", 90_000, wing=9, bias=61),
            _lap("lap-6", 91_000, wing=9, bias=61),
        ],
        candidate_valid=True,
        candidate_reason="three valid laps",
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
    assert invalid["verdict"] == "no_verdict"
    assert invalid["reason"] == "insufficient_flying_laps"
    assert invalid["promoted"] is False


def test_completed_run_persists_plan_outcomes_and_append_only_ledger(tmp_path: Path) -> None:
    plan = _plan()
    outcome = {
        "constraint_key": plan["experiments"][0]["constraint_key"],
        "verdict": "falsified",
        "promoted": False,
        "reason": "candidate_not_significantly_faster",
        "baseline_flying_laps": 2,
        "candidate_flying_laps": 2,
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
    assert ledger[0]["scope"] == _SCOPE
    assert ledger[0]["combo"] == _COMBO
    assert ledger[0]["scope_key"] == plan["scope_key"]
    assert ledger[0]["baseline_flying_laps"] == 2
    assert ledger[0]["candidate_flying_laps"] == 2
    with pytest.raises(ScientistError, match="scientist_experiment_already_recorded"):
        append_ledger(tmp_path / "journal" / "alien_scientist" / "experiments.jsonl", ledger[0])

    with pytest.raises(ScientistError, match="scientist_run_already_exists"):
        persist_completed_run(
            tmp_path,
            plan=plan,
            outcomes=[outcome],
            created_utc="20260722T000000Z",
        )


def test_no_verdict_run_is_audited_without_mutating_the_ledger(tmp_path: Path) -> None:
    plan = _plan()
    outcome = {
        "constraint_key": plan["experiments"][0]["constraint_key"],
        "verdict": "no_verdict",
        "promoted": False,
        "reason": "insufficient_flying_laps",
        "baseline_flying_laps": 1,
        "candidate_flying_laps": 1,
    }

    run_path = persist_completed_run(
        tmp_path,
        plan=plan,
        outcomes=[outcome],
        created_utc="20260722T000003Z",
    )

    payload = json.loads(run_path.read_text(encoding="utf-8"))
    assert payload["outcomes"] == [outcome]
    ledger_path = tmp_path / "journal" / "alien_scientist" / "experiments.jsonl"
    assert not ledger_path.exists()


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


@pytest.mark.parametrize("redirect", ["scientist_root", "runs", "ledger"])
def test_completed_run_rejects_state_symlink_redirection(tmp_path: Path, redirect: str) -> None:
    user_dir = tmp_path / "Assetto Corsa"
    outside = tmp_path / "outside"
    outside.mkdir()
    scientist_root = user_dir / "journal" / "alien_scientist"
    if redirect == "scientist_root":
        scientist_root.parent.mkdir(parents=True)
        scientist_root.symlink_to(outside, target_is_directory=True)
    else:
        scientist_root.mkdir(parents=True)
        target = scientist_root / ("runs" if redirect == "runs" else "experiments.jsonl")
        external = outside if redirect == "runs" else outside / "experiments.jsonl"
        if redirect == "ledger":
            external.write_text("sentinel\n", encoding="utf-8")
        target.symlink_to(external, target_is_directory=redirect == "runs")

    with pytest.raises(ScientistError, match="scientist_state_path_unsafe"):
        persist_completed_run(
            user_dir,
            plan=_plan(),
            outcomes=[{"verdict": "rejected", "reason": "test"}],
            created_utc="20260722T000002Z",
        )
    assert sorted(path.name for path in outside.iterdir()) in ([], ["experiments.jsonl"])
