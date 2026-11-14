"""Stage 0 feasibility analysis (issue #989): rates, variance, simulated detectable effect and
the fixed proceed / stop / inconclusive thresholds.
"""

from __future__ import annotations

import json
import random

import pytest

from tools.ai_sidecar.coaching_trial import JOURNAL_SCHEMA, ExposureJournal
from tools.coaching_lake import coaching_effect as effect


def _journal(
    session: str,
    *,
    laps: int = 12,
    lap_ms: float = 90_000.0,
    corners: dict[int, list[float]] | None = None,
    root: str = "slow_apex",
    assess_laps: int = 2,
    committed: bool = True,
) -> list[dict]:
    """A journal with one approach per (coached lap, corner); ``corners`` maps corner ->
    targeted-error magnitude on successive coached laps.
    """
    journal = ExposureJournal()
    journal.append(
        "session",
        session=session,
        ledger={"assess_laps": assess_laps},
        context={"combo": ["car", "track", None]},
    )
    corners = corners if corners is not None else {2: [10.0, 9.0, 11.0, 10.0]}
    for lap in range(1, laps + 1):
        for corner, values in corners.items():
            index = lap - assess_laps - 1
            if not 0 <= index < len(values):
                continue
            approach_id = f"{session}:0:{lap}:{corner}"
            journal.append(
                "armed",
                session=session,
                approach_id=approach_id,
                lap=lap,
                corner=corner,
                root=root,
                assignment="as_delivered",
            )
            if committed:
                journal.append(
                    "commit", session=session, approach_id=approach_id, committed=True, root=root
                )
                journal.append("emitted", session=session, approach_id=approach_id)
            journal.append(
                "outcome",
                session=session,
                approach_id=approach_id,
                pass_measured=True,
                pass_valid=True,
                targeted_error=values[index],
                targeted_error_unit="km/h",
                corner_time_s=12.0 + 0.01 * index,
                gate_reason="",
            )
        journal.append(
            "lap",
            session=session,
            lap=lap,
            lap_uuid=f"{session}-{lap}",
            lap_ms=lap_ms,
            replayed=True,
        )
    return journal.events


def test_rates_and_projection_arithmetic():
    journals = [_journal(f"s{i}", corners={2: [10.0] * 10, 4: [5.0] * 5}) for i in range(3)]
    sessions = [effect.load_session(events) for events in journals]
    rates = effect.armed_rates(sessions)
    row = rates["sessions"][0]
    assert (row["laps_replayed"], row["coached_laps"]) == (12, 10)
    assert (row["armed_approaches"], row["usable_approaches"], row["emitted"]) == (15, 15, 15)
    assert row["armed_per_lap"] == pytest.approx(15 / 12)
    assert rates["pooled"]["usable_per_coached_lap"] == pytest.approx(1.5)
    assert rates["pooled"]["mean_lap_s"] == pytest.approx(90.0)
    projection = effect.project_session(rates)
    # 90 min at 90 s laps = 60 laps, minus 10 uncued = 50 randomized laps at 1.5 per lap
    assert projection == {
        "laps": 60,
        "randomized_laps": 50,
        "usable_approaches": pytest.approx(75.0),
        "track_time_fraction": 1.0,
    }
    assert effect.project_session(rates, track_time_fraction=0.75)["laps"] == 45


def test_uncommitted_and_unmeasured_approaches_are_armed_but_not_usable():
    events = _journal("s0", committed=False)
    session = effect.load_session(events)
    assert len(session["approaches"]) == 4
    assert not any(effect.is_usable(a) for a in session["approaches"])
    events = _journal("s1")
    for event in events:
        if event["event"] == "outcome":
            event["targeted_error"] = None
    assert not any(effect.is_usable(a) for a in effect.load_session(events)["approaches"])


def test_variance_is_reported_per_root_within_corner():
    journals = [
        _journal("s0", corners={2: [10.0, 12.0], 4: [100.0, 102.0]}),
        _journal("s1", corners={2: [0.0, 0.0]}, root="early_brake"),
    ]
    variance = effect.variance_by_root([effect.load_session(e) for e in journals])
    apex = variance["slow_apex"]
    assert (apex["n"], apex["strata"], apex["unit"]) == (4, 2, "km/h")
    assert apex["mean"] == pytest.approx(56.0)
    assert apex["sd"] > 50  # the pooled SD is dominated by the difference between corners
    assert apex["sd_within"] == pytest.approx(2**0.5)  # pass-to-pass, corner means removed
    assert apex["variance_within"] == pytest.approx(2.0)
    assert apex["cv_within"] == pytest.approx(2**0.5 / 56.0)
    assert apex["corner_time_sd_within_s"] == pytest.approx(0.01 / 2**0.5)
    assert variance["early_brake"]["share_zero"] == 1.0
    assert variance["early_brake"]["cv_within"] is None  # no scale: mean is zero


def test_relative_pool_rescales_strata_and_counts_exclusions():
    journals = [_journal("s0", corners={2: [5.0, 15.0], 4: [7.0], 6: [0.0, 0.0]})]
    pool = effect.relative_error_pool([effect.load_session(e) for e in journals])
    assert sorted(pool["values"]) == [0.5, 1.5]
    assert pool["excluded_passes"] == 3  # one single-pass stratum, one zero-mean stratum


def _pool(cv: float, n: int = 400) -> list[float]:
    rng = random.Random(7)
    return [max(0.0, rng.gauss(1.0, cv)) for _ in range(n)]


def test_power_is_deterministic_monotone_and_holds_its_false_positive_rate():
    pool = _pool(0.5)
    kwargs = {"sims": 150, "perms": 99, "seed": 3}
    null = effect.simulate_power(pool, 60, 0.0, **kwargs)
    small = effect.simulate_power(pool, 60, 0.15, **kwargs)
    large = effect.simulate_power(pool, 60, 0.45, **kwargs)
    assert null <= 0.12  # nominal 0.05, 150 simulated sessions
    assert null <= small <= large and large > 0.8
    assert effect.simulate_power(pool, 60, 0.15, **kwargs) == small
    assert effect.simulate_power(pool, 1, 0.9, **kwargs) == 0.0
    assert effect.simulate_power([], 60, 0.9, **kwargs) == 0.0


def test_detectable_effect_tracks_noise_and_sample_size():
    kwargs = {"sims": 80, "perms": 79, "seed": 5}
    quiet = effect.minimum_detectable_effect(_pool(0.1), 60, **kwargs)
    noisy = effect.minimum_detectable_effect(_pool(0.8), 60, **kwargs)
    tiny = effect.minimum_detectable_effect(_pool(0.8), 6, **kwargs)
    assert quiet["effect"] <= 0.10
    assert quiet["effect"] < noisy["effect"]
    assert tiny["effect"] is None or tiny["effect"] > noisy["effect"]
    assert [p["effect"] for p in quiet["power_curve"]] == list(effect.EFFECT_GRID)
    assert quiet["false_positive_rate"] == quiet["power_curve"][0]["power"]


@pytest.mark.parametrize(
    ("sessions", "approaches", "detectable", "verdict"),
    [
        (2, 80.0, 0.10, "blocked"),
        (3, 40.0, 0.25, "proceed"),
        (3, 39.9, 0.25, "inconclusive"),
        (3, 80.0, 0.2501, "inconclusive"),
        (3, 80.0, 0.50, "inconclusive"),
        (3, 80.0, 0.5001, "stop"),
        (3, 10.0, 0.60, "stop"),
        (3, 80.0, None, "stop"),
    ],
)
def test_fixed_thresholds(sessions, approaches, detectable, verdict):
    decision = effect.decide(sessions=sessions, projected_approaches=approaches, effect=detectable)
    assert decision["verdict"] == verdict and decision["reason"]


def test_thresholds_are_the_ones_fixed_in_the_issue():
    assert effect.MIN_SESSIONS == 3
    assert effect.PROCEED_MIN_APPROACHES == 40
    assert effect.PROCEED_MAX_EFFECT == 0.25
    assert effect.STOP_ABOVE_EFFECT == 0.50
    assert (effect.POWER, effect.ALPHA, effect.SESSION_MINUTES) == (0.80, 0.05, 90.0)


def test_report_end_to_end_and_markdown():
    rng = random.Random(11)
    journals = [
        _journal(
            f"s{i}",
            laps=22,
            corners={c: [rng.gauss(10.0, 1.0) for _ in range(20)] for c in (2, 4)},
        )
        for i in range(3)
    ]
    report = effect.feasibility_report(journals, sims=60, perms=59, seed=2)
    assert report["schema"] == effect.REPORT_SCHEMA
    assert report["sessions_replayed"] == 3 and report["combos"] == [["car", "track", None]]
    assert report["projection_90_min"]["usable_approaches"] == pytest.approx(100.0)
    assert report["minimum_detectable_effect"]["n"] == 100
    assert report["minimum_detectable_effect_at_40"]["n"] == 40
    assert report["decision"]["verdict"] == "proceed"  # CV 0.1 at n = 100
    assert report["corner_time_guardrail"]["difference_standard_error_s"] > 0
    json.dumps(report, allow_nan=False)
    text = effect.render_markdown(report)
    assert text.startswith("**Verdict: PROCEED**")
    assert "not attested human laps" in text and "| slow_apex | km/h |" in text


def test_fewer_than_three_sessions_is_blocked_not_a_verdict():
    report = effect.feasibility_report([_journal("s0"), _journal("s1")], sims=10, perms=9)
    assert report["decision"]["verdict"] == "blocked"


def test_no_usable_approaches_stops():
    journals = [_journal(f"s{i}", committed=False) for i in range(3)]
    report = effect.feasibility_report(journals, sims=10, perms=9)
    assert report["projection_90_min"]["usable_approaches"] == 0
    assert report["minimum_detectable_effect"]["effect"] is None
    assert report["decision"]["verdict"] == "stop"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda e: e.pop(0), "exactly_one_session_header"),
        (lambda e: e.append(dict(e[0])), "exactly_one_session_header"),
        (lambda e: e[1].update(session="other"), "journal_mixes_sessions"),
        (lambda e: e.append(dict(e[-1])), "duplicate_lap_identity"),
        (lambda e: e[-1].update(lap_ms=0), "non_finite_or_non_positive_lap_duration"),
        (lambda e: e[0].update(session=""), "journal_session_identity_missing"),
    ],
)
def test_load_session_validates_the_journal(mutate, message):
    events = _journal("s0")
    mutate(events)
    with pytest.raises(ValueError, match=message):
        effect.load_session(events)


def test_duplicate_session_identity_is_rejected():
    with pytest.raises(ValueError, match="duplicate_session_identity"):
        effect.feasibility_report([_journal("s0"), _journal("s0"), _journal("s1")])


def test_cli_writes_new_files_only(tmp_path, capsys):
    for index in range(3):
        path = tmp_path / f"session-{index}.trial.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in _journal(f"s{index}")))
    out, summary = tmp_path / "report.json", tmp_path / "report.md"
    argv = ["--journal-dir", str(tmp_path), "--out", str(out), "--markdown", str(summary)]
    assert effect.main([*argv, "--sims", "10", "--perms", "9"]) == 0
    report = json.loads(out.read_text())
    assert report["journals"] == [f"session-{i}.trial.jsonl" for i in range(3)]
    assert report["minimum_detectable_effect"]["seed"] == 989
    assert summary.read_text() == capsys.readouterr().out.removesuffix("\n")
    with pytest.raises(FileExistsError):
        effect.main([*argv, "--sims", "10", "--perms", "9"])
    assert all(e["schema"] == JOURNAL_SCHEMA for e in _journal("s9"))
