from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.ac_harness import init_perturber_ab as ab_mod
from tools.ac_harness.init_perturber_ab import (
    ANALYSIS_SCHEMA,
    BASELINE_ONSET_INDEX_GRACEFUL,
    DEFAULT_LAUNCHES_PER_BOOT,
    MAX_BOOTS_PER_ARM,
    MAX_UNDELIVERED_FRACTION,
    MIN_BOOTS_PER_ARM,
    MIN_LAUNCHES_PER_BOOT,
    POST_ONSET_WINDOW,
    SUPERSEDED_PLAN_SCHEMA,
    WITHDRAWN_PLAN_SCHEMA,
    BootObservation,
    LaunchObservation,
    analyze,
    build_plan,
    exact_block_permutation_two_sided,
    exact_rank_sum_two_sided,
    load_observations,
    load_plan,
    paired_exact_two_sided,
    randomized_block_sequence,
    render_markdown,
    summarize_boot,
)
from tools.ac_harness.resilient_launch import DEFAULT_GO_LIVE_TIMEOUT, REPORT_SCHEMA

_LAUNCHES = 20


def _launch_config(launches: int = _LAUNCHES) -> dict[str, object]:
    return {
        "car": "ks_porsche_911_gt3_r_2016",
        "track": "spa",
        "layout": None,
        "stability_window": 140.0,
        "go_live_timeout": DEFAULT_GO_LIVE_TIMEOUT,
        "trials_per_invocation": launches,
    }


def _default_delivery(verdicts: list[str]) -> list[bool | None]:
    """#710 delivery flags for a verdict list, defaulting never_live to 'never reached AC'.

    Every other verdict is only reachable through a live ``acs.exe``, so it delivered a cycle.
    The delivered-``never_live`` shape (acs.exe appeared then exited) is exercised by passing
    ``delivered`` explicitly.
    """
    return [verdict != "never_live" for verdict in verdicts]


#: "We could not look" — the honest no-information default for fixtures (#719).
_UNAVAILABLE_PERTURBERS = {"steam_overlay": "unavailable", "nvidia_capture": "unavailable"}
_INJECTED_PERTURBERS = {"steam_overlay": "injected", "nvidia_capture": "injected"}
_ABSENT_PERTURBERS = {"steam_overlay": "not_observed", "nvidia_capture": "not_observed"}


def _write_boot_report(
    path: Path,
    *,
    verdicts: list[str],
    start_minute: int,
    uptime_start: float,
    launch: dict[str, object] | None = None,
    attempts: int | None = None,
    delivered: list[bool | None] | None = None,
    perturbers: dict[str, str] | None = None,
    condition: str | None = None,
) -> None:
    """Emit one ``resilient_launch --trials N`` style report for a whole boot."""
    counts = {"stable": 0, "froze": 0, "wedged_init": 0, "never_live": 0}
    flags = _default_delivery(verdicts) if delivered is None else delivered
    # Prefer arm-matching evidence so analysis fixtures are not silently `unverified` under the
    # receipt gate (#721). Explicit `perturbers=` still wins; unavailable is the pre-receipt default
    # only when no condition is known.
    if perturbers is not None:
        evidence = perturbers
    elif condition is not None:
        evidence = _default_perturbers_for(condition)
    else:
        evidence = _UNAVAILABLE_PERTURBERS
    log = []
    for index, (verdict, delivery) in enumerate(zip(verdicts, flags, strict=True), start=1):
        counts[verdict] += 1
        minute = start_minute + index
        # Only stable is post-race for absence; keep injected on any verdict, demote
        # not_observed to unavailable on non-stable rows so analyze fixtures stay confirmed.
        row_evidence = dict(evidence)
        if verdict != "stable":
            row_evidence = {
                key: (
                    value
                    if value == "injected"
                    else ("unavailable" if value == "not_observed" else value)
                )
                for key, value in evidence.items()
            }
        log.append(
            {
                "attempt": index,
                "verdict": verdict,
                "cycle_delivered": delivery,
                "perturbers": row_evidence,
                "started_at_utc": f"2026-07-28T{minute // 60:02d}:{minute % 60:02d}:00Z",
                "elapsed_s": 12.5,
                "uptime_h": round(uptime_start + index * 0.05, 4),
            }
        )
    payload = {
        "schema": REPORT_SCHEMA,
        "verdict": verdicts[-1],
        "attempts": len(verdicts) if attempts is None else attempts,
        "counts": counts,
        "cycles": {
            "delivered": sum(flag is True for flag in flags),
            "undelivered": sum(flag is False for flag in flags),
            "undetermined": sum(flag is None for flag in flags),
        },
        "launch": launch or _launch_config(len(verdicts)),
        "attempts_log": log,
    }
    if condition == "overlays_on":
        payload["expect_perturbers"] = "on"
    elif condition == "overlays_off":
        payload["expect_perturbers"] = "off"
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stable_then_freeze(onset: int, total: int = _LAUNCHES) -> list[str]:
    """``onset``-1 clean launches, then a freeze, then an alternating burst."""
    verdicts = ["stable"] * (onset - 1)
    for index in range(onset, total + 1):
        verdicts.append("froze" if (index - onset) % 2 == 0 else "stable")
    return verdicts[:total]


def _default_perturbers_for(condition: str) -> dict[str, str]:
    """Matching receipt evidence so analysis fixtures are not silently unverified (#721)."""

    if condition == "overlays_on":
        return dict(_INJECTED_PERTURBERS)
    if condition == "overlays_off":
        return dict(_ABSENT_PERTURBERS)
    return dict(_UNAVAILABLE_PERTURBERS)


def _boot(
    number: int,
    condition: str,
    verdicts: list[str],
    *,
    uptime_start: float = 0.5,
    delivered: list[bool | None] | None = None,
    perturbers: dict[str, str] | None = None,
) -> BootObservation:
    flags = _default_delivery(verdicts) if delivered is None else delivered
    base = dict(perturbers or _default_perturbers_for(condition))

    def _row_evidence(verdict: str) -> tuple[tuple[str, str], ...]:
        # Only stable is post-race for absence; demote not_observed on other verdicts.
        if verdict == "stable":
            return tuple(sorted(base.items()))
        demoted = {
            key: (
                value
                if value == "injected"
                else ("unavailable" if value == "not_observed" else value)
            )
            for key, value in base.items()
        }
        return tuple(sorted(demoted.items()))

    return BootObservation(
        boot=number,
        condition=condition,
        launches=tuple(
            LaunchObservation(
                launch=index,
                verdict=verdict,
                started_at_utc=f"2026-07-28T10:{index:02d}:00Z",
                elapsed_s=12.5,
                uptime_h=uptime_start + index * 0.05,
                cycle_delivered=delivery,
                perturbers=_row_evidence(verdict),
            )
            for index, (verdict, delivery) in enumerate(zip(verdicts, flags, strict=True), start=1)
        ),
    )


def _ambiguous_boot(number: int, condition: str) -> BootObservation:
    """A boot whose onset position is genuinely unknown (#710).

    Since #710 an undelivered attempt merely SHIFTS the onset's cycle position, so the only
    remaining ambiguity is a report that does not know whether an attempt reached AC —
    ``cycle_delivered: null``, which a rig run never emits but the schema still admits.
    """
    verdicts = ["stable"] * 5 + ["never_live"] + ["froze"] + ["stable"] * 13
    delivered = _default_delivery(verdicts)
    delivered[5] = None
    return _boot(number, condition, verdicts, delivered=delivered)


# _LAUNCHES == MIN_LAUNCHES_PER_BOOT, so the default fixtures are endpoint-eligible.
assert _LAUNCHES == MIN_LAUNCHES_PER_BOOT


def _blocks(onsets_on: list[int], onsets_off: list[int]) -> list[BootObservation]:
    """One block per (on, off) pair, in plan order."""
    boots: list[BootObservation] = []
    for on_onset, off_onset in zip(onsets_on, onsets_off, strict=True):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", _stable_then_freeze(off_onset)))
    return boots


# --------------------------------------------------------------------------- plan


def test_randomized_block_sequence_is_seeded_and_one_arm_per_block() -> None:
    sequence = randomized_block_sequence(6)
    assert len(sequence) == 12
    assert sequence.count("overlays_on") == sequence.count("overlays_off") == 6
    assert all(
        set(sequence[offset : offset + 2]) == {"overlays_on", "overlays_off"}
        for offset in range(0, len(sequence), 2)
    )
    assert sequence == randomized_block_sequence(6)
    assert sequence != randomized_block_sequence(6, randomization_seed=626)


def test_randomization_reference_set_is_the_full_two_to_the_blocks() -> None:
    """The whole power argument rests on this: independent per-block orientation gives 2**n.

    The earlier balanced-counterbalancing draft could only emit
    ``n!/((n//2)!*(n-n//2)!)`` orders — 6 at n=4 — which caps the attainable two-sided p at
    0.33 and makes the experiment unable to reach alpha at any effect size.
    """
    for blocks in (3, 4, 5):
        emitted = {randomized_block_sequence(blocks, randomization_seed=s) for s in range(4000)}
        assert len(emitted) == 2**blocks


def test_plan_is_boot_scoped_and_records_the_operator_gate() -> None:
    plan = build_plan(6, generated_at_utc="2026-07-28T12:00:00Z")
    assert plan["schema"] == "init-perturber-ab-plan/v4"
    assert plan["supersedes"] == [
        WITHDRAWN_PLAN_SCHEMA,
        SUPERSEDED_PLAN_SCHEMA,
        "init-perturber-ab-plan/v3",
    ]
    assert plan["treatment_receipt"]["enabled"] is True
    assert plan["treatment_receipt"]["expect_perturbers_in_commands"] is True
    assert plan["operator_owned_settings"] is True
    assert plan["protocol"]["reboot_before_every_boot"] is True
    assert plan["protocol"]["graceful_first_teardown_both_arms"] is True
    assert plan["protocol"]["one_invocation_per_boot"] is True
    assert plan["protocol"]["retry_after_abort_requires_reboot"] is True
    assert "REBOOT" in plan["protocol"]["abort_policy"].upper()
    assert plan["protocol"]["condition_definitions"]["overlays_off"] == {
        "steam_overlay_enabled": False,
        "nvidia_shadowplay_enabled": False,
    }
    assert "onset DELIVERED-CYCLE index" in plan["endpoints"]["primary"]
    assert plan["randomization_reference_set"] == 2**6
    assert plan["smallest_attainable_two_sided_p"] == pytest.approx(2 / 64)
    assert plan["prereg_baselines"]["onset_index_graceful"] == BASELINE_ONSET_INDEX_GRACEFUL
    assert "false negative" in plan["withdrawn_design_note"]
    assert plan["launch"]["trials_per_invocation"] == DEFAULT_LAUNCHES_PER_BOOT
    assert len(plan["boots"]) == 12
    assert plan["run_id"]
    assert (
        plan["boots"][0]["report"]
        == f"boot-001-{plan['run_id']}-{plan['boots'][0]['condition']}.json"
    )


def test_a_real_plan_draws_its_seed_rather_than_reusing_a_constant() -> None:
    """Codex #708 P1: the design-based claim requires the schedule to be DRAWN.

    With a constant default seed the planner emitted one fixed schedule, so no assignment was
    ever randomized and enumerating the `2**blocks` alternative orientations was not justified —
    a boot-slot or time effect could align with the fixed order with nothing to appeal to.
    """
    stamp = "2026-07-28T12:00:00Z"
    seeds = {build_plan(6, generated_at_utc=stamp)["randomization_seed"] for _ in range(8)}
    assert len(seeds) > 1, "a real plan must draw a fresh seed, not reuse a constant"
    # The drawn seed is persisted, so the schedule stays verifiable and reproducible after the fact.
    drawn = build_plan(6, generated_at_utc=stamp)
    assert tuple(boot["condition"] for boot in drawn["boots"]) == randomized_block_sequence(
        6, randomization_seed=drawn["randomization_seed"]
    )
    # An explicit seed is still honoured, for reproducing a known plan.
    assert (
        build_plan(6, generated_at_utc=stamp, randomization_seed=625)["randomization_seed"] == 625
    )


def test_build_plan_rejects_sizes_it_could_not_answer_or_analyze() -> None:
    # Too few blocks: 2/2**5 = 0.0625 > alpha, so no result could ever be significant.
    with pytest.raises(ValueError, match="cannot reach alpha"):
        build_plan(MIN_BOOTS_PER_ARM - 1)
    # Too short a boot: no room for the graceful onset plus the fixed burst window.
    with pytest.raises(ValueError, match=str(MIN_LAUNCHES_PER_BOOT)):
        build_plan(MIN_BOOTS_PER_ARM, launches_per_boot=MIN_LAUNCHES_PER_BOOT - 1)
    # Too many blocks: the exact enumeration would exceed the limit, so a COMPLETED (and very
    # expensive) run would not be analyzable. Refuse at plan time, not after the reboots.
    with pytest.raises(ValueError, match="would not be analyzable"):
        build_plan(MAX_BOOTS_PER_ARM + 1)
    # The cap is derived from the PRIMARY test's enumeration, not picked:
    # 2**19 fits under the limit, 2**20 does not.
    assert 2**MAX_BOOTS_PER_ARM <= ab_mod.MAX_EXACT_PERMUTATIONS
    assert 2 ** (MAX_BOOTS_PER_ARM + 1) > ab_mod.MAX_EXACT_PERMUTATIONS


def test_oversized_rank_sum_sensitivity_degrades_instead_of_failing() -> None:
    """The non-gating rank-sum must never break an analysis the primary test can score."""
    boots = _blocks(list(range(6, 18)), list(range(8, 20)))  # 12 blocks -> C(24,12) > limit
    import math

    assert math.comb(24, 12) > ab_mod.MAX_EXACT_PERMUTATIONS
    result = analyze(boots)
    assert result["sensitivity"]["onset_rank_sum_two_sided_p"] is None
    assert result["onset_block_permutation_two_sided_p"] is not None
    assert result["usable_blocks"] == 12


def test_min_launches_per_boot_covers_baseline_onset_plus_the_burst_window() -> None:
    assert MIN_LAUNCHES_PER_BOOT == BASELINE_ONSET_INDEX_GRACEFUL + POST_ONSET_WINDOW


def test_load_plan_rejects_the_withdrawn_v1_design(tmp_path: Path) -> None:
    """The refuted interleaved single-boot plan must not be analyzable (#625 redesign)."""
    stale = tmp_path / "plan.json"
    stale.write_text(json.dumps({"schema": WITHDRAWN_PLAN_SCHEMA}), encoding="utf-8")
    with pytest.raises(ValueError, match="withdrawn"):
        load_plan(stale)


def test_load_plan_rejects_reordered_schedule(tmp_path: Path) -> None:
    plan = build_plan(2, launches_per_boot=_LAUNCHES, allow_undersized=True)
    plan["boots"][0]["condition"], plan["boots"][1]["condition"] = (
        plan["boots"][1]["condition"],
        plan["boots"][0]["condition"],
    )
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="randomization_seed"):
        load_plan(path)


def test_load_plan_rejects_same_arm_block(tmp_path: Path) -> None:
    plan = build_plan(2, launches_per_boot=_LAUNCHES, allow_undersized=True)
    plan["boots"][1]["condition"] = plan["boots"][0]["condition"]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="condition|arm|randomization_seed"):
        load_plan(path)


# ------------------------------------------------------------------- report load


def _two_boot_plan() -> dict[str, object]:
    return build_plan(1, launches_per_boot=_LAUNCHES, allow_undersized=True)


def test_report_must_cover_every_planned_launch(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * (_LAUNCHES - 1),
        start_minute=0,
        uptime_start=0.5,
    )
    with pytest.raises(ValueError, match="requires exactly"):
        load_observations(plan, tmp_path, require_complete=False)


def test_report_attempts_header_must_match_its_log(tmp_path: Path) -> None:
    """A truncated log behind a full ``attempts`` header would fake a complete boot."""
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * (_LAUNCHES - 2),
        start_minute=0,
        uptime_start=0.5,
        attempts=_LAUNCHES,
    )
    with pytest.raises(ValueError, match="must log all"):
        load_observations(plan, tmp_path, require_complete=False)


def test_report_counts_must_match_the_attempts_log(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    path = tmp_path / plan["boots"][0]["report"]
    _write_boot_report(
        path,
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["counts"]["stable"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="counts"):
        load_observations(plan, tmp_path, require_complete=False)


def _mutate_first_report(tmp_path: Path, plan: dict[str, object], mutate) -> None:
    path = tmp_path / plan["boots"][0]["report"]
    _write_boot_report(
        path,
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_v1_reports_are_rejected_with_a_reason(tmp_path: Path) -> None:
    """#710 — a v1 report has no delivery flag, so its never_live rows cannot be mapped."""
    plan = _two_boot_plan()

    def drop_delivery(payload: dict) -> None:
        payload["schema"] = "resilient-launch-report/v1"
        payload.pop("cycles")
        for row in payload["attempts_log"]:
            row.pop("cycle_delivered")

    _mutate_first_report(tmp_path, plan, drop_delivery)
    with pytest.raises(ValueError, match="withdrawn"):
        load_observations(plan, tmp_path, require_complete=False)


def test_missing_cycle_delivered_is_rejected(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _mutate_first_report(tmp_path, plan, lambda p: p["attempts_log"][3].pop("cycle_delivered"))
    with pytest.raises(ValueError, match="missing cycle_delivered"):
        load_observations(plan, tmp_path, require_complete=False)


def test_a_live_verdict_claimed_as_undelivered_is_rejected(tmp_path: Path) -> None:
    """Only never_live may lack a delivered cycle; anything else needs a live acs.exe."""
    plan = _two_boot_plan()

    def lie(payload: dict) -> None:
        payload["attempts_log"][3]["cycle_delivered"] = False
        payload["cycles"] = {"delivered": _LAUNCHES - 1, "undelivered": 1, "undetermined": 0}

    _mutate_first_report(tmp_path, plan, lie)
    with pytest.raises(ValueError, match="only never_live"):
        load_observations(plan, tmp_path, require_complete=False)


def test_cycles_block_must_match_the_attempts_log(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _mutate_first_report(tmp_path, plan, lambda p: p["cycles"].__setitem__("delivered", 0))
    with pytest.raises(ValueError, match="cycles block"):
        load_observations(plan, tmp_path, require_complete=False)


def test_delivery_flags_survive_the_report_round_trip(tmp_path: Path) -> None:
    """End-to-end: what the launcher writes is what ``summarize_boot`` scores (#710)."""
    plan = _two_boot_plan()
    verdicts = ["stable"] * 9 + ["never_live"] + ["froze"] + ["stable"] * 9
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=verdicts,
        start_minute=0,
        uptime_start=0.5,
    )
    observations = load_observations(plan, tmp_path, require_complete=False)
    summary = summarize_boot(observations[0])
    assert [item.cycle_delivered for item in observations[0].launches] == _default_delivery(
        verdicts
    )
    assert (summary.onset_index, summary.onset_cycle) == (11, 10)
    assert summary.onset_ambiguous is False


def test_incomplete_experiment_is_refused(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    with pytest.raises(ValueError, match="incomplete"):
        load_observations(plan, tmp_path)


def test_continuous_uptime_across_a_boundary_is_refused(tmp_path: Path) -> None:
    """The sharpest boot-scoped guard: two arms on one boot pools the accumulator.

    Detected by comparing the IMPLIED BOOT EPOCH (`started_at_utc - uptime_h`): two launches
    from the same boot agree on it, and a reboot moves it forward.
    """
    plan = _two_boot_plan()
    # Boot 1 launches at minutes 1..20 -> last uptime 0.5 + 20*0.05 = 1.5h at minute 20.
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    # Boot 2's first launch is 41 min later; uptime advanced by exactly the same 41 min
    # (1.5h + 0.6833h = 2.1833h, minus the +0.05 the writer adds for launch 1) -> no reboot.
    _write_boot_report(
        tmp_path / plan["boots"][1]["report"],
        condition=plan["boots"][1]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=60,
        uptime_start=1.5 + (41 / 60) - 0.05,
    )
    with pytest.raises(ValueError, match="share a machine boot epoch"):
        load_observations(plan, tmp_path)


def test_report_names_are_namespaced_to_their_plan() -> None:
    """Codex #708: two same-seed plans must not collide in one reports directory.

    Deterministic `boot-NNN-condition.json` names meant a second run's `analyze` could silently
    consume the FIRST experiment's reports and return a stale conclusion — after a dozen reboots.
    """
    # A real plan DRAWS its seed, so reproducibility needs both the stamp and the seed pinned.
    pinned = dict(generated_at_utc="2026-07-28T12:00:00Z", randomization_seed=625)
    first = build_plan(6, **pinned)
    same = build_plan(6, **pinned)
    later = build_plan(6, generated_at_utc="2026-07-29T12:00:00Z", randomization_seed=625)
    other_car = build_plan(6, car="ks_mazda_mx5_cup", **pinned)
    names = lambda plan: [boot["report"] for boot in plan["boots"]]  # noqa: E731
    # Reproducible for identical inputs...
    assert names(first) == names(same)
    # ...and distinct for a different generation time or launch config, even at the same seed.
    assert set(names(first)).isdisjoint(names(later))
    assert set(names(first)).isdisjoint(names(other_car))
    assert first["randomization_seed"] == later["randomization_seed"]


def test_run_id_covers_every_plan_input_and_gets_fresh_entropy() -> None:
    """Codex #708: a same-tick regeneration must not reuse the namespace.

    `generated_at_utc` is only second-resolution, and a collision is expensive — the second
    physical run burns a whole boot's launch budget before the exclusive report write fails.
    """
    pinned = dict(generated_at_utc="2026-07-28T12:00:00Z", randomization_seed=625)
    baseline = build_plan(6, **pinned)["run_id"]
    # Deterministic when the caller pins the inputs (reproducing a known plan, tests).
    assert build_plan(6, **pinned)["run_id"] == baseline
    # Launch parameters that used to be omitted from the hash now change the namespace.
    assert build_plan(6, stability_window=99.0, **pinned)["run_id"] != baseline
    assert build_plan(6, go_live_timeout=99.0, **pinned)["run_id"] != baseline
    # The nonce is what breaks a same-second collision: identical inputs AND an identical
    # pinned timestamp still separate once the nonce differs.
    assert (
        build_plan(6, run_nonce="a", **pinned)["run_id"]
        != build_plan(6, run_nonce="b", **pinned)["run_id"]
    )
    # A real run pins nothing, so two plans generated inside one tick cannot share a namespace.
    assert build_plan(6)["run_id"] != build_plan(6)["run_id"]


def test_reboot_is_accepted_even_when_the_operator_waits_a_long_time(tmp_path: Path) -> None:
    """Qodo #708: a real reboot after a long wait can leave uptime numerically HIGHER.

    The earlier magnitude check (`later.first_uptime < earlier.last_uptime`) false-rejected
    this, which would make an already-completed 12-reboot experiment un-analyzable.
    """
    plan = _two_boot_plan()
    # Boot 1 ends at uptime 1.5h.
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    # Reboot, then the operator leaves the rig up overnight before starting boot 2, so its
    # first launch sits at uptime 9.0h — HIGHER than boot 1's last (1.5h) — yet uptime clearly
    # did not track the ~16h of wall clock since boot 1's final launch.
    _write_boot_report(
        tmp_path / plan["boots"][1]["report"],
        condition=plan["boots"][1]["condition"],
        verdicts=_stable_then_freeze(14),
        start_minute=1000,
        uptime_start=9.0,
    )
    observations = load_observations(plan, tmp_path)
    assert observations[1].launches[0].uptime_h > observations[0].launches[-1].uptime_h
    assert summarize_boot(observations[1]).onset_index == 14


def test_boot_boundary_accepts_a_real_reboot(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=2.0,
    )
    _write_boot_report(
        tmp_path / plan["boots"][1]["report"],
        condition=plan["boots"][1]["condition"],
        verdicts=_stable_then_freeze(14),
        start_minute=200,
        uptime_start=0.1,
    )
    observations = load_observations(plan, tmp_path)
    assert len(observations) == 2
    assert summarize_boot(observations[1]).onset_index == 14


def test_mid_boot_uptime_drop_is_refused(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    path = tmp_path / plan["boots"][0]["report"]
    _write_boot_report(
        path,
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["attempts_log"][10]["uptime_h"] = 0.01
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="nondecreasing within a boot"):
        load_observations(plan, tmp_path, require_complete=False)


def test_report_launch_must_match_plan(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    wrong = _launch_config()
    wrong["car"] = "wrong_car"
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        condition=plan["boots"][0]["condition"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
        launch=wrong,
    )
    with pytest.raises(ValueError, match="launch.car"):
        load_observations(plan, tmp_path, require_complete=False)


# ------------------------------------------------------------------ boot summary


def test_onset_index_and_fixed_burst_window_start_at_onset() -> None:
    # Reproduces the #668 graceful battery shape: 13 clean, then 14/15 froze, then stable.
    verdicts = ["stable"] * 13 + ["froze", "froze", "stable"] + ["stable"] * 4
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.onset_index == 14
    assert summary.onset_censored is False
    assert summary.onset_value == 14
    # Fixed window is launches 14..19 inclusive -> 6 launches, 2 freezes (NOT to the boot end).
    assert summary.burst_window == POST_ONSET_WINDOW
    assert summary.burst_window_complete is True
    assert summary.post_onset_launches == 6
    assert summary.post_onset_freezes == 2
    assert summary.post_onset_burst_rate == pytest.approx(2 / 6)
    assert summary.usable is True


def test_fixed_window_gives_equal_exposure_regardless_of_onset() -> None:
    """Codex #708: an early-onset boot must not get a longer follow-up than a late-onset one.

    One freeze at onset then all stable: with a to-the-end window these would report 1/15 vs
    1/3; with the fixed window both report 1/6.
    """
    early = ["stable"] * 5 + ["froze"] + ["stable"] * 14
    late = ["stable"] * 17 + ["froze"] + ["stable"] * 2
    early_summary = summarize_boot(_boot(1, "overlays_on", early))
    late_summary = summarize_boot(_boot(2, "overlays_off", late))
    assert early_summary.post_onset_launches == POST_ONSET_WINDOW
    assert early_summary.post_onset_burst_rate == pytest.approx(1 / POST_ONSET_WINDOW)
    # The late boot's window runs past the end of the boot -> no secondary observation at all,
    # rather than a short window masquerading as a comparable one.
    assert late_summary.burst_window_complete is False
    assert late_summary.post_onset_burst_rate is None
    assert late_summary.onset_index == 18  # the primary endpoint is unaffected


def test_censored_boot_gets_a_surrogate_beyond_every_observable_onset() -> None:
    summary = summarize_boot(_boot(1, "overlays_off", ["stable"] * _LAUNCHES))
    assert summary.onset_index is None
    assert summary.onset_censored is True
    assert summary.onset_value == _LAUNCHES + 1
    assert summary.onset_ambiguous is False
    assert summary.post_onset_launches == 0
    assert summary.post_onset_burst_rate is None
    assert summary.usable is True


def test_censored_boot_is_bounded_by_its_delivered_cycles() -> None:
    """#710: censoring is known in DELIVERED cycles, and now those are recorded.

    "No freeze in N launches" bounds the onset above the number of cycles actually delivered.
    Before #710 an undelivered attempt made that number unknown and the boot was discarded; now
    the surrogate is simply ``delivered + 1`` instead of ``launches + 1``, which is the whole
    point — an arm with more delivery failures no longer looks like it stayed clean for longer.
    """
    verdicts = ["stable"] * (_LAUNCHES - 1) + ["never_live"]
    summary = summarize_boot(_boot(1, "overlays_off", verdicts))
    assert summary.onset_index is None
    assert summary.onset_censored is True
    assert summary.delivered_cycles == _LAUNCHES - 1
    assert summary.undelivered_launches == 1
    assert summary.onset_ambiguous is False
    # ``launches + 1`` would have been 21 — one cycle of credit the accumulator never saw.
    assert summary.onset_value == _LAUNCHES


def test_undelivered_launch_before_onset_shifts_the_onset_cycle() -> None:
    """#710 — the recovered statistical power: this boot used to be discarded entirely.

    The freeze is the 11th report row but only the 10th launch cycle the accumulator saw,
    because one attempt never reached AC. Scoring it at 11 would overstate how long the arm
    stayed clean; discarding the boot (the pre-#710 fallback) cost a physical reboot.
    """
    verdicts = ["stable"] * 9 + ["never_live"] + ["froze"] + ["stable"] * 9
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.onset_index == 11
    assert summary.onset_cycle == 10
    assert summary.onset_value == 10
    assert summary.undetermined_before_onset == 0
    assert summary.onset_ambiguous is False
    assert summary.usable is True


def test_a_delivered_never_live_still_consumes_a_cycle() -> None:
    """The other never_live shape: acs.exe appeared then exited, so the accumulator advanced."""
    verdicts = ["stable"] * 9 + ["never_live"] + ["froze"] + ["stable"] * 9
    delivered = _default_delivery(verdicts)
    delivered[9] = True  # the never_live DID spawn acs.exe
    summary = summarize_boot(_boot(1, "overlays_on", verdicts, delivered=delivered))
    assert summary.onset_index == 11
    assert summary.onset_cycle == 11
    assert summary.delivered_cycles == _LAUNCHES
    assert summary.onset_ambiguous is False


def test_unknown_delivery_before_onset_is_the_only_remaining_ambiguity() -> None:
    """#710 narrows ``onset_ambiguous`` to reports that genuinely do not know."""
    verdicts = ["stable"] * 9 + ["never_live"] + ["froze"] + ["stable"] * 9
    delivered = _default_delivery(verdicts)
    delivered[9] = None
    summary = summarize_boot(_boot(1, "overlays_on", verdicts, delivered=delivered))
    assert summary.undetermined_before_onset == 1
    assert summary.onset_ambiguous is True
    # Still a usable boot for reporting; it just cannot contribute an onset observation.
    assert summary.usable is True


def test_undelivered_launch_after_onset_extends_the_burst_window() -> None:
    verdicts = ["stable"] * 5 + ["froze"] + ["never_live"] + ["stable"] * 13
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.onset_index == 6
    assert summary.onset_cycle == 6
    assert summary.onset_ambiguous is False
    # #710: the window is counted in delivered CYCLES, so the undelivered attempt is skipped and
    # the full pre-registered exposure is still collected — where the pre-#710 code voided the
    # window rather than shrink the denominator.
    assert summary.burst_window_complete is True
    assert summary.post_onset_launches == POST_ONSET_WINDOW
    assert summary.post_onset_freezes == 1
    assert summary.post_onset_burst_rate == pytest.approx(1 / POST_ONSET_WINDOW)


def test_undelivered_heavy_boot_is_unusable_not_scored() -> None:
    undelivered = int(MAX_UNDELIVERED_FRACTION * _LAUNCHES) + 1
    verdicts = ["never_live"] * undelivered + ["stable"] * (_LAUNCHES - undelivered)
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.usable is False
    assert summary.unusable_reason == "undelivered_fraction_exceeded"


def test_never_live_heavy_boot_stays_usable_when_the_cycles_were_delivered() -> None:
    """#710 — the exclusion is about DELIVERY failures, not about the never_live verdict."""
    count = int(MAX_UNDELIVERED_FRACTION * _LAUNCHES) + 1
    verdicts = ["never_live"] * count + ["stable"] * (_LAUNCHES - count)
    summary = summarize_boot(_boot(1, "overlays_on", verdicts, delivered=[True] * _LAUNCHES))
    assert summary.never_live == count
    assert summary.undelivered_launches == 0
    assert summary.usable is True


def test_boot_that_never_reached_ac_at_all_is_unusable() -> None:
    verdicts = ["never_live"] * _LAUNCHES
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.delivered_cycles == 0
    assert summary.usable is False
    assert summary.unusable_reason == "no_delivered_cycles"


def test_all_never_live_boot_stays_usable_when_every_cycle_was_delivered() -> None:
    """#710 Codex P2 — usability is about DELIVERY, not about another verdict happening to occur.

    20 delivered never_live cycles are a perfectly good censored observation; discarding them
    while scoring 19 of the same cycles plus one stable row was the old ``classified == 0`` bug.
    """
    verdicts = ["never_live"] * _LAUNCHES
    summary = summarize_boot(_boot(1, "overlays_on", verdicts, delivered=[True] * _LAUNCHES))
    assert summary.classified == 0
    assert summary.delivered_cycles == _LAUNCHES
    assert summary.usable is True
    assert summary.onset_censored is True
    assert summary.onset_value == _LAUNCHES + 1


def test_unknown_delivery_inside_the_burst_window_voids_it() -> None:
    """#710 Codex P2 — an unknown row cannot be skipped over to fill the window.

    If it really delivered, it belongs inside the registered six cycles and the later row that
    took its slot does not, so the computed rate would cover the wrong window.
    """
    verdicts = ["stable"] * 5 + ["froze"] + ["never_live"] + ["stable"] * 13
    delivered = _default_delivery(verdicts)
    delivered[6] = None  # AFTER onset, so the onset itself stays unambiguous
    summary = summarize_boot(_boot(1, "overlays_on", verdicts, delivered=delivered))
    assert summary.onset_cycle == 6
    assert summary.onset_ambiguous is False
    assert summary.burst_window_complete is False
    assert summary.post_onset_burst_rate is None


def test_wedged_init_counts_as_onset() -> None:
    verdicts = ["stable"] * 5 + ["wedged_init"] + ["stable"] * 14
    assert summarize_boot(_boot(1, "overlays_on", verdicts)).onset_index == 6


# -------------------------------------------------------------------- statistics


def test_paired_exact_uses_only_discordant_pairs() -> None:
    assert paired_exact_two_sided(0, 0) == 1.0
    assert paired_exact_two_sided(10, 0) == pytest.approx(0.001953125)
    assert paired_exact_two_sided(5, 5) == 1.0


def test_block_permutation_matches_the_randomization_reference_set() -> None:
    # All differences same sign -> only the two all-same-sign flips are as extreme: 2/2**n.
    assert exact_block_permutation_two_sided([3.0] * 6) == pytest.approx(2 / 64)
    assert exact_block_permutation_two_sided([-3.0] * 6) == pytest.approx(2 / 64)
    # 5 blocks cannot reach alpha=0.05 even under perfect separation -> hence the floor of 6.
    assert exact_block_permutation_two_sided([3.0] * 5) == pytest.approx(2 / 32)
    assert 2 / 32 > 0.05 >= 2 / 64
    # Symmetric/no-signal data returns 1.0.
    assert exact_block_permutation_two_sided([0.0, 0.0, 0.0]) == 1.0


def test_block_permutation_guards_its_enumeration() -> None:
    with pytest.raises(ValueError, match="at least one block"):
        exact_block_permutation_two_sided([])
    with pytest.raises(ValueError, match="assignments"):
        exact_block_permutation_two_sided([1.0] * 8, max_permutations=10)


def test_exact_rank_sum_known_values_and_ties() -> None:
    assert exact_rank_sum_two_sided([1, 2], [3, 4]) == pytest.approx(2 / 6)
    assert exact_rank_sum_two_sided([1, 2, 3, 4], [5, 6, 7, 8]) == pytest.approx(2 / 70)
    assert exact_rank_sum_two_sided([5, 6, 7, 8], [1, 2, 3, 4]) == pytest.approx(2 / 70)
    assert exact_rank_sum_two_sided([1, 1], [1, 1]) == 1.0
    with pytest.raises(ValueError, match="permutations"):
        exact_rank_sum_two_sided([1] * 12, [2] * 12, max_permutations=10)
    with pytest.raises(ValueError, match="non-empty"):
        exact_rank_sum_two_sided([], [1, 2])


# ---------------------------------------------------------------------- analysis


def test_analysis_reports_no_measurable_effect_when_arms_match() -> None:
    boots = _blocks([8, 10, 12, 9, 11, 13], [8, 10, 12, 9, 11, 13])
    result = analyze(boots)
    assert result["schema"] == ANALYSIS_SCHEMA
    assert result["usable_blocks"] == 6
    assert result["randomization_reference_set"] == 64
    assert result["onset_block_permutation_two_sided_p"] == pytest.approx(1.0)
    assert result["median_onset_difference_off_minus_on"] == 0
    assert result["conclusion"] == "no_measurable_effect"
    assert "PRIMARY" in render_markdown(result)


def test_analysis_detects_overlays_off_delaying_onset() -> None:
    boots = _blocks([6, 7, 8, 6, 7, 8], [15, 16, 17, 15, 16, 17])
    result = analyze(boots)
    assert result["onset_block_permutation_two_sided_p"] == pytest.approx(2 / 64)
    assert result["median_onset_difference_off_minus_on"] == pytest.approx(9.0)
    assert result["conclusion"] == "overlays_off_delays_onset"
    assert result["sensitivity"]["sign_test"]["overlays_off_later_onset_blocks"] == 6
    assert result["sensitivity"]["onset_rank_sum_two_sided_p"] is not None
    assert result["onset_p_is_bound"] is False


def test_analysis_detects_overlays_off_accelerating_onset() -> None:
    boots = _blocks([15, 16, 17, 15, 16, 17], [6, 7, 8, 6, 7, 8])
    result = analyze(boots)
    assert result["conclusion"] == "overlays_off_accelerates_onset"
    assert result["sensitivity"]["sign_test"]["overlays_off_earlier_onset_blocks"] == 6


def test_censoring_marks_the_p_value_as_a_bound() -> None:
    boots: list[BootObservation] = []
    for on_onset in (6, 7, 8, 6, 7, 8):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    result = analyze(boots)
    assert result["censored_boots"] == 6
    assert result["onset_p_is_bound"] is True
    assert result["arms"]["overlays_off"]["observed_onsets"] == ()
    assert result["arms"]["overlays_off"]["median_burst_rate"] is None
    assert result["conclusion"] == "overlays_off_delays_onset"


def test_doubly_censored_blocks_with_unequal_delivery_are_not_informative() -> None:
    """#710 Codex P1 — delivered-cycle surrogates differ per boot, so subtracting two unrelated
    lower bounds would fabricate a signed difference.

    Before #710 every boot shared the same ``launches + 1`` surrogate and this cancelled to zero
    by construction. Without saying it explicitly, six doubly-censored blocks split +1/-1 would
    clear the informative-block floor and report ``no_measurable_effect`` with p=1 — having
    observed no onset at all.
    """
    boots: list[BootObservation] = []
    for index in range(6):
        # Both arms censored, but with different numbers of undelivered attempts, so their
        # delivered-cycle surrogates differ — and the sign alternates between blocks.
        on_undelivered, off_undelivered = (1, 0) if index % 2 else (0, 1)
        for condition, undelivered in (
            ("overlays_on", on_undelivered),
            ("overlays_off", off_undelivered),
        ):
            verdicts = ["never_live"] * undelivered + ["stable"] * (_LAUNCHES - undelivered)
            boots.append(_boot(len(boots) + 1, condition, verdicts))
    result = analyze(boots)
    assert result["informative_blocks"] == 0
    assert result["conclusion"] == "insufficient_sample"


def test_one_uninformative_block_does_not_veto_observed_ties() -> None:
    """#710 Qodo round 3 — censoring must not downgrade a result the observations support.

    Six fully observed equal onsets ARE evidence of no effect. Appending one sign-ambiguous
    censored block used to flip the conclusion to `insufficient_sample`, which is backwards: the
    veto exists for a run that learned nothing, not for one that learned something and then saw
    an extra uninformative block.
    """
    boots: list[BootObservation] = []
    for _ in range(6):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(8)))
        boots.append(_boot(len(boots) + 1, "overlays_off", _stable_then_freeze(8)))
    # ...plus one block whose censoring leaves the sign open.
    boots.append(_boot(len(boots) + 1, "overlays_on", ["stable"] * 23 + ["froze"]))
    boots.append(_boot(len(boots) + 1, "overlays_off", ["never_live"] * 4 + ["stable"] * 20))
    result = analyze(boots)
    assert result["informative_blocks"] == 0
    assert result["censoring_uninformative_blocks"] == 1
    assert result["observing_blocks"] == 6  # the six observed ties still count
    assert result["conclusion"] == "no_measurable_effect"


def test_uninformative_blocks_cannot_fill_the_endpoint_floor() -> None:
    """The other half: 2 observed ties + 5 uninformative blocks is not 7 blocks of evidence."""
    boots: list[BootObservation] = []
    for _ in range(2):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(8)))
        boots.append(_boot(len(boots) + 1, "overlays_off", _stable_then_freeze(8)))
    for _ in range(5):
        boots.append(_boot(len(boots) + 1, "overlays_on", ["stable"] * 23 + ["froze"]))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["never_live"] * 4 + ["stable"] * 20))
    result = analyze(boots)
    assert result["usable_blocks"] == 7  # enough blocks by the old count...
    assert result["observing_blocks"] == 2  # ...but only two learned anything
    assert result["conclusion"] == "insufficient_sample"


def test_singly_censored_pair_without_a_known_ordering_is_not_informative() -> None:
    """#710 Codex P1 round 2 — a one-sided bound that fails to exclude zero fixes no sign.

    Pre-#710 every boot shared the ``launches + 1`` surrogate, so a censored boot's surrogate
    strictly exceeded any onset observable in the same plan and a singly-censored block's sign
    was guaranteed. With per-boot delivered-cycle budgets, `on` observed LATE against an `off`
    censored after fewer delivered cycles yields a negative surrogate while the true difference
    may be zero or positive — so it must not enter the permutation statistic as an observation.
    """
    launches = 24
    # off: 4 undelivered, never freezes -> 20 delivered cycles -> surrogate 21.
    off_verdicts = ["never_live"] * 4 + ["stable"] * (launches - 4)
    # on: freezes at cycle 24, all delivered -> observed onset 24.
    on_verdicts = ["stable"] * 23 + ["froze"]
    on_boot = _boot(1, "overlays_on", on_verdicts)
    off_boot = _boot(2, "overlays_off", off_verdicts)
    on_summary = summarize_boot(on_boot)
    off_summary = summarize_boot(off_boot)
    assert on_summary.onset_cycle == 24
    assert off_summary.onset_censored is True and off_summary.onset_value == 21
    block = ab_mod._summarize_blocks([on_summary, off_summary])[0]
    # The raw surrogate would be 21 - 24 = -3, but off's true onset may be 24 or later.
    assert block.onset_sign_established is False
    assert block.onset_difference == 0.0
    assert block.onset_difference_lower == -3.0  # the bound itself is still reported


def test_a_run_of_sign_ambiguous_pairs_is_not_a_null_result() -> None:
    """The aggregate consequence: six such blocks must not read as ``no_measurable_effect``."""
    launches = 24
    boots: list[BootObservation] = []
    for _ in range(6):
        boots.append(_boot(len(boots) + 1, "overlays_on", ["stable"] * 23 + ["froze"]))
        boots.append(
            _boot(
                len(boots) + 1,
                "overlays_off",
                ["never_live"] * 4 + ["stable"] * (launches - 4),
            )
        )
    result = analyze(boots)
    assert result["informative_blocks"] == 0
    assert result["censoring_uninformative_blocks"] == 6
    assert result["conclusion"] == "insufficient_sample"


def test_a_short_boot_in_an_excluded_block_does_not_gate_the_run() -> None:
    """#710 Qodo round 2 — block eligibility is paired, so an untested boot must not gate.

    A boot whose partner is ambiguous never contributes an onset difference; letting its
    delivered-cycle shortfall force ``insufficient_sample`` would override a correct result from
    the eligible population. Only reachable in practice once the floor counts delivered cycles.
    """
    boots = _blocks([6, 7, 8, 6, 7, 8, 6], [15, 16, 17, 15, 16, 17, 15])
    # Block 1: the on boot is short on delivered cycles, and its partner is ambiguous, so the
    # whole block is excluded from the primary test anyway.
    short = ["never_live"] * 4 + _stable_then_freeze(6)[: _LAUNCHES - 4]
    boots[0] = _boot(1, "overlays_on", short)
    boots[1] = _ambiguous_boot(2, "overlays_off")
    result = analyze(boots)
    assert summarize_boot(boots[0]).delivered_cycles == 16 < MIN_LAUNCHES_PER_BOOT
    assert result["short_boots_below_launch_floor"] == 0  # it never reached the test
    assert result["usable_blocks"] == 6
    assert result["conclusion"] == "post_treatment_exclusions_present"


def test_delivered_cycle_floor_rejects_a_boot_short_on_cycles() -> None:
    """#710 Codex P2 — enough report rows is not enough accumulator.

    A 20-attempt plan may carry undelivered attempts without tripping the 20% exclusion
    threshold, leaving too few cycles to cover the pre-registered onset plus follow-up window.
    """
    boots = _blocks([6, 7, 8, 6, 7, 8], [15, 16, 17, 15, 16, 17])
    short = ["never_live"] * 4 + _stable_then_freeze(6)[: _LAUNCHES - 4]
    boots[0] = _boot(1, "overlays_on", short)
    summary = summarize_boot(boots[0])
    assert summary.usable is True  # 4/20 undelivered does not exceed the 20% threshold...
    assert summary.delivered_cycles == 16 < MIN_LAUNCHES_PER_BOOT  # ...but 16 cycles is short
    result = analyze(boots)
    assert result["short_boots_below_launch_floor"] == 1
    assert result["conclusion"] == "insufficient_sample"


def test_doubly_censored_blocks_refuse_a_directional_conclusion() -> None:
    """Codex #708: substituting N+1 is a BOUND, not an observation.

    With exactly one censored boot per block the substitution still gets the sign right, so a
    direction is claimable. With BOTH boots censored the true difference is unconstrained in
    either direction, so the summed statistic cannot support a direction — the p-value stays
    valid, but the conclusion must say so rather than pick a side.
    """
    boots: list[BootObservation] = []
    # Six singly-censored blocks (off never freezes) carry a clear positive effect...
    for on_onset in (6, 7, 8, 6, 7, 8):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    # ...and a seventh block with BOTH arms censored, whose true difference is unconstrained.
    # Seven blocks keep p (4/128 = 0.03125) under alpha so the direction check is what fires.
    boots.append(_boot(len(boots) + 1, "overlays_on", ["stable"] * _LAUNCHES))
    boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    result = analyze(boots)
    assert result["usable_blocks"] == 7
    assert result["onset_block_permutation_two_sided_p"] < 0.05
    assert result["onset_block_permutation_two_sided_p"] is not None
    assert result["effect_direction_determined"] is False
    assert result["blocked_onset_effect_lower_bound"] is None
    assert result["conclusion"] == "effect_direction_indeterminate_under_censoring"
    assert "DIRECTION INDETERMINATE" in render_markdown(result)


def test_conclusion_direction_comes_from_the_blocked_statistic() -> None:
    """Codex #708: the marginal arm medians can disagree in sign with the tested statistic."""
    boots = _blocks([6, 7, 8, 6, 7, 8], [15, 16, 17, 15, 16, 17])
    result = analyze(boots)
    # The tested statistic is the SUM of within-block differences, and it drives the direction.
    assert result["blocked_onset_effect_off_minus_on"] == pytest.approx(
        sum(b["onset_difference"] for b in result["blocks"])
    )
    assert result["blocked_onset_effect_off_minus_on"] > 0
    assert result["conclusion"] == "overlays_off_delays_onset"
    # The marginal median difference is still reported, but only as a descriptive figure.
    assert result["median_onset_difference_off_minus_on"] is not None
    assert "not the direction source" in render_markdown(result)


def test_short_boots_cannot_claim_the_endpoint_even_with_enough_blocks() -> None:
    """Codex #708: a block floor alone is not eligibility — each boot must be long enough."""
    short = MIN_LAUNCHES_PER_BOOT - 4
    boots: list[BootObservation] = []
    for on_onset, off_onset in zip((3, 4, 5, 3, 4, 5), (9, 10, 11, 9, 10, 11), strict=True):
        boots.append(
            _boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset, total=short))
        )
        boots.append(
            _boot(len(boots) + 1, "overlays_off", _stable_then_freeze(off_onset, total=short))
        )
    result = analyze(boots)
    assert result["usable_blocks"] == 6  # enough blocks...
    assert result["short_boots_below_launch_floor"] == 12  # ...but every boot is too short
    assert result["conclusion"] == "insufficient_sample"


def test_differential_exclusion_refuses_to_carry_a_treatment_claim() -> None:
    """Codex #708: if the treatment changes who gets excluded, the test is no longer exact.

    The permutation test is exact for the SHARP null — under it each boot's outcome, and so
    whether it is excluded, is fixed regardless of labels. But an arm imbalance in exclusions is
    the signature of treatment-dependent exclusion, and the test holds the survivor set fixed
    while enumerating assignments under which a different set would have survived.
    """
    boots = _blocks([6, 7, 8, 6, 7, 8, 6], [15, 16, 17, 15, 16, 17, 15])
    # Knock out ONE overlays_on boot only -> exclusions are 1 vs 0 across the arms.
    boots[0] = _ambiguous_boot(1, "overlays_on")
    result = analyze(boots)
    assert result["excluded_boots_by_arm"] == {"overlays_on": 1, "overlays_off": 0}
    assert result["exclusions_present"] is True
    assert result["usable_blocks"] == 6  # still enough blocks...
    assert result["onset_block_permutation_two_sided_p"] is not None  # ...and still significant
    assert result["conclusion"] == "post_treatment_exclusions_present"


def test_balanced_exclusions_are_still_withheld() -> None:
    """Codex + Qodo #708: EQUAL exclusion counts do not prove treatment-independence.

    Equal marginals are consistent with treatment-dependent missingness landing in different
    blocks, and every exclusion here is decided from a post-treatment outcome. The mechanism
    cannot be modelled from the reports, so any exclusion withholds the causal conclusion.
    """
    # 8 blocks so that knocking out one from each arm still leaves 6 usable — at 7 blocks the
    # run would (correctly) fall under the floor and report insufficient_sample instead.
    boots = _blocks([6, 7, 8, 6, 7, 8, 6, 7], [15, 16, 17, 15, 16, 17, 15, 16])
    boots[0] = _ambiguous_boot(1, "overlays_on")  # block 1 loses its on boot...
    boots[3] = _ambiguous_boot(4, "overlays_off")  # ...block 2 loses its off boot
    result = analyze(boots)
    assert result["excluded_boots_by_arm"] == {"overlays_on": 1, "overlays_off": 1}
    assert result["exclusions_present"] is True
    assert result["conclusion"] == "post_treatment_exclusions_present"


def test_blocks_are_paired_by_planned_number_not_adjacency() -> None:
    """Codex #708: a partial load must not fabricate cross-block pairs.

    Dropping one boot from each of two different blocks leaves an even count, and adjacency
    pairing would then pair boots from different randomized blocks — passing the condition
    check and feeding fabricated pairs to the exact test.
    """
    boots = _blocks([6, 7, 8, 6, 7, 8], [15, 16, 17, 15, 16, 17])
    # Drop overlays_on of block 1 (boot 1) and overlays_off of block 2 (boot 4). 10 boots left.
    partial = [boot for boot in boots if boot.boot not in {1, 4}]
    assert len(partial) % 2 == 0
    result = analyze(partial)
    reasons = {block["block"]: block["unusable_reason"] for block in result["blocks"]}
    assert reasons[1] == "missing_overlays_on_boot"
    assert reasons[2] == "missing_overlays_off_boot"
    # Only the four intact blocks score — not five fabricated ones.
    assert result["usable_blocks"] == 4
    assert result["conclusion"] == "insufficient_sample"


def test_missing_reports_count_as_post_treatment_exclusions() -> None:
    """Codex + Qodo #708: a missing report is an exclusion whose reason is unobservable.

    `analyze` only sees loaded boots, so a partially-loaded block would slip past the exclusion
    gate, and a block with BOTH reports absent would not appear at all. An overscheduled run
    could then keep enough intact blocks and emit a directional causal conclusion despite
    outcome- or treatment-dependent missingness.
    """
    boots = _blocks([6, 7, 8, 6, 7, 8, 6, 7], [15, 16, 17, 15, 16, 17, 15, 16])
    # Block 1 loses one boot; block 2 loses BOTH (so it vanishes from the observations entirely).
    partial = [boot for boot in boots if boot.boot not in {1, 3, 4}]
    result = analyze(partial, expected_blocks=8)
    assert result["incomplete_blocks"] == 1  # block 1, seen but half-loaded
    assert result["missing_blocks"] == 1  # block 2, invisible without the plan's block count
    assert result["exclusions_present"] is True
    assert result["usable_blocks"] == 6  # enough intact blocks to have concluded...
    assert result["conclusion"] == "post_treatment_exclusions_present"  # ...but it must not


def test_censoring_outside_the_test_does_not_mark_the_p_value_bound() -> None:
    """Codex #708: a censored boot whose partner was excluded never reached the test."""
    boots = _blocks([6, 7, 8, 6, 7, 8], [15, 16, 17, 15, 16, 17])
    boots[0] = _ambiguous_boot(1, "overlays_on")  # drops block 1 from the test...
    boots[1] = _boot(2, "overlays_off", ["stable"] * _LAUNCHES)  # ...and its censored partner
    result = analyze(boots)
    assert result["censored_boots"] == 1  # the arm-level count still sees it
    assert result["censored_boots_in_test"] == 0  # but it never entered the primary test
    assert result["onset_p_is_bound"] is False
    assert "BOUND" not in render_markdown(result)


def test_zero_difference_blocks_do_not_inflate_the_power_floor() -> None:
    """Self-hosted reviewer #708 HIGH: tied blocks carry no information.

    Flipping a zero-difference block's sign leaves the permutation sum unchanged, so it doubles
    the extreme count and the reference set alike and cancels. Counting it toward the floor let
    an underpowered run pass the eligibility check and then report `no_measurable_effect` for a
    p it could never have driven under alpha — the exact false-negative path this redesign
    exists to prevent.
    """
    # 5 same-sign informative blocks + 1 block whose arms tie -> 6 usable, 5 informative.
    boots = _blocks([6, 7, 8, 6, 7, 9], [15, 16, 17, 15, 16, 9])
    result = analyze(boots)
    assert result["usable_blocks"] == 6  # the naive floor check would have passed here
    assert result["informative_blocks"] == 5
    # Best attainable is 2/2**5 = 0.0625, NOT 2/2**6 = 0.03125 ...
    assert result["smallest_attainable_two_sided_p"] == pytest.approx(2 / 32)
    # ... and the observed p indeed cannot clear alpha, so this must not read as "no effect".
    assert result["onset_block_permutation_two_sided_p"] == pytest.approx(4 / 64)
    assert result["conclusion"] == "insufficient_sample"
    # A refusal must say what it would take, not just refuse: 2/2**k <= 0.05 needs k >= 6.
    assert result["informative_blocks_required"] == 6
    assert "NEEDS 6 informative blocks" in render_markdown(result)


def test_all_tied_blocks_still_read_as_no_measurable_effect() -> None:
    """The carve-out: genuinely identical arms are a null result, not an underpowered one."""
    boots = _blocks([8, 10, 12, 9, 11, 13], [8, 10, 12, 9, 11, 13])
    result = analyze(boots)
    assert result["informative_blocks"] == 0
    assert result["censoring_uninformative_blocks"] == 0  # every tie was OBSERVED
    assert result["smallest_attainable_two_sided_p"] is None
    assert result["conclusion"] == "no_measurable_effect"


def test_all_doubly_censored_blocks_are_not_a_null_result() -> None:
    """Qodo #708: equal N+1 surrogates are not equal onsets.

    Two censored boots tie by construction, so an all-doubly-censored run has
    `informative_blocks == 0` and would have slipped through the carve-out to report
    `no_measurable_effect` with p=1 — while every true onset difference is unconstrained and
    nothing whatsoever was learned.
    """
    boots: list[BootObservation] = []
    for _ in range(6):
        boots.append(_boot(len(boots) + 1, "overlays_on", ["stable"] * _LAUNCHES))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    result = analyze(boots)
    assert result["informative_blocks"] == 0
    assert (
        result["censoring_uninformative_blocks"] == 6
    )  # every "tie" came from censoring surrogates
    assert result["onset_block_permutation_two_sided_p"] == pytest.approx(1.0)
    assert result["conclusion"] == "insufficient_sample"


def test_undersized_run_cannot_claim_the_endpoint() -> None:
    """5 blocks under perfect separation still cannot reach alpha, so it must not conclude."""
    boots = _blocks([6, 7, 8, 6, 7], [16, 17, 18, 16, 17])
    result = analyze(boots, minimum_boots_per_arm=5)
    assert result["minimum_boots_per_arm"] == MIN_BOOTS_PER_ARM
    assert result["usable_blocks"] == 5
    assert result["smallest_attainable_two_sided_p"] == pytest.approx(2 / 32)
    assert result["onset_block_permutation_two_sided_p"] == pytest.approx(2 / 32)
    assert result["conclusion"] == "insufficient_sample"


def test_ambiguous_and_unusable_boots_drop_their_whole_block() -> None:
    never_live = int(MAX_UNDELIVERED_FRACTION * _LAUNCHES) + 1
    broken = ["never_live"] * never_live + ["stable"] * (_LAUNCHES - never_live)
    boots = _blocks([6, 7, 8, 6, 7, 8], [16, 17, 18, 16, 17, 18])
    boots[0] = _boot(1, "overlays_on", broken)
    boots[2] = _ambiguous_boot(3, "overlays_on")
    result = analyze(boots)
    assert result["usable_blocks"] == 4
    assert result["ambiguous_onset_boots"] == 1
    assert [b["unusable_reason"] for b in result["blocks"][:2]] == [
        "unusable_boot",
        "ambiguous_onset",
    ]
    assert result["conclusion"] == "insufficient_sample"


def test_burst_endpoint_is_block_paired_not_pooled_launches() -> None:
    """Codex #708: within-boot launches are correlated, so the burst test uses boot summaries."""
    boots = _blocks([8, 8, 8, 8, 8, 8], [8, 8, 8, 8, 8, 8])
    result = analyze(boots)
    on = result["arms"]["overlays_on"]
    assert len(on["boot_burst_rates"]) == 6
    assert on["median_burst_rate"] == pytest.approx(on["boot_burst_rates"][0])
    # Identical arms -> every block difference is 0 -> the permutation test returns 1.0.
    assert result["burst_block_permutation_two_sided_p"] == pytest.approx(1.0)
    assert all(block["burst_difference"] == 0 for block in result["blocks"])
    # Codex #708: the secondary p can rest on fewer blocks than the primary, so it names its own.
    assert result["burst_blocks"] == 6
    assert "from 6 block(s))" in render_markdown(result)


def test_secondary_endpoint_flags_when_it_rests_on_fewer_blocks() -> None:
    """A late onset leaves no room for the burst window, so that block has no rate at all."""
    late = _stable_then_freeze(_LAUNCHES - 1)  # window would run past the end of the boot
    boots = _blocks([8, 8, 8, 8, 8, 8], [8, 8, 8, 8, 8, 8])
    boots[1] = _boot(2, "overlays_off", late)
    result = analyze(boots)
    assert result["burst_blocks"] == 5
    assert result["usable_blocks"] == 6
    assert "FEWER than the 6 the primary used" in render_markdown(result)


def test_render_markdown_flags_a_bounded_p_value() -> None:
    boots: list[BootObservation] = []
    for on_onset in (6, 7, 8, 6, 7, 8):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    rendered = render_markdown(analyze(boots))
    assert "BOUND" in rendered
    assert "n/a" in rendered  # the fully-censored arm has no burst rate
    assert "Pre-registered baseline onset (graceful): 14" in rendered
    assert "non-gating" in rendered


# --------------------------------------------------------------------------- IO


def test_write_new_json_maps_oserror_to_valueerror(tmp_path, monkeypatch) -> None:
    """#657 Qodo — filesystem failures become clean CLI errors, not tracebacks."""
    from tools.ac_harness.init_perturber_ab import _write_new_json

    target = tmp_path / "blocked" / "out.json"

    def boom_mkdir(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", boom_mkdir)
    with pytest.raises(ValueError, match="could not write artifact"):
        _write_new_json(target, {"ok": True})


def test_write_new_json_is_exclusive_and_atomic(tmp_path) -> None:
    """#657 Qodo — no destination tombstone; refuse overwrite of a complete artifact."""
    from tools.ac_harness.init_perturber_ab import _write_new_json

    path = tmp_path / "plan.json"
    _write_new_json(path, {"schema": "test", "n": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema": "test", "n": 1}
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []
    with pytest.raises(ValueError, match="refusing to overwrite"):
        _write_new_json(path, {"schema": "test", "n": 2})
    assert json.loads(path.read_text(encoding="utf-8"))["n"] == 1


def test_plan_cli_prints_boot_scoped_protocol_and_windows_quoting(
    capsys, tmp_path, monkeypatch
) -> None:
    """#657 — paste target is the Windows rig; #625 redesign — one command per boot."""
    from tools.ac_harness.init_perturber_ab import main

    monkeypatch.setattr(ab_mod, "repo_checkout_root", lambda: tmp_path)
    out = tmp_path / ".scratch" / "plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    assert (
        main(
            [
                "plan",
                "--out",
                str(out),
                "--boots-per-arm",
                "6",
                "--launches-per-boot",
                "20",
                "--seed",
                "1",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "Windows rig" in printed
    assert "BOOT-SCOPED" in printed
    assert "REBOOT AGAIN before re-running that boot" in printed  # abort/retry guidance
    assert "REBOOT, then:" in printed
    assert "--trials 20" in printed
    assert "1 of 64 arm orders" in printed
    assert printed.count("resilient_launch") == 12  # one invocation per boot, not per launch
    assert f"cd {tmp_path}" not in printed
    assert "planner host's absolute path" in printed
    # Spaces in tokens must use list2cmdline quoting, not shlex.
    sample = ab_mod._shell_quote("path with spaces")
    assert sample == subprocess.list2cmdline(["path with spaces"])
    assert "'" not in sample  # shlex.quote would wrap with single quotes on POSIX


@pytest.mark.parametrize("hostile", ["x&whoami", "%USERPROFILE%", "a|b", "a^b", "a>b", 'a"b'])
def test_pasted_commands_reject_cmd_metacharacters(hostile: str) -> None:
    """Codex #708: list2cmdline is CRT-argv quoting, NOT cmd.exe escaping.

    `&`, `|`, `^`, `<`, `>` pass through untouched and `%VAR%` expands even inside double
    quotes, so a hostile car/track/layout or checkout path could split the pasted command.
    Reuses the transport's existing allowlist rather than inventing a second escaping scheme.
    """
    assert subprocess.list2cmdline([hostile]) != ""  # sanity: it really does not escape these
    with pytest.raises(ValueError, match="refusing to print"):
        ab_mod._shell_quote(hostile)


def test_build_plan_rejects_cmd_metacharacters_before_writing_anything() -> None:
    """The failure must land before the plan artifact exists, not at print time."""
    with pytest.raises(ValueError, match="unsafe car"):
        build_plan(MIN_BOOTS_PER_ARM, car="ks_car&whoami")
    with pytest.raises(ValueError, match="unsafe track"):
        build_plan(MIN_BOOTS_PER_ARM, track="spa|calc")
    with pytest.raises(ValueError, match="unsafe layout"):
        build_plan(MIN_BOOTS_PER_ARM, layout="%USERPROFILE%")
    # The real defaults must still pass.
    assert build_plan(MIN_BOOTS_PER_ARM)["launch"]["car"]


def test_analyze_cli_round_trip(capsys, tmp_path, monkeypatch) -> None:
    """The consumer path: plan -> per-boot reports -> analysis, through main()."""
    from tools.ac_harness.init_perturber_ab import main

    monkeypatch.setattr(ab_mod, "repo_checkout_root", lambda: tmp_path)
    scratch = tmp_path / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    plan_path = scratch / "plan.json"
    assert (
        main(
            [
                "plan",
                "--out",
                str(plan_path),
                "--boots-per-arm",
                "6",
                "--launches-per-boot",
                "20",
            ]
        )
        == 0
    )
    capsys.readouterr()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    onsets = {
        "overlays_on": iter([6, 7, 8, 6, 7, 8]),
        "overlays_off": iter([15, 16, 17, 15, 16, 17]),
    }
    for index, boot in enumerate(plan["boots"]):
        _write_boot_report(
            scratch / boot["report"],
            verdicts=_stable_then_freeze(next(onsets[boot["condition"]])),
            start_minute=index * 100,
            uptime_start=0.1,
            condition=boot["condition"],
        )
    assert main(["analyze", "--plan", str(plan_path), "--reports-dir", str(scratch)]) == 0
    printed = capsys.readouterr().out
    assert "overlays_off_delays_onset" in printed


def test_plan_is_not_published_when_a_command_cannot_be_rendered(tmp_path, monkeypatch) -> None:
    """Codex #708: an exclusive-write plan must not survive a later rendering failure.

    `_output_path` accepts a `.scratch` directory containing a cmd.exe metacharacter that
    `_shell_quote` then rejects. If the plan were written first, the retry would hit
    "refusing to overwrite" and the operator would be stuck with an unusable artifact.
    """
    from tools.ac_harness.init_perturber_ab import main

    monkeypatch.setattr(ab_mod, "repo_checkout_root", lambda: tmp_path)
    hostile_dir = tmp_path / ".scratch" / "run&backup"
    hostile_dir.mkdir(parents=True, exist_ok=True)
    out = hostile_dir / "plan.json"
    assert main(["plan", "--out", str(out), "--boots-per-arm", "6"]) == 2
    assert not out.exists(), "a rejected render must leave no plan artifact behind"


def test_analyze_cli_reports_a_clean_error_for_a_withdrawn_plan(capsys, tmp_path) -> None:
    from tools.ac_harness.init_perturber_ab import main

    stale = tmp_path / "plan.json"
    stale.write_text(json.dumps({"schema": WITHDRAWN_PLAN_SCHEMA}), encoding="utf-8")
    assert main(["analyze", "--plan", str(stale), "--reports-dir", str(tmp_path)]) == 2
    assert "withdrawn" in capsys.readouterr().err


class TestTreatmentReceipt:
    """#719 — a boot that did not RECEIVE its assigned condition cannot inform the contrast."""

    def test_off_arm_with_an_injected_perturber_is_contradicted_and_excluded(self):
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_CONTRADICTED,
            summarize_boot,
        )

        boot = _boot(1, "overlays_off", _stable_then_freeze(8), perturbers=_INJECTED_PERTURBERS)
        summary = summarize_boot(boot)
        assert summary.treatment == TREATMENT_CONTRADICTED
        assert summary.usable is False
        assert summary.unusable_reason == "treatment_contradicted"
        assert "overlays_off" in (summary.treatment_detail or "")

    def test_on_arm_never_observing_the_perturber_is_contradicted(self):
        """Symmetric at BOOT level even though one attempt cannot refute the `on` arm."""
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_CONTRADICTED,
            summarize_boot,
        )

        boot = _boot(2, "overlays_on", _stable_then_freeze(8), perturbers=_ABSENT_PERTURBERS)
        summary = summarize_boot(boot)
        assert summary.treatment == TREATMENT_CONTRADICTED
        assert summary.usable is False

    def test_matching_arms_are_confirmed_and_stay_usable(self):
        from tools.ac_harness.init_perturber_ab import TREATMENT_CONFIRMED, summarize_boot

        on = summarize_boot(
            _boot(1, "overlays_on", _stable_then_freeze(8), perturbers=_INJECTED_PERTURBERS)
        )
        off = summarize_boot(
            _boot(2, "overlays_off", _stable_then_freeze(14), perturbers=_ABSENT_PERTURBERS)
        )
        assert on.treatment == TREATMENT_CONFIRMED
        assert off.treatment == TREATMENT_CONFIRMED
        assert on.usable and off.usable

    def test_partial_on_arm_injection_is_not_confirmation(self):
        """Codex P1 on #721: both planned overlays must match; one of two is not enough."""
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_CONTRADICTED,
            TREATMENT_UNVERIFIED,
            treatment_receipt,
        )

        half_injected = {"steam_overlay": "injected", "nvidia_capture": "not_observed"}
        mixed_unknown = {"steam_overlay": "injected", "nvidia_capture": "unavailable"}
        off_mixed = {"steam_overlay": "not_observed", "nvidia_capture": "unavailable"}
        # On-arm confirmation is per live-session launch (not a boot-wide union).
        live_half = _boot(1, "overlays_on", _stable_then_freeze(8), perturbers=half_injected)
        live_mixed = _boot(1, "overlays_on", _stable_then_freeze(8), perturbers=mixed_unknown)

        verdict, _detail = treatment_receipt(
            "overlays_on", half_injected, launches=live_half.launches
        )
        assert verdict == TREATMENT_CONTRADICTED
        verdict, _detail = treatment_receipt(
            "overlays_on", mixed_unknown, launches=live_mixed.launches
        )
        assert verdict == TREATMENT_UNVERIFIED
        # Off arm: partial unknown is unverified, not a free confirmation.
        verdict, _detail = treatment_receipt("overlays_off", off_mixed)
        assert verdict == TREATMENT_UNVERIFIED

    def test_on_arm_requires_per_live_launch_full_injection(self):
        """Boot-wide union must not confirm when no single live acs.exe had both overlays."""
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_CONTRADICTED,
            TREATMENT_UNVERIFIED,
            BootObservation,
            LaunchObservation,
            summarize_boot,
            treatment_receipt,
        )

        launches = (
            LaunchObservation(
                launch=1,
                verdict="stable",
                started_at_utc="2026-07-28T10:01:00Z",
                elapsed_s=150.0,
                uptime_h=0.5,
                cycle_delivered=True,
                perturbers=tuple(
                    sorted({"steam_overlay": "injected", "nvidia_capture": "not_observed"}.items())
                ),
            ),
            LaunchObservation(
                launch=2,
                verdict="stable",
                started_at_utc="2026-07-28T10:02:00Z",
                elapsed_s=150.0,
                uptime_h=0.55,
                cycle_delivered=True,
                perturbers=tuple(
                    sorted({"steam_overlay": "not_observed", "nvidia_capture": "injected"}.items())
                ),
            ),
        )  # both stable: only stable is post-race for absence (Codex P1 on #721)
        boot = BootObservation(boot=1, condition="overlays_on", launches=launches)
        # Union would be both injected; per-launch is incomplete → contradicted, not confirmed.
        state = {"steam_overlay": "injected", "nvidia_capture": "injected"}
        verdict, _detail = treatment_receipt("overlays_on", state, launches=launches)
        assert verdict == TREATMENT_CONTRADICTED
        summary = summarize_boot(boot)
        assert summary.usable is False
        assert summary.unusable_reason == "treatment_contradicted"

        # Undelivered never_live looks are non-dispositive for the on arm.
        early = _boot(
            1,
            "overlays_on",
            ["never_live"] * 5,
            delivered=[False] * 5,
            perturbers=_ABSENT_PERTURBERS,
        )
        summary = summarize_boot(early)
        assert summary.treatment == TREATMENT_UNVERIFIED

        # Delivered never_live is never dispositive for absence (elapsed includes pre-launch work).
        short_nl = _boot(
            1,
            "overlays_on",
            ["never_live"] * 5,
            delivered=[True] * 5,
            perturbers=_ABSENT_PERTURBERS,
        )
        summary = summarize_boot(short_nl)
        assert summary.treatment == TREATMENT_UNVERIFIED

        # A stable miss is not erased by a sibling unavailable live launch.
        mixed = (
            LaunchObservation(
                launch=1,
                verdict="stable",
                started_at_utc="2026-07-28T10:01:00Z",
                elapsed_s=150.0,
                uptime_h=0.5,
                cycle_delivered=True,
                perturbers=tuple(sorted(_ABSENT_PERTURBERS.items())),
            ),
            LaunchObservation(
                launch=2,
                verdict="stable",
                started_at_utc="2026-07-28T10:02:00Z",
                elapsed_s=150.0,
                uptime_h=0.55,
                cycle_delivered=True,
                perturbers=tuple(sorted(_UNAVAILABLE_PERTURBERS.items())),
            ),
        )
        verdict, _detail = treatment_receipt(
            "overlays_on",
            {"steam_overlay": "not_observed", "nvidia_capture": "unavailable"},
            launches=mixed,
        )
        assert verdict == TREATMENT_CONTRADICTED

    def test_incomplete_perturber_keys_are_rejected(self, tmp_path: Path) -> None:
        plan = _two_boot_plan()
        path = tmp_path / plan["boots"][0]["report"]
        _write_boot_report(
            path,
            condition=plan["boots"][0]["condition"],
            verdicts=["stable"] * _LAUNCHES,
            start_minute=0,
            uptime_start=0.5,
            launch=_launch_config(_LAUNCHES),
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["attempts_log"]:
            row["perturbers"] = {"steam_overlay": "injected"}  # missing nvidia_capture
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="perturbers keys must be exactly"):
            load_observations(plan, tmp_path, require_complete=False)

    def test_pre_treatment_v3_plans_are_rejected(self, tmp_path: Path) -> None:
        from tools.ac_harness.init_perturber_ab import PRE_TREATMENT_PLAN_SCHEMA, load_plan

        stale = tmp_path / "plan.json"
        stale.write_text(json.dumps({"schema": PRE_TREATMENT_PLAN_SCHEMA}), encoding="utf-8")
        with pytest.raises(ValueError, match="treatment-receipt"):
            load_plan(stale)

    def test_unavailable_evidence_is_unverified_not_contradicted(self):
        """No information must fall back to the plan, never manufacture an exclusion."""
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_UNVERIFIED,
            summarize_boot,
        )

        for condition in ("overlays_on", "overlays_off"):
            summary = summarize_boot(
                _boot(1, condition, _stable_then_freeze(8), perturbers=_UNAVAILABLE_PERTURBERS)
            )
            assert summary.treatment == TREATMENT_UNVERIFIED
            assert summary.usable is True

    def test_wedged_init_miss_is_contradicted_when_timeout_cleared_race(self):
        """With go_live_timeout floor ≥5s, wedged_init lived past the injection race."""
        from tools.ac_harness.init_perturber_ab import (
            TREATMENT_CONTRADICTED,
            BootObservation,
            LaunchObservation,
            treatment_receipt,
        )

        wedged = LaunchObservation(
            launch=1,
            verdict="wedged_init",
            started_at_utc="2026-07-28T10:01:00Z",
            elapsed_s=80.0,
            uptime_h=0.5,
            cycle_delivered=True,
            perturbers=tuple(sorted(_ABSENT_PERTURBERS.items())),
        )
        boot = BootObservation(boot=1, condition="overlays_on", launches=(wedged,))
        verdict, _detail = treatment_receipt(
            "overlays_on", dict(_ABSENT_PERTURBERS), launches=boot.launches
        )
        assert verdict == TREATMENT_CONTRADICTED

    def test_go_live_timeout_below_injection_floor_is_rejected(self) -> None:
        """Codex P2: plans must not allow WEDGED_INIT inside the measured race."""
        from tools.ac_harness.init_perturber_ab import MIN_GO_LIVE_TIMEOUT_S, build_plan

        with pytest.raises(ValueError, match="go_live_timeout"):
            build_plan(
                6,
                launches_per_boot=_LAUNCHES,
                go_live_timeout=MIN_GO_LIVE_TIMEOUT_S - 0.1,
            )

    def test_one_sighting_anywhere_in_the_boot_is_dispositive(self):
        """Union across launches: the injection races startup, so early misses prove nothing."""
        from tools.ac_harness.init_perturber_ab import (
            BootObservation,
            LaunchObservation,
            boot_perturber_state,
        )

        launches = tuple(
            LaunchObservation(
                launch=index,
                verdict="stable",
                started_at_utc=f"2026-07-28T10:{index:02d}:00Z",
                elapsed_s=12.5,
                uptime_h=0.5 + index * 0.05,
                cycle_delivered=True,
                perturbers=tuple(sorted(evidence.items())),
            )
            for index, evidence in enumerate(
                [
                    {"steam_overlay": "unavailable"},
                    {"steam_overlay": "not_observed"},
                    {"steam_overlay": "injected"},
                    {"steam_overlay": "not_observed"},
                ],
                start=1,
            )
        )
        state = boot_perturber_state(
            BootObservation(boot=1, condition="overlays_off", launches=launches)
        )
        assert state["steam_overlay"] == "injected"

    def test_a_contradicted_boot_drops_its_whole_block(self):
        """The block is the unit of inference — excluding one boot must remove the pair."""
        from tools.ac_harness.init_perturber_ab import _summarize_blocks, summarize_boot

        boots = [
            summarize_boot(
                _boot(1, "overlays_on", _stable_then_freeze(8), perturbers=_INJECTED_PERTURBERS)
            ),
            summarize_boot(
                # Planned OFF but the overlay was demonstrably injected: label is a lie.
                _boot(2, "overlays_off", _stable_then_freeze(14), perturbers=_INJECTED_PERTURBERS)
            ),
        ]
        blocks = _summarize_blocks(boots)
        assert len(blocks) == 1
        # The surviving block carries no usable difference, so it cannot enter the statistic.
        assert blocks[0].onset_difference is None


def test_early_arm_contradiction_report_is_loadable(tmp_path: Path) -> None:
    """Codex P1 on #721: fail-fast off-arm stop must parse as a contradicted boot, not corrupt."""
    from tools.ac_harness.init_perturber_ab import TREATMENT_CONTRADICTED, summarize_boot

    plan = _two_boot_plan()
    reports_dir = tmp_path
    first = plan["boots"][0]
    # Planned off arm, stopped after one injected sighting — shorter than launches_per_boot.
    path = reports_dir / first["report"]
    _write_boot_report(
        path,
        condition="overlays_off",
        verdicts=["froze"],
        start_minute=10,
        uptime_start=0.5,
        launch=_launch_config(plan["launches_per_boot"]),
        attempts=1,
        perturbers=_INJECTED_PERTURBERS,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["arm_contradicted"] = True
    payload["expect_perturbers"] = "off"
    # Force the planned condition to off for this case (helper may have drawn either arm).
    plan["boots"][0] = {**first, "condition": "overlays_off"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    observations = load_observations(plan, reports_dir, require_complete=False)
    assert len(observations) == 1
    assert len(observations[0].launches) == 1
    summary = summarize_boot(observations[0])
    assert summary.treatment == TREATMENT_CONTRADICTED
    assert summary.usable is False
    assert summary.unusable_reason == "treatment_contradicted"


def test_plan_commands_emit_expect_perturbers(tmp_path, monkeypatch, capsys) -> None:
    """Codex P2 on #721: generated plan lines must activate the fail-fast arm check."""
    from tools.ac_harness.init_perturber_ab import main

    monkeypatch.setattr(ab_mod, "repo_checkout_root", lambda: tmp_path)
    out = tmp_path / ".scratch" / "plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    assert main(["plan", "--out", str(out), "--boots-per-arm", "6", "--seed", "1"]) == 0
    printed = capsys.readouterr().out
    assert "--expect-perturbers on" in printed
    assert "--expect-perturbers off" in printed
    plan = json.loads(out.read_text(encoding="utf-8"))
    # Both arms appear in the printed schedule; counts match the planned boots.
    assert sum(boot["condition"] == "overlays_on" for boot in plan["boots"]) == 6
    assert sum(boot["condition"] == "overlays_off" for boot in plan["boots"]) == 6


def test_v2_reports_are_rejected_with_a_reason(tmp_path: Path) -> None:
    """#719 — a v2 report has no treatment evidence, so its arm label cannot be cross-checked."""
    plan = _two_boot_plan()

    def drop_perturbers(payload: dict) -> None:
        payload["schema"] = "resilient-launch-report/v2"
        payload.pop("perturbers", None)
        for row in payload["attempts_log"]:
            row.pop("perturbers")

    _mutate_first_report(tmp_path, plan, drop_perturbers)
    with pytest.raises(ValueError, match="resilient-launch-report/v2"):
        load_observations(plan, tmp_path, require_complete=False)


def test_missing_perturbers_key_is_rejected(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _mutate_first_report(tmp_path, plan, lambda p: p["attempts_log"][2].pop("perturbers"))
    with pytest.raises(ValueError, match="missing perturbers"):
        load_observations(plan, tmp_path, require_complete=False)


def test_unknown_perturber_evidence_value_is_rejected(tmp_path: Path) -> None:
    """A tri-state that silently accepts a fourth value is not a tri-state."""
    plan = _two_boot_plan()
    _mutate_first_report(
        tmp_path,
        plan,
        lambda p: p["attempts_log"][0]["perturbers"].__setitem__("steam_overlay", "probably"),
    )
    with pytest.raises(ValueError, match="invalid perturber evidence"):
        load_observations(plan, tmp_path, require_complete=False)
