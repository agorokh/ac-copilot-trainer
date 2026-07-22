from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ac_harness.init_perturber_ab import (
    ANALYSIS_SCHEMA,
    MIN_TRIALS_PER_ARM,
    Observation,
    analyze,
    build_plan,
    counterbalanced_sequence,
    fisher_exact_two_sided,
    load_observations,
    load_plan,
    paired_exact_two_sided,
    render_markdown,
    wilson_interval,
)
from tools.ac_harness.resilient_launch import REPORT_SCHEMA


def _write_report(
    path: Path,
    *,
    verdict: str,
    started_at_utc: str,
    uptime_h: float | None,
    launch: dict[str, object] | None = None,
) -> None:
    counts = {"stable": 0, "froze": 0, "wedged_init": 0, "never_live": 0}
    counts[verdict] = 1
    payload = {
        "schema": REPORT_SCHEMA,
        "verdict": verdict,
        "attempts": 1,
        "counts": counts,
        "launch": launch
        or {
            "car": "ks_porsche_911_gt3_r_2016",
            "track": "spa",
            "stability_window": 140.0,
            "trials_per_invocation": 1,
        },
        "attempts_log": [
            {
                "attempt": 1,
                "verdict": verdict,
                "started_at_utc": started_at_utc,
                "elapsed_s": 12.5,
                "uptime_h": uptime_h,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_counterbalanced_sequence_interleaves_every_pair_and_is_seeded() -> None:
    sequence = counterbalanced_sequence(20)
    assert len(sequence) == 40
    assert sequence.count("overlays_on") == sequence.count("overlays_off") == 20
    assert all(
        set(sequence[offset : offset + 2]) == {"overlays_on", "overlays_off"}
        for offset in range(0, len(sequence), 2)
    )
    ab_first = sum(1 for offset in range(0, len(sequence), 2) if sequence[offset] == "overlays_on")
    assert ab_first == 10
    assert sequence == counterbalanced_sequence(20)
    assert sequence != counterbalanced_sequence(20, randomization_seed=626)


def test_plan_records_operator_gate_and_plain_report_names() -> None:
    plan = build_plan(2, generated_at_utc="2026-07-22T12:00:00Z", allow_undersized=True)
    assert plan["operator_owned_settings"] is True
    assert plan["protocol"]["fresh_reboot_before_run"] is True
    assert plan["protocol"]["restore_settings_after_run"] is True
    assert plan["protocol"]["condition_definitions"]["overlays_off"] == {
        "steam_overlay_enabled": False,
        "nvidia_shadowplay_enabled": False,
    }
    assert plan["launch"] == {
        "car": "ks_porsche_911_gt3_r_2016",
        "track": "spa",
        "stability_window": 140.0,
        "trials_per_invocation": 1,
    }
    assert plan["randomization_seed"] == 625
    assert all(
        {plan["trials"][offset]["condition"], plan["trials"][offset + 1]["condition"]}
        == {"overlays_on", "overlays_off"}
        for offset in range(0, 4, 2)
    )
    assert plan["trials"][0]["report"] == f"trial-001-{plan['trials'][0]['condition']}.json"


def test_build_plan_rejects_undersized_experiment() -> None:
    with pytest.raises(ValueError, match=str(MIN_TRIALS_PER_ARM)):
        build_plan(MIN_TRIALS_PER_ARM - 1)


def test_load_plan_rejects_non_interleaved_pair(tmp_path: Path) -> None:
    plan = build_plan(2, allow_undersized=True)
    plan["trials"][1]["condition"] = plan["trials"][0]["condition"]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="condition|interleave|randomization_seed"):
        load_plan(path)


def test_load_plan_rejects_reordered_schedule(tmp_path: Path) -> None:
    plan = build_plan(2, allow_undersized=True)
    plan["trials"][0]["condition"], plan["trials"][1]["condition"] = (
        plan["trials"][1]["condition"],
        plan["trials"][0]["condition"],
    )
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="randomization_seed"):
        load_plan(path)


def test_report_summary_must_match_attempt_verdict(tmp_path: Path) -> None:
    plan = build_plan(1, allow_undersized=True)
    first = plan["trials"][0]
    path = tmp_path / first["report"]
    _write_report(
        path,
        verdict="stable",
        started_at_utc="2026-07-22T12:00:00Z",
        uptime_h=0.1,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["counts"]["stable"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="summary"):
        load_observations(plan, tmp_path, require_complete=False)


def test_observations_require_complete_reports_uptime_and_order(tmp_path: Path) -> None:
    plan = build_plan(1, allow_undersized=True)
    _write_report(
        tmp_path / plan["trials"][0]["report"],
        verdict="stable",
        started_at_utc="2026-07-22T12:00:00Z",
        uptime_h=0.1,
    )
    with pytest.raises(ValueError, match="incomplete"):
        load_observations(plan, tmp_path)

    _write_report(
        tmp_path / plan["trials"][1]["report"],
        verdict="froze",
        started_at_utc="2026-07-22T11:59:00Z",
        uptime_h=0.2,
    )
    with pytest.raises(ValueError, match="increase"):
        load_observations(plan, tmp_path)

    second = tmp_path / plan["trials"][1]["report"]
    second.unlink()
    _write_report(
        second,
        verdict="froze",
        started_at_utc="2026-07-22T12:01:00Z",
        uptime_h=None,
    )
    with pytest.raises(ValueError, match="uptime_h"):
        load_observations(plan, tmp_path)


def test_observations_reject_mid_run_reboot(tmp_path: Path) -> None:
    plan = build_plan(1, allow_undersized=True)
    _write_report(
        tmp_path / plan["trials"][0]["report"],
        verdict="stable",
        started_at_utc="2026-07-22T12:00:00Z",
        uptime_h=4.19,
    )
    _write_report(
        tmp_path / plan["trials"][1]["report"],
        verdict="froze",
        started_at_utc="2026-07-22T12:01:00Z",
        uptime_h=0.10,
    )
    with pytest.raises(ValueError, match="nondecreasing|reboot"):
        load_observations(plan, tmp_path)


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


def test_analysis_counts_both_freeze_buckets_and_reports_no_measurable_effect() -> None:
    observations: list[Observation] = []
    for index in range(20):
        for condition, verdict in (
            ("overlays_on", "froze" if index < 10 else "stable"),
            ("overlays_off", "wedged_init" if index < 10 else "stable"),
        ):
            observations.append(
                Observation(
                    trial=len(observations) + 1,
                    condition=condition,
                    verdict=verdict,
                    started_at_utc=f"2026-07-22T12:{len(observations):02d}:00Z",
                    elapsed_s=10.0,
                    uptime_h=1.0 + len(observations) / 60,
                )
            )
    result = analyze(observations)
    assert result["schema"] == ANALYSIS_SCHEMA
    assert result["arms"]["overlays_on"]["freeze_count"] == 10
    assert result["arms"]["overlays_off"]["freeze_count"] == 10
    assert result["conclusion"] == "no_measurable_effect"
    assert "Fisher exact" in render_markdown(result)


def test_never_live_is_separate_and_cannot_complete_the_primary_endpoint() -> None:
    observations: list[Observation] = []
    for pair in range(20):
        for condition in ("overlays_on", "overlays_off"):
            observations.append(
                Observation(
                    trial=len(observations) + 1,
                    condition=condition,
                    verdict=(
                        "never_live" if pair == 0 and condition == "overlays_on" else "stable"
                    ),
                    started_at_utc=f"2026-07-22T12:{len(observations):02d}:00Z",
                    elapsed_s=10.0,
                    uptime_h=1.0,
                )
            )
    result = analyze(observations)
    assert result["arms"]["overlays_on"]["total"] == 20
    assert result["arms"]["overlays_on"]["analyzable_total"] == 19
    assert result["arms"]["overlays_on"]["never_live"] == 1
    assert result["paired_sensitivity"]["excluded_never_live_pairs"] == 1
    assert result["conclusion"] == "insufficient_sample"


def test_analysis_detects_material_lower_off_rate() -> None:
    pairs: list[tuple[str, str]] = []
    for index in range(20):
        pairs.extend(
            [
                ("overlays_on", "froze" if index < 16 else "stable"),
                ("overlays_off", "froze" if index < 4 else "stable"),
            ]
        )
    observations = tuple(
        Observation(
            trial=index + 1,
            condition=condition,
            verdict=verdict,
            started_at_utc=f"2026-07-22T12:{index:02d}:00Z",
            elapsed_s=10.0,
            uptime_h=2.0,
        )
        for index, (condition, verdict) in enumerate(pairs)
    )
    result = analyze(observations)
    assert result["fisher_exact_two_sided_p"] < 0.001
    assert result["risk_difference_off_minus_on"] == pytest.approx(-0.6)
    assert result["conclusion"] == "overlays_off_lower_freeze_rate"
    assert result["paired_sensitivity"]["exact_two_sided_p"] < 0.001


def test_undersized_significant_run_stays_insufficient_sample() -> None:
    """A dry-run with n=5/arm must not claim the experiment endpoint even if Fisher is tiny."""
    observations: list[Observation] = []
    for _index in range(5):
        for condition, verdict in (
            ("overlays_on", "froze"),
            ("overlays_off", "stable"),
        ):
            observations.append(
                Observation(
                    trial=len(observations) + 1,
                    condition=condition,
                    verdict=verdict,
                    started_at_utc=f"2026-07-22T12:{len(observations):02d}:00Z",
                    elapsed_s=10.0,
                    uptime_h=1.0 + len(observations) / 60,
                )
            )
    result = analyze(observations, minimum_per_arm=5)
    assert result["minimum_per_arm"] == MIN_TRIALS_PER_ARM
    assert result["fisher_exact_two_sided_p"] < 0.01
    assert result["conclusion"] == "insufficient_sample"


def test_duplicate_timestamps_accepted_when_uptime_strictly_increases(
    tmp_path: Path,
) -> None:
    plan = build_plan(1, allow_undersized=True)
    stamp = "2026-07-22T12:00:00Z"
    _write_report(
        tmp_path / plan["trials"][0]["report"],
        verdict="stable",
        started_at_utc=stamp,
        uptime_h=1.0,
    )
    _write_report(
        tmp_path / plan["trials"][1]["report"],
        verdict="froze",
        started_at_utc=stamp,
        uptime_h=1.1,
    )
    observations = load_observations(plan, tmp_path)
    assert len(observations) == 2


def test_report_launch_must_match_plan(tmp_path: Path) -> None:
    plan = build_plan(1, allow_undersized=True)
    _write_report(
        tmp_path / plan["trials"][0]["report"],
        verdict="stable",
        started_at_utc="2026-07-22T12:00:00Z",
        uptime_h=1.0,
        launch={
            "car": "wrong_car",
            "track": "spa",
            "stability_window": 140.0,
            "trials_per_invocation": 1,
        },
    )
    with pytest.raises(ValueError, match="launch.car"):
        load_observations(plan, tmp_path, require_complete=False)


def test_all_never_live_arm_reports_insufficient_sample() -> None:
    observations: list[Observation] = []
    for _index in range(20):
        for condition, verdict in (
            ("overlays_on", "never_live"),
            ("overlays_off", "stable"),
        ):
            observations.append(
                Observation(
                    trial=len(observations) + 1,
                    condition=condition,
                    verdict=verdict,
                    started_at_utc=f"2026-07-22T12:{len(observations):02d}:00Z",
                    elapsed_s=10.0,
                    uptime_h=1.0 + len(observations) / 60,
                )
            )
    result = analyze(observations)
    assert result["arms"]["overlays_on"]["analyzable_total"] == 0
    assert result["arms"]["overlays_on"]["never_live"] == 20
    assert result["conclusion"] == "insufficient_sample"
