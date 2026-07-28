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
    MAX_NEVER_LIVE_FRACTION,
    MIN_BOOTS_PER_ARM,
    MIN_LAUNCHES_PER_BOOT,
    WITHDRAWN_PLAN_SCHEMA,
    BootObservation,
    LaunchObservation,
    analyze,
    build_plan,
    counterbalanced_sequence,
    exact_rank_sum_two_sided,
    fisher_exact_two_sided,
    load_observations,
    load_plan,
    paired_exact_two_sided,
    render_markdown,
    summarize_boot,
    wilson_interval,
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


def _write_boot_report(
    path: Path,
    *,
    verdicts: list[str],
    start_minute: int,
    uptime_start: float,
    launch: dict[str, object] | None = None,
    attempts: int | None = None,
) -> None:
    """Emit one ``resilient_launch --trials N`` style report for a whole boot."""
    counts = {"stable": 0, "froze": 0, "wedged_init": 0, "never_live": 0}
    log = []
    for index, verdict in enumerate(verdicts, start=1):
        counts[verdict] += 1
        minute = start_minute + index
        log.append(
            {
                "attempt": index,
                "verdict": verdict,
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
        "launch": launch or _launch_config(len(verdicts)),
        "attempts_log": log,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stable_then_freeze(onset: int, total: int = _LAUNCHES) -> list[str]:
    """``onset``-1 clean launches, then a freeze, then alternating burst behaviour."""
    verdicts = ["stable"] * (onset - 1)
    for index in range(onset, total + 1):
        verdicts.append("froze" if (index - onset) % 2 == 0 else "stable")
    return verdicts[:total]


def _boot(
    number: int, condition: str, verdicts: list[str], *, uptime_start: float = 0.5
) -> BootObservation:
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
            )
            for index, verdict in enumerate(verdicts, start=1)
        ),
    )


def _arm_boots(onsets_on: list[int], onsets_off: list[int]) -> list[BootObservation]:
    """Build a counterbalanced-looking boot list: alternating on/off, one pair at a time."""
    boots: list[BootObservation] = []
    for on_onset, off_onset in zip(onsets_on, onsets_off, strict=True):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", _stable_then_freeze(off_onset)))
    return boots


# --------------------------------------------------------------------------- plan


def test_counterbalanced_sequence_pairs_boots_and_is_seeded() -> None:
    sequence = counterbalanced_sequence(4)
    assert len(sequence) == 8
    assert sequence.count("overlays_on") == sequence.count("overlays_off") == 4
    assert all(
        set(sequence[offset : offset + 2]) == {"overlays_on", "overlays_off"}
        for offset in range(0, len(sequence), 2)
    )
    ab_first = sum(1 for offset in range(0, len(sequence), 2) if sequence[offset] == "overlays_on")
    assert ab_first == 2
    assert sequence == counterbalanced_sequence(4)
    assert sequence != counterbalanced_sequence(4, randomization_seed=626)


def test_plan_is_boot_scoped_and_records_the_operator_gate() -> None:
    plan = build_plan(4, generated_at_utc="2026-07-28T12:00:00Z")
    assert plan["schema"] == "init-perturber-ab-plan/v2"
    assert plan["supersedes"] == WITHDRAWN_PLAN_SCHEMA
    assert plan["operator_owned_settings"] is True
    assert plan["protocol"]["reboot_before_every_boot"] is True
    assert plan["protocol"]["graceful_first_teardown_both_arms"] is True
    assert plan["protocol"]["one_invocation_per_boot"] is True
    assert plan["protocol"]["condition_definitions"]["overlays_off"] == {
        "steam_overlay_enabled": False,
        "nvidia_shadowplay_enabled": False,
    }
    assert "onset launch-index" in plan["endpoints"]["primary"]
    assert plan["prereg_baselines"]["onset_index_graceful"] == BASELINE_ONSET_INDEX_GRACEFUL
    assert "false negative" in plan["withdrawn_design_note"]
    assert plan["launch"]["trials_per_invocation"] == DEFAULT_LAUNCHES_PER_BOOT
    assert len(plan["boots"]) == 8
    assert plan["boots"][0]["report"] == f"boot-001-{plan['boots'][0]['condition']}.json"


def test_build_plan_rejects_undersized_boot_and_launch_counts() -> None:
    with pytest.raises(ValueError, match=str(MIN_BOOTS_PER_ARM)):
        build_plan(MIN_BOOTS_PER_ARM - 1)
    with pytest.raises(ValueError, match=str(MIN_LAUNCHES_PER_BOOT)):
        build_plan(MIN_BOOTS_PER_ARM, launches_per_boot=MIN_LAUNCHES_PER_BOOT - 1)


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


def test_load_plan_rejects_same_arm_pair(tmp_path: Path) -> None:
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
    _write_boot_report(path, verdicts=["stable"] * _LAUNCHES, start_minute=0, uptime_start=0.5)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["counts"]["stable"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="counts"):
        load_observations(plan, tmp_path, require_complete=False)


def test_incomplete_experiment_is_refused(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    with pytest.raises(ValueError, match="incomplete"):
        load_observations(plan, tmp_path)


def test_uptime_must_reset_between_boots(tmp_path: Path) -> None:
    """The sharpest boot-scoped guard: two arms on one boot pools the accumulator."""
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
    )
    _write_boot_report(
        tmp_path / plan["boots"][1]["report"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=60,
        # Uptime kept climbing — no reboot happened between the arms.
        uptime_start=2.0,
    )
    with pytest.raises(ValueError, match="did not reset"):
        load_observations(plan, tmp_path)


def test_boot_boundary_accepts_a_real_reboot(tmp_path: Path) -> None:
    plan = _two_boot_plan()
    _write_boot_report(
        tmp_path / plan["boots"][0]["report"],
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=2.0,
    )
    _write_boot_report(
        tmp_path / plan["boots"][1]["report"],
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
    _write_boot_report(path, verdicts=["stable"] * _LAUNCHES, start_minute=0, uptime_start=0.5)
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
        verdicts=["stable"] * _LAUNCHES,
        start_minute=0,
        uptime_start=0.5,
        launch=wrong,
    )
    with pytest.raises(ValueError, match="launch.car"):
        load_observations(plan, tmp_path, require_complete=False)


# ------------------------------------------------------------------ boot summary


def test_onset_index_and_post_onset_window_start_at_onset() -> None:
    # Reproduces the #668 graceful battery shape: 13 clean, then 14/15 froze, then stable.
    verdicts = ["stable"] * 13 + ["froze", "froze", "stable"] + ["stable"] * 4
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.onset_index == 14
    assert summary.onset_censored is False
    assert summary.onset_value == 14
    # Window is launches 14..20 inclusive -> 7 classified launches, 2 freezes.
    assert summary.post_onset_launches == 7
    assert summary.post_onset_freezes == 2
    assert summary.post_onset_burst_rate == pytest.approx(2 / 7)
    assert summary.usable is True


def test_censored_boot_gets_a_surrogate_beyond_every_observable_onset() -> None:
    summary = summarize_boot(_boot(1, "overlays_off", ["stable"] * _LAUNCHES))
    assert summary.onset_index is None
    assert summary.onset_censored is True
    assert summary.onset_value == _LAUNCHES + 1
    assert summary.post_onset_launches == 0
    assert summary.post_onset_burst_rate is None
    assert summary.usable is True


def test_never_live_keeps_its_cycle_but_leaves_the_denominator() -> None:
    verdicts = ["stable"] * 9 + ["never_live"] + ["froze"] + ["stable"] * 9
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    # The never_live launch still consumed an accumulator cycle, so onset stays at index 11.
    assert summary.onset_index == 11
    assert summary.never_live == 1
    assert summary.classified == _LAUNCHES - 1
    # Window 11..20 has no further never_live, so the denominator is the full 10.
    assert summary.post_onset_launches == 10
    assert summary.post_onset_freezes == 1
    assert summary.usable is True


def test_never_live_heavy_boot_is_unusable_not_scored() -> None:
    never_live = int(MAX_NEVER_LIVE_FRACTION * _LAUNCHES) + 1
    verdicts = ["never_live"] * never_live + ["stable"] * (_LAUNCHES - never_live)
    summary = summarize_boot(_boot(1, "overlays_on", verdicts))
    assert summary.usable is False
    assert summary.unusable_reason == "never_live_fraction_exceeded"


def test_wedged_init_counts_as_onset() -> None:
    verdicts = ["stable"] * 5 + ["wedged_init"] + ["stable"] * 14
    assert summarize_boot(_boot(1, "overlays_on", verdicts)).onset_index == 6


# -------------------------------------------------------------------- statistics


@pytest.mark.parametrize(
    ("successes", "total", "expected"),
    [(0, 20, (0.0, 0.161125)), (10, 20, (0.299298, 0.700702)), (20, 20, (0.838875, 1.0))],
)
def test_wilson_interval_known_values(
    successes: int, total: int, expected: tuple[float, float]
) -> None:
    actual = wilson_interval(successes, total)
    assert actual == pytest.approx(expected, abs=1e-6)


def test_fisher_exact_matches_known_tables_and_is_symmetric() -> None:
    # Canonical tea-tasting table: [[1, 9], [11, 3]].
    assert fisher_exact_two_sided(1, 10, 11, 14) == pytest.approx(0.002759456, abs=1e-9)
    assert fisher_exact_two_sided(11, 14, 1, 10) == pytest.approx(0.002759456, abs=1e-9)
    assert fisher_exact_two_sided(5, 10, 5, 10) == 1.0


def test_paired_exact_uses_only_discordant_pairs() -> None:
    assert paired_exact_two_sided(0, 0) == 1.0
    assert paired_exact_two_sided(10, 0) == pytest.approx(0.001953125)
    assert paired_exact_two_sided(5, 5) == 1.0


def test_exact_rank_sum_known_values_and_symmetry() -> None:
    # 2v2 perfect separation: only the two most extreme splits are as extreme -> 2/C(4,2).
    assert exact_rank_sum_two_sided([1, 2], [3, 4]) == pytest.approx(2 / 6)
    # 4v4 perfect separation is the smallest attainable p and justifies MIN_BOOTS_PER_ARM=4.
    assert exact_rank_sum_two_sided([1, 2, 3, 4], [5, 6, 7, 8]) == pytest.approx(2 / 70)
    assert exact_rank_sum_two_sided([5, 6, 7, 8], [1, 2, 3, 4]) == pytest.approx(2 / 70)
    assert 2 / 70 < 0.05
    # 3v3 perfect separation cannot reach alpha, which is exactly why the floor is 4.
    assert exact_rank_sum_two_sided([1, 2, 3], [4, 5, 6]) == pytest.approx(2 / 20)
    assert 2 / 20 > 0.05


def test_exact_rank_sum_handles_ties_and_refuses_to_blow_up() -> None:
    assert exact_rank_sum_two_sided([1, 1], [1, 1]) == 1.0
    with pytest.raises(ValueError, match="permutations"):
        exact_rank_sum_two_sided([1] * 12, [2] * 12, max_permutations=10)
    with pytest.raises(ValueError, match="non-empty"):
        exact_rank_sum_two_sided([], [1, 2])


# ---------------------------------------------------------------------- analysis


def test_analysis_reports_no_measurable_effect_when_arms_match() -> None:
    boots = _arm_boots([8, 10, 12, 14], [8, 10, 12, 14])
    result = analyze(boots)
    assert result["schema"] == ANALYSIS_SCHEMA
    assert result["arms"]["overlays_on"]["usable_boots"] == 4
    assert result["onset_exact_rank_sum_two_sided_p"] == pytest.approx(1.0)
    assert result["median_onset_difference_off_minus_on"] == 0
    assert result["conclusion"] == "no_measurable_effect"
    assert "Onset exact rank-sum" in render_markdown(result)


def test_analysis_detects_overlays_off_delaying_onset() -> None:
    boots = _arm_boots([6, 7, 8, 9], [15, 16, 17, 18])
    result = analyze(boots)
    assert result["onset_exact_rank_sum_two_sided_p"] == pytest.approx(2 / 70)
    assert result["median_onset_difference_off_minus_on"] == pytest.approx(9.0)
    assert result["conclusion"] == "overlays_off_delays_onset"
    assert result["paired_sensitivity"]["overlays_off_later_onset_pairs"] == 4
    assert result["onset_p_is_bound"] is False


def test_analysis_detects_overlays_off_accelerating_onset() -> None:
    boots = _arm_boots([15, 16, 17, 18], [6, 7, 8, 9])
    result = analyze(boots)
    assert result["conclusion"] == "overlays_off_accelerates_onset"
    assert result["paired_sensitivity"]["overlays_off_earlier_onset_pairs"] == 4


def test_censoring_marks_the_p_value_as_a_bound() -> None:
    boots: list[BootObservation] = []
    for on_onset in (6, 7, 8, 9):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    result = analyze(boots)
    assert result["censored_boots"] == 4
    assert result["onset_p_is_bound"] is True
    assert result["arms"]["overlays_off"]["observed_onsets"] == ()
    assert result["arms"]["overlays_off"]["post_onset_burst_rate"] is None
    assert result["conclusion"] == "overlays_off_delays_onset"


def test_undersized_run_cannot_claim_the_endpoint() -> None:
    """A 3-boot pilot must stay insufficient even under perfect separation."""
    boots = _arm_boots([6, 7, 8], [16, 17, 18])
    result = analyze(boots, minimum_boots_per_arm=3)
    assert result["minimum_boots_per_arm"] == MIN_BOOTS_PER_ARM
    assert result["conclusion"] == "insufficient_sample"


def test_unusable_boots_do_not_count_toward_the_floor() -> None:
    never_live = int(MAX_NEVER_LIVE_FRACTION * _LAUNCHES) + 1
    broken = ["never_live"] * never_live + ["stable"] * (_LAUNCHES - never_live)
    boots = _arm_boots([6, 7, 8, 9], [16, 17, 18, 19])
    boots[0] = _boot(1, "overlays_on", broken)
    result = analyze(boots)
    assert result["arms"]["overlays_on"]["usable_boots"] == 3
    assert result["conclusion"] == "insufficient_sample"
    assert result["paired_sensitivity"]["excluded_unusable_pairs"] == 1


def test_post_onset_burst_is_compared_with_fisher() -> None:
    boots = _arm_boots([8, 8, 8, 8], [8, 8, 8, 8])
    result = analyze(boots)
    on = result["arms"]["overlays_on"]
    assert on["post_onset_launches"] > 0
    assert result["post_onset_burst_fisher_two_sided_p"] == pytest.approx(1.0)
    assert on["post_onset_burst_rate"] == pytest.approx(
        on["post_onset_freezes"] / on["post_onset_launches"]
    )


def test_render_markdown_flags_a_bounded_p_value() -> None:
    boots: list[BootObservation] = []
    for on_onset in (6, 7, 8, 9):
        boots.append(_boot(len(boots) + 1, "overlays_on", _stable_then_freeze(on_onset)))
        boots.append(_boot(len(boots) + 1, "overlays_off", ["stable"] * _LAUNCHES))
    rendered = render_markdown(analyze(boots))
    assert "BOUND" in rendered
    assert "n/a" in rendered  # the fully-censored arm has no burst rate
    assert "Pre-registered baseline onset (graceful): 14" in rendered


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
                "4",
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
    assert "REBOOT, then:" in printed
    assert "--trials 20" in printed
    assert printed.count("resilient_launch") == 8  # one invocation per boot, not per launch
    assert f"cd {tmp_path}" not in printed
    assert "planner host's absolute path" in printed
    # Spaces in tokens must use list2cmdline quoting, not shlex.
    sample = ab_mod._shell_quote("path with spaces")
    assert sample == subprocess.list2cmdline(["path with spaces"])
    assert "'" not in sample  # shlex.quote would wrap with single quotes on POSIX


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
                "4",
                "--launches-per-boot",
                "20",
            ]
        )
        == 0
    )
    capsys.readouterr()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    onsets = {"overlays_on": iter([6, 7, 8, 9]), "overlays_off": iter([16, 17, 18, 19])}
    for index, boot in enumerate(plan["boots"]):
        _write_boot_report(
            scratch / boot["report"],
            verdicts=_stable_then_freeze(next(onsets[boot["condition"]])),
            start_minute=index * 100,
            uptime_start=0.1,
        )
    assert main(["analyze", "--plan", str(plan_path), "--reports-dir", str(scratch)]) == 0
    printed = capsys.readouterr().out
    assert "overlays_off_delays_onset" in printed


def test_analyze_cli_reports_a_clean_error_for_a_withdrawn_plan(capsys, tmp_path) -> None:
    from tools.ac_harness.init_perturber_ab import main

    stale = tmp_path / "plan.json"
    stale.write_text(json.dumps({"schema": WITHDRAWN_PLAN_SCHEMA}), encoding="utf-8")
    assert main(["analyze", "--plan", str(stale), "--reports-dir", str(tmp_path)]) == 2
    assert "withdrawn" in capsys.readouterr().err
