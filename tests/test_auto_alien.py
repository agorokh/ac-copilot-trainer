"""Tests for the #572 one-button alien pipeline orchestration (no rig needed)."""

from __future__ import annotations

import json as _json
from pathlib import Path

import pytest

from tools.ac_harness import auto_alien
from tools.ac_harness.auto_alien import (
    _build_arg_parser,
    drive_argv,
    evaluate_selfplay_iteration,
    flying_lap_consistency,
    identify_argv,
    iteration_scale,
    load_stage_outcome,
    needs_identification,
    resolve_drive_seconds,
    run_pipeline,
    run_scientist,
    stage_lap_archives,
    stage_lap_times_ms,
)


def _args(tmp_path, *extra: str):
    argv = ["--car", "car_a", "--track", "trk", "--ac-user-dir", str(tmp_path), *extra]
    return _build_arg_parser().parse_args(argv)


class _Runner:
    """Records stage argvs; scripted exit codes; optional side effect per call."""

    def __init__(self, codes: list[int], on_call=None):
        self.codes = list(codes)
        self.calls: list[list[str]] = []
        self.on_call = on_call

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        if self.on_call:
            self.on_call(argv)
        return self.codes.pop(0)


def _usable_plant(monkeypatch, usable: bool | list[bool]):
    """Patch the plant lookup auto_alien uses. ``usable`` may be a sequence (per lookup)."""
    seq = usable if isinstance(usable, list) else [usable]
    state = {"i": 0}

    def fake_load(*a, **kw):
        idx = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return {"fit": idx} if seq[idx] else None

    monkeypatch.setattr(auto_alien, "load_plant_artifact", fake_load)
    monkeypatch.setattr(
        auto_alien,
        "plant_ready_for_full_consumption",
        lambda art, *, require_friction_fit: None if art else "no plant artifact for this combo",
    )


def test_needs_identification_reasons(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, [False, True])
    needed, why = needs_identification(tmp_path, "c", "t", None, None, layout=None)
    assert needed and "no plant artifact" in why
    needed, why = needs_identification(tmp_path, "c", "t", None, None, layout=None)
    assert not needed
    needed, why = needs_identification(tmp_path, "c", "t", None, None, layout=None, force=True)
    assert needed and "forced" in why


def test_needs_identification_uses_the_drive_stage_readiness_gate(monkeypatch, tmp_path):
    # The gate is the SHARED plant_ready_for_full_consumption — any reason it returns
    # (missing fit, incomplete steering constants) triggers the handshake stage, so the
    # pipeline can never skip identification for a plant the drive stage would reject.
    monkeypatch.setattr(auto_alien, "load_plant_artifact", lambda *a, **kw: {"fit": 0})
    monkeypatch.setattr(
        auto_alien,
        "plant_ready_for_full_consumption",
        lambda art, *, require_friction_fit: (
            "plant artifact has no uncertainty-aware friction fit (#543)"
        ),
    )
    needed, why = needs_identification(tmp_path, "c", "t", None, None, layout=None)
    assert needed and "uncertainty-aware" in why
    monkeypatch.setattr(
        auto_alien,
        "plant_ready_for_full_consumption",
        lambda art, *, require_friction_fit: "plant artifact missing measured steering constants",
    )
    needed, why = needs_identification(tmp_path, "c", "t", None, None, layout=None)
    assert needed and "steering constants" in why


def test_pipeline_skips_identification_when_plant_usable(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, True)
    runner = _Runner([0])
    args = _args(tmp_path, "--evidence-dir", str(tmp_path / "ev"))
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0 and report["ok"]
    assert not report["identification_needed"]
    assert len(runner.calls) == 1
    drive = runner.calls[0]
    assert ["--driver", "alien"] == drive[drive.index("--driver") : drive.index("--driver") + 2]
    assert "--wait-lap" in drive
    assert "identify" not in report["stages"]


def test_pipeline_runs_identification_then_drive(monkeypatch, tmp_path):
    # Plant unusable until the handshake stage "persists" it (flip on the runner's side effect).
    state = {"usable": False}
    monkeypatch.setattr(
        auto_alien, "load_plant_artifact", lambda *a, **kw: {"x": 1} if state["usable"] else None
    )
    monkeypatch.setattr(
        auto_alien,
        "plant_ready_for_full_consumption",
        lambda art, *, require_friction_fit: None if art else "no plant artifact for this combo",
    )
    settled_urls: list[str] = []
    monkeypatch.setattr(
        auto_alien,
        "wait_sidecar_port_settled",
        lambda url, **kw: settled_urls.append(url) or "released",
    )

    def persist(argv):
        if "handshake" in argv:
            state["usable"] = True

    runner = _Runner([0, 0], on_call=persist)
    args = _args(tmp_path, "--evidence-dir", str(tmp_path / "ev"))
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0 and report["ok"]
    assert report["identification_needed"]
    assert len(runner.calls) == 2
    assert "handshake" in runner.calls[0]
    assert "alien" in runner.calls[1]
    assert report["stages"]["identify"]["exit_code"] == 0
    assert report["stages"]["drive"]["exit_code"] == 0
    # The sidecar port settle runs between the stages (drive never adopts a dying sidecar).
    assert settled_urls == [auto_alien.DEFAULT_SIDECAR_URL]
    assert report["sidecar_port_between_stages"] == "released"


def test_wait_sidecar_port_settled_released_and_stable_and_timeout():
    from tools.ac_harness.auto_alien import wait_sidecar_port_settled

    clock = {"t": 0.0}

    def now():
        return clock["t"]

    def sleep(s):
        clock["t"] += s

    # Port answers twice then dies -> released (the terminated stage sidecar let go).
    answers = iter([True, True, False])
    assert (
        wait_sidecar_port_settled(
            "ws://127.0.0.1:8765", probe=lambda u: next(answers), sleep=sleep, now=now
        )
        == "released"
    )
    # Port answers continuously -> stable pre-existing sidecar, safe to adopt.
    clock["t"] = 0.0
    assert (
        wait_sidecar_port_settled(
            "ws://127.0.0.1:8765", probe=lambda u: True, sleep=sleep, now=now, stable_s=2.0
        )
        == "stable"
    )
    # Port answers but never reaches the stability window within the budget -> timeout
    # (the pipeline proceeds; the drive stage's own sidecar handling takes over).
    clock["t"] = 0.0
    assert (
        wait_sidecar_port_settled(
            "ws://127.0.0.1:8765",
            probe=lambda u: True,
            sleep=sleep,
            now=now,
            timeout_s=3.0,
            stable_s=10.0,
        )
        == "timeout"
    )


def test_pipeline_aborts_when_identification_fails(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, False)
    runner = _Runner([3])
    code, report = run_pipeline(_args(tmp_path), run_stage=runner)
    assert code == 3 and not report["ok"]
    assert "identification stage failed" in report["error"]
    assert len(runner.calls) == 1  # the drive stage never ran


def test_pipeline_aborts_when_plant_still_unusable_after_identify(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, False)  # stays unusable even after the stage exits 0
    runner = _Runner([0])
    code, report = run_pipeline(_args(tmp_path), run_stage=runner)
    assert code == 1 and not report["ok"]
    assert "still unusable" in report["error"]
    assert len(runner.calls) == 1


def test_pipeline_propagates_drive_failure(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, True)
    runner = _Runner([1])
    code, report = run_pipeline(_args(tmp_path), run_stage=runner)
    assert code == 1 and not report["ok"]
    assert "drive stage failed" in report["error"]


def test_force_identify_runs_handshake_even_with_usable_plant(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, True)
    runner = _Runner([0, 0])
    code, report = run_pipeline(_args(tmp_path, "--force-identify"), run_stage=runner)
    assert code == 0 and report["ok"]
    assert "handshake" in runner.calls[0]
    assert "forced" in report["identification_reason"]


def test_pipeline_rejects_path_shaped_ids(tmp_path):
    args = _args(tmp_path)
    args.car = "../evil"
    with pytest.raises(ValueError, match="car"):
        run_pipeline(args, run_stage=_Runner([0]))


def test_stage_argv_builders(tmp_path):
    args = _args(
        tmp_path,
        "--track-layout",
        "gp",
        "--setup",
        "MySetup",
        "--rebuild-line",
        "--strict",
        "--identify-seconds",
        "420",
        "--rig-lock-timeout",
        "30",
    )
    ident = identify_argv(args, tmp_path / "identify")
    assert ["--driver", "handshake"] == ident[ident.index("--driver") : ident.index("--driver") + 2]
    assert ["--drive-seconds", "420.0"] == ident[-2:]
    assert "--track-layout" in ident and "--setup" in ident and "--rig-lock-timeout" in ident

    drive = drive_argv(args, tmp_path / "drive")
    assert ["--driver", "alien"] == drive[drive.index("--driver") : drive.index("--driver") + 2]
    assert "--alien-rebuild-line" in drive
    assert "--strict" in drive
    assert "--wait-lap" in drive
    assert str(tmp_path / "drive") in drive


# --------------------------------------------------------------------------- #577 self-play
def test_resolve_drive_seconds_scales_with_lap_window(tmp_path):
    assert resolve_drive_seconds(_args(tmp_path)) == 300.0
    assert resolve_drive_seconds(_args(tmp_path, "--laps", "3")) == 180.0 + 240.0 * 3
    # An explicit budget always wins ("N laps or the time budget, whichever first").
    assert resolve_drive_seconds(_args(tmp_path, "--laps", "3", "--drive-seconds", "200")) == 200.0


def test_drive_argv_carries_lap_window_scale_and_overspeed(tmp_path):
    args = _args(tmp_path, "--laps", "3")
    drive = drive_argv(args, tmp_path / "d")
    assert ["--laps", "3"] == drive[drive.index("--laps") : drive.index("--laps") + 2]
    assert "--alien-allow-overspeed" not in drive  # scale 0.9: no opt-in
    drive = drive_argv(args, tmp_path / "d", ggv_scale=1.05)
    scale_at = drive.index("--ggv-scale")
    assert ["--ggv-scale", "1.05"] == drive[scale_at : scale_at + 2]
    assert "--alien-allow-overspeed" in drive  # >1 requires the explicit drive-stage opt-in
    assert "--alien-rebuild-line" not in drive
    drive = drive_argv(args, tmp_path / "d", rebuild_line=True)
    assert "--alien-rebuild-line" in drive


def test_iteration_scale_ladder_caps():
    assert iteration_scale(0.9, 0.05, 1, 1.1) == 0.95
    assert iteration_scale(0.9, 0.05, 4, 1.1) == 1.1
    assert iteration_scale(0.9, 0.05, 40, 1.1) == 1.1


# --------------------------------------------------------------------------- #582 L3
def test_drive_argv_enables_l3_by_default_and_no_l3_disables(tmp_path):
    drive = drive_argv(_args(tmp_path), tmp_path / "d")
    assert "--l3" in drive
    drive = drive_argv(_args(tmp_path, "--no-l3"), tmp_path / "d")
    assert "--l3" not in drive


def test_stage_l3_summary_extraction():
    from tools.ac_harness.auto_alien import stage_l3_summary

    assert stage_l3_summary(None) is None
    assert stage_l3_summary({"run": {}}) is None
    assert stage_l3_summary({"run": {"alien_line": {"qss": {}}}}) is None
    # write_evidence stores alien-line detail under the TOP-LEVEL run extras, not report
    # (#583 Codex P2) — a report-nested payload must not match.
    assert stage_l3_summary({"report": {"alien_line": {"l3": {"refined_corners": 1}}}}) is None
    outcome = {
        "run": {
            "alien_line": {
                "l3": {
                    "refined_corners": 3,
                    "reverted_corners": 1,
                    "predicted_gain_ms": 412,
                    "corners": [{"corner": 0}],
                }
            }
        }
    }
    assert stage_l3_summary(outcome) == {
        "refined_corners": 3,
        "reverted_corners": 1,
        "predicted_gain_ms": 412,
    }
    outcome["run"]["alien_line"]["l3"] = {
        "refined_corners": 0,
        "reverted_corners": 0,
        "predicted_gain_ms": 0,
        "reverted_all": "plant is not uncertainty-aware",
    }
    summary = stage_l3_summary(outcome)
    assert summary["reverted_all"] == "plant is not uncertainty-aware"


def _stage_outcome(lap_times, *, recoveries=0, archives=(), stage="done", error=None):
    return {
        "report": {
            "ok": True,
            "stage": stage,
            "error": error,
            "lap_times_ms": list(lap_times),
            "drive": {"recoveries": recoveries},
        },
        "lap_archives": [str(p) for p in archives],
    }


def _archive_payload(lap_n=1, valid=True, car="car_a", track="trk", lap_ms=90000):
    return {
        "car": {"id": car},
        "track": {"id": track, "layout": None},
        "lap": {"lap_n": lap_n, "lap_ms": lap_ms, "is_valid": valid},
    }


def _batch(*lap_ms, valid=True):
    """A clean per-lap batch; the first entry is the standing-start out-lap."""
    return [
        _archive_payload(lap_n=i, valid=valid, lap_ms=ms) for i, ms in enumerate(lap_ms, start=1)
    ]


def test_evaluate_selfplay_iteration_falsification_branches():
    # The archives must reproduce the reported timed laps; the oracle checks that since #746
    # round 8, so these fixtures carry the same times the stage reports.
    ok_payloads = _batch(95000, 93000)
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000]), ok_payloads)
    assert valid and "AC-valid" in reason

    valid, reason = evaluate_selfplay_iteration(0, None, ok_payloads)
    assert not valid and "report missing" in reason

    valid, reason = evaluate_selfplay_iteration(
        1, _stage_outcome([95000], stage="drive", error="boom"), _batch(95000)
    )
    assert not valid and "exit 1" in reason and "boom" in reason

    # A VETOED drive finishes stage=done with error=None and the cause in `reason`; reporting
    # `error` alone rendered a real physics falsification as "error=None" (#746).
    vetoed = _stage_outcome([177161], recoveries=7)
    vetoed["report"]["reason"] = "recovery cap (6) exceeded at 10366m"
    valid, reason = evaluate_selfplay_iteration(1, vetoed, _batch(177161))
    assert not valid and "recovery cap (6) exceeded at 10366m" in reason
    assert "error=None" not in reason

    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([95000], recoveries=2), _batch(95000)
    )
    assert not valid and "recovery" in reason

    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([]), ok_payloads)
    assert not valid and "no timed lap" in reason

    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000]), [])
    assert not valid and "no lap archives" in reason

    bad = _batch(95000, 96000)
    bad[1]["lap"]["is_valid"] = False
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 96000]), bad)
    assert not valid and "AC-invalid lap" in reason and "lap_n=2" in reason

    # A payload with no explicit lap-validity verdict fails CLOSED (#579 Qodo).
    malformed = [_archive_payload(1, lap_ms=95000), {"car": {"id": "car_a"}, "trace": {}}]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 96000]), malformed)
    assert not valid and "without a lap-validity verdict" in reason

    # A partial archive set leaves counted laps unverifiable -> falsified (#579 Codex P2).
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([95000, 93000, 92000]), [_archive_payload(1, lap_ms=95000)]
    )
    assert not valid and "archive count 1 < 3 timed laps" in reason


def test_flying_lap_spread_falsifies_an_unrepeatable_envelope():
    """The #529 ladder-3 batch: drivable once, not reproducible -> must falsify (#746).

    Real archives from 2026-07-26 (911 GT3 R @ Magione): out-lap 106.655 s then flying laps
    80.791 s and 95.122 s, every lap AC-valid with zero recoveries. The pre-#746 oracle called
    this VALID and the 86.27 s-floor plant was retained on it.
    """
    batch = _batch(106655, 80791, 95122)
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 80791, 95122]), batch)
    assert not valid
    assert "not repeatable" in reason
    assert "17.7%" in reason  # (95.122 - 80.791) / 80.791
    assert "80.791s" in reason and "95.122s" in reason


def test_flying_lap_spread_ignores_the_out_lap():
    """The out-lap is legitimately slow; counting it would falsify every healthy batch (#746)."""
    # Ladder 2's stint: same shape, but the two FLYING laps are 14 ms apart.
    batch = _batch(106655, 81505, 81519)
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), batch)
    assert valid, reason
    assert "spread 0.02%" in reason
    # The out-lap alone is 31% slower than the flyers — proof it was excluded, not tolerated.
    consistency = flying_lap_consistency(batch)
    assert consistency["judged"] and consistency["out_lap_ms"] == 106655
    assert consistency["flying_ms"] == [81505, 81519]


def test_flying_lap_spread_is_unjudged_rather_than_falsified_when_it_cannot_be_measured():
    """Unjudgeable is not a falsification — the batch still faces every other gate (#746)."""
    # One flying lap after the out-lap: nothing to compare against.
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([95000, 93000]), _batch(95000, 93000)
    )
    assert valid and "consistency unjudged" in reason and "need 2 to compare" in reason

    # A payload with no lap_n is CORRUPT, not merely unjudgeable, and fails closed — see
    # test_malformed_lap_evidence_falsifies_but_unjudgeable_evidence_does_not (#746).

    # A duplicate lap_n is session CONTAMINATION and fails closed — see
    # test_mixed_session_batch_falsifies_because_the_refit_would_consume_it (#746).


def test_an_unattributable_batch_falsifies_rather_than_being_judged_as_the_batch():
    """An over-wide archive scan validates NOTHING (#746 Codex P1, round 7).

    ``collect_lap_archives`` returns every combo-matching archive newer than ``since_epoch``,
    which can exceed the timed-lap count. This was first modelled as "valid but withheld from the
    refit" — a third state, neither validated nor rejected, that had to be re-defended at every
    consumer (refit, scientist baseline, scientist candidate, rung counter, persisted plant
    candidate); four of those were missed. A batch that cannot be shown to be this drive's own
    evidence now takes the ordinary keep-last-valid path instead.
    """
    # Two repeatable flying laps (14 ms apart) plus a stray archive from another stint.
    payloads = _batch(106655, 81505, 81519, 95122)
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), payloads)
    assert not valid
    assert "not attributable" in reason
    # Same laps, correctly attributed, stay judged and VALID.
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), _batch(106655, 81505, 81519)
    )
    assert valid and "spread 0.02%" in reason


def test_malformed_lap_evidence_falsifies_but_unjudgeable_evidence_does_not():
    """Corrupt evidence fails CLOSED; merely-unjudgeable evidence does not (#746 self-hosted).

    An archive that passed `is_valid` yet has no usable `lap_n`/`lap_ms` contradicts its own
    schema — the refit consumes that same batch, so it must falsify. A two-lap ladder or an
    over-wide archive scan is a known harness situation, not corrupt data, and falsifying it
    would revert the plant and stop the ladder for no physical reason.
    """
    broken_n = _batch(95000, 93000, 92000)
    del broken_n[1]["lap"]["lap_n"]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000, 92000]), broken_n)
    assert not valid and "unusable lap evidence" in reason and "no integer lap_n" in reason

    broken_ms = _batch(95000, 93000, 92000)
    broken_ms[2]["lap"]["lap_ms"] = 0
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000, 92000]), broken_ms)
    assert not valid and "unusable lap evidence" in reason and "finite positive lap_ms" in reason

    # The one genuinely unjudgeable case that must still stay VALID: a correctly attributed batch
    # that simply does not have two flying laps to compare. Falsifying it would break every
    # ordinary `--laps 2` ladder, which is what the G1b cold start runs.
    valid, _ = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000]), _batch(95000, 93000))
    assert valid, "an ordinary --laps 2 ladder must not be falsified for lacking a second flyer"


def test_mixed_session_batch_falsifies_because_the_refit_would_consume_it():
    """A duplicate lap_n means two sessions in one batch — fail closed (#746 Codex P2).

    When `auto_drive` retries after a sim death that already produced an archive,
    `run_started_epoch` spans both attempts while the Lua session resets `lap_n`. The batch then
    mixes sessions with different tyre states, and it also feeds `persist_selfplay_refinement`,
    whose merge is strictly monotone — so a hotter session's grip would be adopted permanently.
    Scoping archives to the batch at source is the real fix (#751); this is the safety net.
    """
    dupes = _batch(95000, 93000, 92000)
    dupes[2]["lap"]["lap_n"] = 2
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000, 92000]), dupes)
    assert not valid
    assert "unusable lap evidence" in reason and "more than one session" in reason


def test_corruption_is_checked_before_the_count_mismatch():
    """Schema/duplicate checks must precede the count check (#746 Codex P2 + Qodo, round 3).

    A retry that leaves one archive from the failed attempt alongside the final attempt's laps
    produces BOTH a count mismatch and a duplicate `lap_n`. Returning on the count first labelled
    that mixed-session batch `malformed=False`, so the oracle accepted it and `run_selfplay`
    handed the whole list to the next refit — the exact contamination the duplicate check exists
    to prevent.
    """
    # Count mismatch AND a duplicate lap_n: contamination must win over "not attributable".
    mixed = _batch(95000, 93000, 92000)
    mixed[2]["lap"]["lap_n"] = 2
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000]), mixed)
    assert not valid, "a mixed-session batch must falsify even when the count also mismatches"
    assert "more than one session" in reason

    # Count mismatch AND corrupt lap evidence: corruption must win.
    corrupt = _batch(95000, 93000, 92000)
    del corrupt[1]["lap"]["lap_n"]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000]), corrupt)
    assert not valid and "unusable lap evidence" in reason


def test_non_finite_lap_time_cannot_pass_as_a_positive_lap_ms():
    """`NaN <= 0` is False, so NaN slipped the positivity check (#746 Codex P2).

    A NaN lap time yields a NaN spread, and `NaN > threshold` is also False, so the corrupt batch
    was reported VALID with "flying-lap spread nan%".
    """
    # An oversized Python int is the same class of corruption but a different failure: ints are
    # arbitrary precision, so `math.isfinite(10**309)` RAISES OverflowError and would abort the
    # pipeline rather than fail the batch closed (#746 Codex P2, round 4).
    for bad in (float("nan"), float("inf"), float("-inf"), 10**309, 10**400, -(10**400)):
        batch = _batch(106655, 81505, 81519)
        batch[2]["lap"]["lap_ms"] = bad
        valid, reason = evaluate_selfplay_iteration(
            0, _stage_outcome([106655, 81505, 81519]), batch
        )
        assert not valid, f"lap_ms={bad!r} must falsify, not be accepted"
        assert "finite positive lap_ms" in reason
        assert "nan" not in reason.lower()


def test_batch_spanning_two_session_uuids_falsifies():
    """`session_uuid` is the direct attribution fact; unique lap_n is only a proxy (#746 round 6).

    A missing current archive replaced by a uniquely-numbered lap from a neighbouring stint gives
    the expected COUNT and unique lap numbers, so the duplicate check passes while the batch still
    spans two sessions. Two distinct non-empty UUIDs prove contamination; absence proves nothing.
    """
    batch = _batch(106655, 81505, 81519)
    for payload in batch:
        payload["session_uuid"] = "aaaa1111"
    batch[2]["session_uuid"] = "bbbb2222"
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), batch)
    assert not valid
    assert "spans 2 session_uuids" in reason

    # One shared UUID is fine, and so is the legacy case where none carry one.
    same = _batch(106655, 81505, 81519)
    for payload in same:
        payload["session_uuid"] = "aaaa1111"
    valid, _ = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), same)
    assert valid
    valid, _ = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), _batch(106655, 81505, 81519)
    )
    assert valid


def test_gapped_lap_numbers_falsify_even_when_the_times_line_up():
    """A lap_n gap is an attribution failure even if the times match (#746 Codex P2, round 9).

    Archives for lap_n 1, 2, 4 mean the counted lap 3's validity and telemetry are absent and
    lap 4 stood in for it — so lap 4 would feed refinement in lap 3's place. Times can coincide
    to the millisecond, so the multiset comparison alone does not catch it.
    """
    batch = _batch(106655, 81505, 81519)
    batch[2]["lap"]["lap_n"] = 4  # lap 3 missing, a post-window lap stands in with the same time
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), batch)
    assert not valid
    assert "not contiguous" in reason
    # The contiguous batch with identical times stays VALID.
    valid, _ = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), _batch(106655, 81505, 81519)
    )
    assert valid


def test_a_permuted_lap_time_stream_is_not_attributable():
    """Times must match IN LAP ORDER, not as a multiset (#746 Codex P2, round 11).

    The report's `lap_times_ms` is the tap's ordered stream. Sorting both sides accepts archives
    whose lap_n-to-time correspondence is scrambled — and since the out-lap is chosen by `lap_n`,
    a permutation can move the slow lap out of position 1 and change which lap is discarded.
    """
    # Reported out-lap 106655 first; archives carry the same three times in a different order.
    permuted = [
        _archive_payload(1, lap_ms=81505),
        _archive_payload(2, lap_ms=106655),
        _archive_payload(3, lap_ms=81519),
    ]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([106655, 81505, 81519]), permuted)
    assert not valid, "a permuted lap stream must not be judged as the batch"
    assert "do not match" in reason
    # In-order archives for the same reported stream stay VALID.
    valid, _ = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), _batch(106655, 81505, 81519)
    )
    assert valid


def test_a_shifted_lap_window_cannot_invert_the_out_lap():
    """A window starting past lap 1 flips which lap is treated as the out-lap (#746 round 10).

    Codex's case: reported ``[96000, 80000, 95000]`` with archives ``(2,80000) (3,95000)
    (4,96000)``. Multiset matches, lap numbers are contiguous — but the helper then drops lap 2
    as the "out-lap" and reports a **1.1%** spread where the drive's real flying spread was
    **18.8%**. The gate inverts into hiding precisely what it exists to catch.
    """
    shifted = [
        _archive_payload(2, lap_ms=80000),
        _archive_payload(3, lap_ms=95000),
        _archive_payload(4, lap_ms=96000),
    ]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([96000, 80000, 95000]), shifted)
    assert not valid, "a shifted window must not be judged as the batch"
    assert "not 1" in reason and "shifted" in reason
    # The same times, correctly anchored, expose the real 18.8% spread instead.
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([96000, 80000, 95000]), _batch(96000, 80000, 95000)
    )
    assert not valid and "not repeatable" in reason and "18.8%" in reason


def test_non_positive_lap_numbers_are_malformed_not_silently_dropped():
    """A `lap_n <= 0` record sorts first and would be discarded as the out-lap (#746 round 6)."""
    for bad_n in (0, -1):
        batch = _batch(106655, 81505, 81519)
        batch[0]["lap"]["lap_n"] = bad_n
        valid, reason = evaluate_selfplay_iteration(
            0, _stage_outcome([106655, 81505, 81519]), batch
        )
        assert not valid, f"lap_n={bad_n} must falsify rather than be dropped as the out-lap"
        assert "not a completed lap number" in reason


def test_oracle_uses_the_consistency_measurement_it_is_given():
    """The ladder measures once and passes it in, so report and verdict cannot diverge (#746)."""
    batch = _batch(106655, 81505, 81519)
    measured = flying_lap_consistency(batch, expected_lap_times_ms=[106655, 81505, 81519])
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), batch, consistency=measured
    )
    assert valid and "spread 0.02%" in reason
    # A supplied measurement is authoritative: pass a falsifying one over the same laps.
    injected = flying_lap_consistency(
        _batch(106655, 80791, 95122), expected_lap_times_ms=[106655, 80791, 95122]
    )
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([106655, 81505, 81519]), batch, consistency=injected
    )
    assert not valid and "not repeatable" in reason


def test_flying_lap_spread_threshold_admits_every_healthy_historical_batch():
    """No false positives against real rig history (#746).

    Every self-play-era batch measured on the rig that had >=2 flying laps and a spread under
    1% must stay VALID; the three measured pathologies must not.
    """
    healthy = [  # (out-lap, flying...) in ms, from journal/laps
        (191890, 180366, 180387),  # huracan @ spa, 2026-08-10
        (106655, 81505, 81519),  # 911 @ magione, ladder 2
        (112002, 85072, 85132),  # 911 @ magione, 1.15 rung
        (145361, 109110, 109107),  # 911 @ magione, 2026-07-14
    ]
    for laps in healthy:
        valid, reason = evaluate_selfplay_iteration(0, _stage_outcome(list(laps)), _batch(*laps))
        assert valid, f"{laps} should stay VALID but was falsified: {reason}"

    pathological = [
        (178873, 190068, 155763, 169388),  # amg_gtp @ spa, 22.0%
        (106655, 80791, 95122),  # 911 @ magione, 17.7%
        (189509, 167425, 159161),  # 911 @ spa, 5.2%
    ]
    for laps in pathological:
        valid, reason = evaluate_selfplay_iteration(0, _stage_outcome(list(laps)), _batch(*laps))
        assert not valid, f"{laps} should falsify but was accepted"
        assert "not repeatable" in reason


def test_stage_outcome_readers_round_trip(tmp_path):
    stage = tmp_path / "drive"
    stage.mkdir()
    payload = _stage_outcome([95000], archives=[tmp_path / "lap_1.json"])
    (stage / "report.json").write_text(_json.dumps(payload), encoding="utf-8")
    outcome = load_stage_outcome(stage)
    assert stage_lap_times_ms(outcome) == [95000]
    assert stage_lap_archives(outcome) == [str(tmp_path / "lap_1.json")]
    assert load_stage_outcome(tmp_path / "missing") is None
    assert stage_lap_times_ms(None) == []
    assert stage_lap_archives(None) == []


def test_pipeline_rejects_bad_selfplay_flags(monkeypatch, tmp_path):
    _usable_plant(monkeypatch, True)
    with pytest.raises(ValueError, match="--laps"):
        run_pipeline(_args(tmp_path, "--laps", "-1"), run_stage=_Runner([0]))
    with pytest.raises(ValueError, match="--iterations"):
        run_pipeline(_args(tmp_path, "--iterations", "-2"), run_stage=_Runner([0]))
    # The base drive keeps the #572 one-shot gate: a bare overspeed scale is rejected here,
    # never silently forwarded with --alien-allow-overspeed (#579 Codex P1).
    with pytest.raises(ValueError, match="--ggv-scale"):
        run_pipeline(_args(tmp_path, "--ggv-scale", "1.05"), run_stage=_Runner([0]))
    # Self-play needs timed-lap batches; legacy any-boundary --wait-lap cannot provide them.
    with pytest.raises(ValueError, match="--iterations requires --laps"):
        run_pipeline(_args(tmp_path, "--iterations", "1"), run_stage=_Runner([0]))
    with pytest.raises(ValueError, match="--scale-step"):
        run_pipeline(
            _args(tmp_path, "--iterations", "1", "--laps", "1", "--scale-step", "0"),
            run_stage=_Runner([0]),
        )
    with pytest.raises(ValueError, match="--max-scale"):
        run_pipeline(
            _args(tmp_path, "--iterations", "1", "--laps", "1", "--max-scale", "1.5"),
            run_stage=_Runner([0]),
        )
    # A cap below the base scale would make iteration 1 an EASIER envelope than the base drive.
    with pytest.raises(ValueError, match="must be >= --ggv-scale"):
        run_pipeline(
            _args(tmp_path, "--iterations", "1", "--laps", "1", "--max-scale", "0.8"),
            run_stage=_Runner([0]),
        )
    with pytest.raises(ValueError, match="--scientist requires"):
        run_pipeline(_args(tmp_path, "--scientist"), run_stage=_Runner([0]))
    with pytest.raises(ValueError, match="--scientist requires"):
        run_pipeline(
            _args(
                tmp_path,
                "--scientist",
                "--setup",
                "baseline",
                "--iterations",
                "1",
                "--laps",
                "1",
            ),
            run_stage=_Runner([0]),
        )
    with pytest.raises(ValueError, match="--scientist-batch-size"):
        run_pipeline(_args(tmp_path, "--scientist-batch-size", "4"), run_stage=_Runner([0]))


def _fake_artifact_from_bytes(raw, *_a, **_kw):
    """Stand-in for `plant_id.plant_artifact_from_bytes` that stays content-sensitive.

    Derived from the real fixture bytes so a peer rewrite changes the artifact — and therefore
    its provenance hash — exactly as it would in the product. A constant dict would make every
    fit look identical and silently disable the peer-change tests.
    """
    if raw is None:
        return None
    return {"fit": 0, "_raw": raw.decode("utf-8", "replace")}


class _SelfplayHarness:
    """Fakes the drive stages + plant persistence for the iterate-loop orchestration tests."""

    def __init__(
        self,
        monkeypatch,
        tmp_path,
        stage_specs,
        refine_ok=True,
        merge_stats=None,
        mutate_plant_during_refine=False,
        persist_error_after_write=False,
    ):
        self.tmp_path = tmp_path
        self.stage_specs = list(stage_specs)  # per drive call: (exit, lap_times, archive_valids)
        self.refine_ok = refine_ok
        # A dict applies to every refine call; a list scripts them per call (the last entry
        # repeats), so a test can replay a real ladder whose first refit was a no-op.
        self.merge_stats = merge_stats or {
            "lateral_bins_adopted": 0,
            "lateral_bins_raised": 1,
            "mu_lat_g_before": 1.5,
            "mu_lat_g_after": 1.5,
        }
        self.mutate_plant_during_refine = mutate_plant_during_refine
        self.persist_error_after_write = persist_error_after_write
        self.refine_calls: list[list[dict]] = []
        self.persist_lock_timeouts: list[float] = []
        self.plant_path = tmp_path / "plant_id" / "car_a__trk.json"
        self.plant_path.parent.mkdir(parents=True, exist_ok=True)
        self.plant_path.write_text('{"v": "original"}', encoding="utf-8")
        self.saves = 0

        _usable_plant(monkeypatch, True)
        monkeypatch.setattr(auto_alien, "wait_sidecar_port_settled", lambda url, **kw: "released")
        monkeypatch.setattr(auto_alien, "plant_artifact_path", lambda *a, **kw: self.plant_path)
        # `_usable_plant` fakes `load_plant_artifact` with a synthetic dict, so the product's
        # provenance helper would hash that instead of the fixture file the fake drive reports
        # from. Bind both to the artifact ON DISK so "the plant on disk is the plant" holds in the
        # fake exactly as it does in the product — otherwise every ladder trips the round-5
        # base-provenance gate on a disagreement that only exists in the harness.
        # The refit path now parses the snapshot it compares and writes against, so the fake
        # loader must cover that entry point too (mirrors `_usable_plant`).
        monkeypatch.setattr(auto_alien, "plant_artifact_from_bytes", _fake_artifact_from_bytes)

        def fake_refine(artifact, payloads, prior, **kw):
            self.refine_calls.append(list(payloads))
            if self.mutate_plant_during_refine:
                self.plant_path.write_text('{"v": "peer"}', encoding="utf-8")
            if not self.refine_ok:
                return None, {"ok": False, "reason": "batch refit degraded (test)"}
            stats = self.merge_stats
            if isinstance(stats, list):
                stats = stats[min(len(self.refine_calls) - 1, len(stats) - 1)]
            return {"ok": True}, {"ok": True, "selfplay_merge": dict(stats)}

        def fake_persist(
            user_dir,
            result,
            *,
            expected_path,
            expected_current_bytes,
            lock_timeout=0.0,
        ):
            del user_dir, result
            self.persist_lock_timeouts.append(lock_timeout)
            if Path(expected_path).read_bytes() != expected_current_bytes:
                return None, None, "plant artifact changed between load and save (test peer)"
            self.saves += 1
            self.plant_path.write_text(_json.dumps({"v": f"iter{self.saves}"}), encoding="utf-8")
            if self.persist_error_after_write:
                raise OSError("late candidate read failed")
            return self.plant_path, self.plant_path.read_bytes(), None

        def fake_revert(
            path,
            previous_bytes,
            *,
            expected_current_bytes,
            car_id,
            track_id,
            lock_timeout=0.0,
        ):
            del car_id, track_id, lock_timeout
            path = Path(path)
            if path.read_bytes() != expected_current_bytes:
                return False
            path.write_bytes(previous_bytes)
            return True

        import tools.ac_harness.plant_id as plant_id_mod

        monkeypatch.setattr(plant_id_mod, "selfplay_refine_result", fake_refine)
        monkeypatch.setattr(plant_id_mod, "persist_selfplay_refinement", fake_persist)
        monkeypatch.setattr(plant_id_mod, "revert_plant_artifact", fake_revert)

    def _plant_bytes_direct(self):
        """Read the fixture artifact WITHOUT going through ``auto_alien._read_plant_bytes``.

        The peer-window tests count the product's plant reads to place their injection precisely;
        if the harness's own bookkeeping went through the same (monkeypatched) helper it would
        shift those counts and silently move what those tests exercise.
        """
        try:
            return self.plant_path.read_bytes() if self.plant_path.exists() else None
        except OSError:
            # The filesystem-error test makes reads raise to exercise the PRODUCT's guard; the
            # fixture's own bookkeeping must not turn that into a harness crash.
            return None

    def _plant_fit_direct(self):
        """Provenance of the artifact on disk, via the same gate the product parses through."""
        from tools.ac_harness.alien_line import plant_provenance

        artifact = _fake_artifact_from_bytes(self._plant_bytes_direct())
        return plant_provenance(artifact).get("sha12") if artifact is not None else None

    def runner(self):
        state = {"i": 0}

        def run(argv: list[str]) -> int:
            exit_code, lap_times, archive_valids = self.stage_specs[state["i"]]
            state["i"] += 1
            stage_dir = Path(argv[argv.index("--evidence-dir") + 1])
            stage_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for n, valid in enumerate(archive_valids, start=1):
                p = stage_dir / f"lap_{n}.json"
                # A real drive archives the very laps it timed; the oracle now checks that
                # correspondence, so the fake must honour it too (#746 round 8). An archive with
                # no matching reported lap keeps a distinct time, which is exactly the
                # unattributable shape some tests want.
                lap_ms = lap_times[n - 1] if n - 1 < len(lap_times) else 90000
                p.write_text(
                    _json.dumps(_archive_payload(n, valid, lap_ms=lap_ms)), encoding="utf-8"
                )
                paths.append(str(p))
            payload = {
                "report": {
                    "ok": exit_code == 0,
                    "stage": "done" if exit_code == 0 else "drive",
                    "lap_times_ms": lap_times,
                    "drive": {"recoveries": 0},
                },
                "lap_archives": paths,
                # A real alien drive records the provenance of the plant its line was built from
                # (auto_drive -> run.alien_line.plant_provenance). The ladder now treats that as
                # the only proof of WHICH plant produced a batch, so the fake must emit it too —
                # computed from the artifact as it stands at drive time, exactly like the product.
                "run": {"alien_line": {"plant_provenance": {"sha12": self._plant_fit_direct()}}},
            }
            (stage_dir / "report.json").write_text(_json.dumps(payload), encoding="utf-8")
            return exit_code

        return run


def test_selfplay_ladder_alternates_one_knob_per_iteration(monkeypatch, tmp_path):
    # #703: each iteration moves exactly ONE knob, starting with a plant step, so a verdict is
    # attributable. Iteration 1 refits and holds the scale; iteration 2 steps the rung and
    # leaves the plant alone; iteration 3 refits again at the newly validated scale.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1
            (0, [91000], [True]),  # iteration 2
            (0, [90000], [True]),  # iteration 3
        ],
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "3",
        "--scale-step",
        "0.05",
        "--max-scale",
        "1.1",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]
    selfplay = report["selfplay"]
    assert selfplay["stopped"] == "completed"
    assert selfplay["ladder_mode"] == "decoupled"
    assert selfplay["lap_trajectory_ms"] == [[95000], [93000], [91000], [90000]]
    assert selfplay["best_lap_ms"] == 90000
    kinds = [entry["step_kind"] for entry in selfplay["iterations"]]
    scales = [entry["ggv_scale"] for entry in selfplay["iterations"]]
    assert kinds == ["plant", "envelope", "plant"]
    # The plant steps hold the last VALIDATED scale (0.9 base, then 0.95 once the rung landed);
    # only the envelope step moves the rung. Exactly one knob changes per iteration.
    assert scales == [0.9, 0.95, 0.95]
    assert all(entry["valid"] for entry in selfplay["iterations"])
    # The envelope step deliberately leaves the plant alone — it never even attempts a refit.
    assert selfplay["iterations"][1]["refine_skipped"]
    assert "refine" not in selfplay["iterations"][1]
    # Each refine consumed the PREVIOUS drive's batch (provenance-bound self-play).
    assert len(harness.refine_calls) == 2
    assert harness.saves == 2
    assert harness.persist_lock_timeouts == [0.0, 0.0]
    assert selfplay["refit_iterations"] == [1, 3]
    # The plant on disk is the last refined fit (no falsification -> no revert).
    assert _json.loads(harness.plant_path.read_text(encoding="utf-8")) == {"v": "iter2"}


def test_selfplay_stops_the_529_g2_recipe_at_its_unrepeatable_rung(monkeypatch, tmp_path):
    """#746 deliberately CHANGES the recorded G2 ladder — this pins the new behaviour.

    Ladder 3 of the #529 Magione session ran ``--ggv-scale 1.0 --scale-step 0.15 --max-scale
    1.15 --iterations 2 --laps 3``; both iterations drove at the capped 1.15 rung, iteration 1's
    refit was a no-op and iteration 2's was real. #703 pinned that the decoupled ladder drives
    the same SEQUENCE, and it still does — the scales and step kinds below are unchanged.

    What changes is the verdict on iteration 2. Its real stint was ``80.791 s`` then
    ``95.122 s``: both AC-valid, zero recoveries, and a **17.7 % spread**. The pre-#746 oracle
    called that VALID and the 86.27 s-floor plant was retained on it — which is the exact defect
    this issue exists to fix. So the ladder that produced the headline G2 number would now STOP
    at that rung and revert the plant.

    That does not retract G2: ladder 2 of the same session ran ``81.505 / 81.519`` (14 ms apart,
    repeatable) and also beat the 82.7 s floor. What #746 withdraws is the *retention of a plant
    refined from an unrepeatable stint*, which is the thing that was never real.
    """
    no_op = {
        "lateral_bins_adopted": 0,
        "lateral_bins_raised": 0,
        "mu_lat_g_before": 1.5,
        "mu_lat_g_after": 1.5,
    }
    real = {
        "lateral_bins_adopted": 1,
        "lateral_bins_raised": 5,
        "mu_lat_g_before": 1.5,
        "mu_lat_g_after": 1.5,
    }
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [96286], [True]),  # base drive at 1.00
            (0, [108748, 81492, 81512], [True, True, True]),  # iteration 1
            (0, [106655, 80791, 95122], [True, True, True]),  # iteration 2
        ],
        merge_stats=[no_op, real],
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "3",
        "--iterations",
        "2",
        "--ggv-scale",
        "1.0",
        "--scale-step",
        "0.15",
        "--max-scale",
        "1.15",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]
    selfplay = report["selfplay"]
    # The SEQUENCE is unchanged (#703): both iterations at the capped 1.15 rung, envelope first.
    assert [entry["ggv_scale"] for entry in selfplay["iterations"]] == [1.15, 1.15]
    assert [entry["step_kind"] for entry in selfplay["iterations"]] == ["envelope", "plant"]
    # The VERDICT changes (#746): iteration 2's stint was 80.791 s then 95.122 s.
    assert "falsified at iteration 2" in selfplay["stopped"]
    assert "not repeatable" in selfplay["stopped"]
    assert "17.7%" in selfplay["stopped"]
    # Its refit is therefore never validated, and the plant is rolled back to the last valid fit.
    assert selfplay["refit_iterations"] == []
    assert _json.loads(harness.plant_path.read_text(encoding="utf-8")) == {"v": "original"}
    # The best lap credited is iteration 1's repeatable 81.492 s, not the unrepeatable 80.791 s.
    assert selfplay["best_lap_ms"] == 81492


def test_selfplay_falsified_envelope_rung_keeps_the_validated_refit(monkeypatch, tmp_path):
    # #703 core regression: a falsified SCALE rung must not discard the refit that a previous,
    # independently validated plant step persisted. Before decoupling, both reverted together.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive: valid
            (0, [93000], [True]),  # iteration 1: plant step, VALID -> refit persisted
            (0, [92000], [False]),  # iteration 2: envelope rung, AC-invalid lap -> falsified
        ],
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "4",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]  # the ladder ended honestly
    selfplay = report["selfplay"]
    plant_step, envelope_step = selfplay["iterations"]
    assert plant_step["step_kind"] == "plant" and plant_step["valid"] is True
    assert envelope_step["step_kind"] == "envelope" and envelope_step["valid"] is False
    # The verdict names the knob, and the retained refit is reported rather than silently lost.
    assert envelope_step["falsified_component"] == "envelope"
    assert envelope_step["plant_refit_retained"] == [1]
    assert "envelope step" in selfplay["stopped"]
    assert "AC-invalid lap" in selfplay["stopped"]
    # Nothing to revert: the envelope step never touched the artifact.
    assert "reverted" not in envelope_step
    assert harness.saves == 1
    # THE POINT OF #703 — the validated refit survives the falsified rung.
    assert _json.loads(harness.plant_path.read_text(encoding="utf-8")) == {"v": "iter1"}


def test_selfplay_falsified_step_reverts_plant_and_stops(monkeypatch, tmp_path):
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive: valid
            (0, [94000, 96000], [True, False]),  # iteration 1: AC-invalid lap -> falsified
        ],
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "2",
        "--iterations",
        "3",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]  # the base pipeline passed; the ladder ended honestly
    selfplay = report["selfplay"]
    assert "falsified at iteration 1" in selfplay["stopped"]
    assert "AC-invalid lap" in selfplay["stopped"]
    assert len(selfplay["iterations"]) == 1  # never silently retried
    entry = selfplay["iterations"][0]
    assert entry["valid"] is False and entry["reverted"] is True
    # #703: the falsified knob was the PLANT (the scale was held), so the revert — the only
    # downward path a strictly-monotone selfplay merge has — is the correct, attributed response.
    assert entry["step_kind"] == "plant"
    assert entry["falsified_component"] == "plant"
    assert "plant step (ggv_scale held at" in selfplay["stopped"]
    # Keep-last-valid: the falsified refined fit was rolled back on disk.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_unavailable_refit_falls_through_to_the_envelope_rung(monkeypatch, tmp_path):
    # #703 AC: invalid/absent refit + falsified scale. A plant step with nothing to persist has
    # no envelope of its own to test, so it spends the drive on the rung instead of re-driving an
    # identical line — and when THAT falsifies there is no refit to lose.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive: valid
            (0, [94000], [False]),  # iteration 1: falls through to the rung, then falsifies
        ],
        refine_ok=False,
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "3"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]
    selfplay = report["selfplay"]
    entry = selfplay["iterations"][0]
    assert entry["refine"]["ok"] is False  # the refit was attempted and did not land
    assert entry["fell_back_to_envelope"]
    assert entry["step_kind"] == "envelope"
    assert entry["ggv_scale"] == 0.95  # the rung moved, not the plant
    assert entry["falsified_component"] == "envelope"
    assert entry["plant_refit_retained"] == []  # no refit had landed, so none was retained
    assert harness.saves == 0
    assert "reverted" not in entry
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_revert_failure_fails_the_pipeline(monkeypatch, tmp_path):
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),
            (0, [94000], [False]),
        ],
    )

    def exploding_revert(*args, **kwargs):
        raise OSError("disk became read-only")

    import tools.ac_harness.plant_id as plant_id_mod

    monkeypatch.setattr(plant_id_mod, "revert_plant_artifact", exploding_revert)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 1 and report["ok"] is False
    assert report["selfplay"]["ok"] is False
    assert "rollback failed at iteration 1" in report["error"]
    entry = report["selfplay"]["iterations"][0]
    assert entry["reverted"] is False
    assert "disk became read-only" in entry["revert_error"]
    # The unsafe candidate remains visible in the test fixture, so a green exit is forbidden.
    assert harness.plant_path.read_text(encoding="utf-8") != '{"v": "original"}'


def test_selfplay_refuses_identical_envelope_retry(monkeypatch, tmp_path):
    # Scale already capped at the base value AND the refit failed -> the envelope cannot change;
    # driving again would retry the identical envelope, which the ladder must refuse.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[(0, [95000], [True])],
        refine_ok=False,
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "2",
        "--max-scale",
        "0.9",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    assert "envelope unchanged" in selfplay["stopped"]
    assert selfplay["iterations"][0].get("skipped") is True
    assert selfplay["iterations"][0]["refine"]["ok"] is False
    # The plant was never touched.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_base_drive_must_pass_the_oracle_to_seed_refinement(monkeypatch, tmp_path):
    # #579 Codex P1: exit 0 with an AC-invalid archived lap must NOT seed iteration 1's refit.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [False]),  # base drive: exit 0 but the archived lap is AC-invalid
            (0, [93000], [True]),  # iteration 1 drives (scale stepped), no refit batch
        ],
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    assert selfplay["base"]["valid"] is False
    assert "AC-invalid lap" in selfplay["base"]["reason"]
    assert harness.refine_calls == []  # tainted base evidence never reached the refit
    entry = selfplay["iterations"][0]
    assert entry["refine"]["reason"] == "no lap archives from the previous drive"
    assert entry["valid"] is True  # the ladder itself still ran (scale changed the envelope)
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_unattributable_base_batch_validates_nothing(monkeypatch, tmp_path):
    """#746 Codex P1, round 7: an unattributable batch may not seed refinement.

    An over-wide archive scan (more archives than timed laps) may carry a lap from another stint
    with a different tyre state, and `selfplay_refine_result` merges strictly monotonically
    (raise-only), so feeding it would raise the plant PERMANENTLY on evidence that was never
    shown to belong to this drive. The batch therefore fails the oracle outright rather than
    being carried as "valid but withheld" — but the ladder still RUNS ON, because each later
    iteration changes the envelope and is falsification-gated in its own right.
    """
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True, True]),  # base: 1 timed lap but 2 archives -> not attributable
            (0, [93000], [True]),  # iteration 1 drives; no refit batch to work from
        ],
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    # The batch validates nothing: it fails the oracle and names why.
    assert selfplay["base"]["valid"] is False
    assert "not attributable" in selfplay["base"]["reason"]
    # It never became refinement evidence, and the plant on disk is untouched.
    assert harness.refine_calls == []
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'
    # …but the ladder still ran its envelope step, which is gated on its own merits.
    assert selfplay["iterations"][0]["valid"] is True
    assert (
        selfplay["iterations"][0]["refine"]["reason"] == "no lap archives from the previous drive"
    )


def test_selfplay_noop_refit_at_scale_cap_stops_instead_of_retrying(monkeypatch, tmp_path):
    # #579 Codex P2: a refit that changes nothing + a capped scale = the identical physical
    # envelope; the ladder must stop, and the no-op fit must not even be persisted.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[(0, [95000], [True])],
        merge_stats={
            "lateral_bins_adopted": 0,
            "lateral_bins_raised": 0,
            "mu_lat_g_before": 1.5,
            "mu_lat_g_after": 1.5,
        },
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "2",
        "--max-scale",
        "0.9",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    assert "envelope unchanged" in selfplay["stopped"]
    assert selfplay["iterations"][0]["refine"]["no_op"] is True
    assert harness.saves == 0  # the no-op fit was never persisted (no provenance churn)
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_refine_save_skipped_when_peer_updates_plant(monkeypatch, tmp_path):
    # #579 Codex P2: a peer refresh between load and save must not be clobbered by a refinement
    # computed from the stale bytes.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1
        ],
        mutate_plant_during_refine=True,
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    entry = report["selfplay"]["iterations"][0]
    assert "save_skipped" in entry["refine"]
    assert harness.saves == 0
    # #703 (Codex P1): the plant on disk is now the PEER's, not the one the previous drive
    # validated. Falling through to the rung would move BOTH knobs and let a failure be blamed on
    # the envelope, destroying the attribution this decoupling exists to guarantee — so the ladder
    # stops instead of driving an unattributable step.
    assert entry["skipped"] is True
    assert "changed by a peer" in report["selfplay"]["stopped"]
    assert "exit_code" not in entry  # never drove
    assert "reverted" not in entry
    # The peer's newer artifact survived untouched.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "peer"}'


def test_selfplay_plant_step_holds_the_scale_the_base_drive_actually_used(monkeypatch, tmp_path):
    # #703 (Codex P1): --stint can drive the base stage at the Layer-4 pace scale instead of
    # --ggv-scale. A plant step holds "the last validated scale", so seeding it from --ggv-scale
    # would silently move the envelope during a plant-only iteration and misattribute its verdict.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive (ran at the stint override, not --ggv-scale)
            (0, [93000], [True]),  # iteration 1: plant step
        ],
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    runner = harness.runner()
    # Produce a real, oracle-valid base batch so iteration 1 is a genuine plant step.
    base_dir = tmp_path / "ev" / "drive"
    runner(["--evidence-dir", str(base_dir)])
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=runner,
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome=load_stage_outcome(base_dir),
        base_scale=0.8,  # the base drive really ran here; --ggv-scale defaults to 0.9
    )
    assert selfplay["base"]["valid"] is True
    assert selfplay["base_scale"] == 0.8
    # #703 (Codex P2, round 7): the rung ladder is ANCHORED to the scale actually validated, not
    # to --ggv-scale, or the first envelope step would jump two increments (0.8 -> 0.9 instead of
    # 0.85 with the 0.05 default) and skip the envelope in between.
    assert selfplay["ladder_base_scale"] == 0.8
    assert selfplay["requested_ggv_scale"] == 0.9
    entry = selfplay["iterations"][0]
    assert entry["step_kind"] == "plant"
    assert entry["ggv_scale"] == 0.8  # held at what the base drive validated, NOT 0.9


def test_selfplay_envelope_rung_never_steps_below_the_validated_base(monkeypatch, tmp_path):
    # #703: a --stint override can sit ABOVE the ladder's opening rungs. A "rung" that lowered the
    # envelope would be a knob moving the wrong way, so the ladder skips to the first rung that
    # actually exceeds the validated base scale.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),
            (0, [93000], [True]),
        ],
        refine_ok=False,  # no refit -> iteration 1 falls straight through to the rung
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "1",
        "--scale-step",
        "0.05",
        "--max-scale",
        "1.1",
    )
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=harness.runner(),
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome=None,
        base_scale=1.0,  # rungs 0.95 and 1.0 cannot raise this; the first usable rung is 1.05
    )
    entry = selfplay["iterations"][0]
    assert entry["step_kind"] == "envelope"
    assert entry["ggv_scale"] == 1.05


def test_next_envelope_rung_never_returns_a_rung_at_or_below_the_validated_scale():
    # #703 (Codex P2): --max-scale is validated only against --ggv-scale, so with --stint the
    # VALIDATED base can legally exceed the cap. A saturated candidate that does not exceed the
    # validated scale is "no rung left", not "a rung to drive downward".
    from tools.ac_harness.auto_alien import next_envelope_rung

    # Cap below the validated base -> no rung at all (never a downward step).
    assert next_envelope_rung(0.8, 0.05, 0.9, 1.0, 1) is None
    # Cap exactly at the validated base -> still no rung (must strictly exceed).
    assert next_envelope_rung(0.8, 0.05, 0.9, 0.9, 1) is None
    # Normal upward ladder.
    assert next_envelope_rung(0.9, 0.05, 1.1, 0.9, 1) == 1
    # The base drive sat above the opening rungs -> skip to the first that actually raises it.
    assert next_envelope_rung(0.9, 0.05, 1.1, 1.0, 1) == 3  # 0.95, 1.0 cannot raise 1.0; 1.05 can
    # Every returned rung strictly exceeds the validated scale.
    for prev in (0.9, 0.95, 1.0, 1.05):
        r = next_envelope_rung(0.9, 0.05, 1.1, prev, 1)
        if r is not None:
            assert iteration_scale(0.9, 0.05, r, 1.1) > prev


def test_next_envelope_rung_terminates_on_a_cap_with_more_than_six_decimals():
    # #703 (Codex P2): iteration_scale rounds to 6 decimals, so a legal cap with more decimals
    # saturates every candidate to the same rounded value. A search comparing against the
    # UNROUNDED cap would spin forever and no drive would ever start. Must terminate.
    from tools.ac_harness.auto_alien import next_envelope_rung

    assert next_envelope_rung(0.9, 0.05, 0.9000004, 0.9, 1) is None  # rounds to 0.9, cannot raise
    # And it still finds a rung when the rounded cap genuinely exceeds the validated scale.
    assert next_envelope_rung(0.9, 0.05, 0.9500004, 0.9, 1) == 1


def test_selfplay_plant_step_rejects_a_peer_replaced_candidate(monkeypatch, tmp_path):
    # #703 (Codex P1, round 3): a peer can rewrite the artifact after
    # persist_selfplay_refinement releases the rig lock but before/during the plant-step drive,
    # so auto_drive loads the PEER's plant rather than our candidate. Restricting the post-drive
    # identity check to envelope steps let the run record that refit as "validated" on a pass,
    # even though it was never the plant driven.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step, peer swaps the artifact under it
            (0, [92000], [True]),  # never reached
        ],
    )
    real_runner = harness.runner()
    calls = {"n": 0}

    def runner(argv):
        code = real_runner(argv)
        calls["n"] += 1
        if calls["n"] == 2:  # the plant step's own drive
            harness.plant_path.write_text('{"v": "peer-mid-ladder"}', encoding="utf-8")
        return code

    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "3"
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    selfplay = report["selfplay"]
    assert len(selfplay["iterations"]) == 1
    entry = selfplay["iterations"][0]
    assert entry["step_kind"] == "plant"
    assert entry["valid"] is True  # the drive passed the oracle...
    assert entry["plant_changed_during_step"] is True  # ...under a plant we did not persist
    assert entry["usable_as_evidence"] is False
    # The refit is NOT recorded as validated: it was never the plant that drove.
    assert selfplay["refit_iterations"] == []
    assert selfplay["requires_rebase"] is True
    assert "plant changed on disk during" in selfplay["stopped"]


def test_selfplay_stops_when_a_peer_changes_the_plant_before_an_envelope_step(
    monkeypatch, tmp_path
):
    # #703 (Codex P1): auto_drive loads the latest on-disk plant after taking the rig lock, so a
    # peer re-identification between the validated drive and this envelope step would move the
    # second knob silently. The verdict would not be the envelope's — stop before driving.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step (clean)
            (0, [92000], [True]),  # iteration 2: envelope step — must never drive
        ],
    )
    # Mutate strictly between iteration 1's post-drive check and iteration 2's pre-drive check —
    # the only window this guard owns. Anchored on the drive count rather than a read index, so
    # adding plant reads elsewhere cannot silently move the injection point: drive 2 is iteration
    # 1's, and the first plant read after it is iteration 1's post-drive verification (which must
    # still observe our own candidate). A peer lands immediately after that.
    real_runner = harness.runner()
    drives = {"n": 0}

    def runner(argv):
        drives["n"] += 1
        return real_runner(argv)

    real_read = auto_alien._read_plant_bytes
    reads_after_iter1_drive = {"n": 0}

    def counting_read(path):
        value = real_read(path)
        if drives["n"] == 2:
            reads_after_iter1_drive["n"] += 1
            if reads_after_iter1_drive["n"] == 1:
                harness.plant_path.write_text('{"v": "peer-between-steps"}', encoding="utf-8")
        return value

    monkeypatch.setattr(auto_alien, "_read_plant_bytes", counting_read)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "3"
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    selfplay = report["selfplay"]
    assert "plant changed on disk before" in selfplay["stopped"]
    envelope_entry = selfplay["iterations"][1]
    assert envelope_entry["step_kind"] == "envelope"
    assert envelope_entry["plant_changed_before_step"] is True
    assert "exit_code" not in envelope_entry  # refused to drive an unattributable step
    assert selfplay["requires_rebase"] is True


def test_selfplay_refuses_to_attribute_when_the_plant_moves_during_an_envelope_step(
    monkeypatch, tmp_path
):
    # #703 (Codex P1): the pre-drive check narrows the peer race but cannot close it — auto_drive
    # loads the plant after taking the rig lock, which the ladder does not hold. A step whose
    # plant moved WHILE it drove belongs to neither knob, so it must not be attributed, and a PASS
    # is no safer to build on than a failure.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step
            (0, [92000], [True]),  # iteration 2: envelope step, peer writes DURING the drive
        ],
    )
    real_runner = harness.runner()
    calls = {"n": 0}

    def runner(argv):
        calls["n"] += 1
        code = real_runner(argv)
        if calls["n"] == 3:  # mid-flight during the envelope step's own drive
            harness.plant_path.write_text('{"v": "peer-during-drive"}', encoding="utf-8")
        return code

    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "3"
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    selfplay = report["selfplay"]
    envelope_entry = selfplay["iterations"][1]
    assert envelope_entry["step_kind"] == "envelope"
    assert envelope_entry["valid"] is True  # the drive itself passed...
    assert (
        envelope_entry["plant_changed_during_step"] is True
    )  # ...but under a plant we did not pick
    assert "plant changed on disk during" in selfplay["stopped"]
    # The pass is NOT carried forward as ladder evidence.
    assert len(selfplay["iterations"]) == 2
    # ...and it is barred from seeding a setup experiment (#703 Codex P1, round 3): the scientist
    # would otherwise pick this newest "valid" batch as its baseline. Selection falls back to the
    # earlier attributable iteration instead of the tainted one.
    assert envelope_entry["usable_as_evidence"] is False
    assert selfplay["requires_rebase"] is True
    baseline = auto_alien._scientist_baseline_outcome(selfplay, None)
    assert baseline is not None
    archives = baseline["lap_archives"]
    tainted = envelope_entry["evidence_dir"]
    attributable = selfplay["iterations"][0]["evidence_dir"]
    assert not any(tainted in p for p in archives)
    assert any(attributable in p for p in archives)
    # Belt and braces: `requires_rebase` also stops the scientist stage running at all, because
    # even an attributable baseline would be compared against drives on the PEER's plant.


def test_scientist_is_skipped_when_the_ladder_needs_a_peer_rebase(monkeypatch, tmp_path):
    # #703 (Codex P1, round 3): a peer-change stop leaves selfplay.ok true, so run_pipeline would
    # still run the scientist — comparing a baseline captured under the OLD plant against
    # experiment drives that load the PEER's plant. That changes setup AND plant at once and can
    # persist a corrupted verdict. The stage must be skipped until a fresh run rebases.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000, 96000], [True, True]),  # base drive
            (0, [93000, 94000], [True, True]),  # iteration 1: peer swaps between load and save
        ],
        mutate_plant_during_refine=True,  # forces the peer save_skipped path
    )
    called = {"scientist": False}
    monkeypatch.setattr(
        auto_alien,
        "run_scientist",
        lambda *a, **kw: called.__setitem__("scientist", True) or {"ok": True},
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "2",
        "--iterations",
        "1",
        "--setup",
        "Copilot_Balanced_Fast",
        "--scientist",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    assert report["selfplay"]["requires_rebase"] is True
    assert called["scientist"] is False  # never ran across two different plants
    assert "re-run to rebase" in report["scientist"]["skipped"]
    # Qodo: the skip status is observable report behaviour, so pin it — otherwise the field could
    # be renamed or dropped and telemetry would silently read the skip as a successful run.
    assert report["scientist"]["status"] == "skipped_requires_rebase"
    assert report["scientist"]["ok"] is True  # skipping is the right outcome, not a stage failure


def test_next_envelope_rung_survives_a_scale_step_that_overflows_the_division():
    # #703 (Codex P2, round 4): --scale-step is validated only as finite and > 0, so a legal but
    # absurd 1e-320 makes (target - base) / step overflow and math.ceil raise OverflowError,
    # crashing the pipeline BEFORE it can write its composed report. Must degrade, not crash.
    from tools.ac_harness.auto_alien import next_envelope_rung

    assert next_envelope_rung(0.9, 1e-320, 1.1, 0.9, 1) is None  # no reachable rung, no crash


def test_selfplay_unattributable_lap_is_not_reported_as_the_best(monkeypatch, tmp_path):
    # #703 (Codex P2, round 4): a fast lap set while a peer's plant was on disk must not become
    # this ladder's best_lap_ms — the batch is explicitly marked unusable in the same breath.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [40000], [True]),  # iteration 1: implausibly fast, under a swapped plant
        ],
    )
    real_runner = harness.runner()
    calls = {"n": 0}

    def runner(argv):
        code = real_runner(argv)
        calls["n"] += 1
        if calls["n"] == 2:
            harness.plant_path.write_text('{"v": "peer"}', encoding="utf-8")
        return code

    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    selfplay = report["selfplay"]
    assert selfplay["iterations"][0]["plant_changed_during_step"] is True
    # 95000 is the base drive's lap; the 40000 set under the peer's plant is rejected.
    assert selfplay["best_lap_ms"] == 95000


def test_selfplay_failed_unattributable_step_also_requires_a_rebase(monkeypatch, tmp_path):
    # #703 (Codex P1, round 4): round 3 set requires_rebase only on the PASS path, so a peer
    # change during an oracle-INVALID drive still let the scientist run across two plants.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000, 96000], [True, True]),  # base drive
            (0, [94000], [False]),  # iteration 1: AC-invalid AND the plant is swapped under it
        ],
    )
    real_runner = harness.runner()
    calls = {"n": 0}

    def runner(argv):
        code = real_runner(argv)
        calls["n"] += 1
        if calls["n"] == 2:
            harness.plant_path.write_text('{"v": "peer"}', encoding="utf-8")
        return code

    called = {"scientist": False}
    monkeypatch.setattr(
        auto_alien,
        "run_scientist",
        lambda *a, **kw: called.__setitem__("scientist", True) or {"ok": True},
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "2",
        "--iterations",
        "1",
        "--setup",
        "Copilot_Balanced_Fast",
        "--scientist",
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    entry = report["selfplay"]["iterations"][0]
    assert entry["valid"] is False
    assert entry["falsified_component"] == "unattributable"
    assert entry["usable_as_evidence"] is False
    assert report["selfplay"]["requires_rebase"] is True
    assert called["scientist"] is False  # the failed path gates the scientist too
    # #703 (Codex P2, round 5): the headline diagnostic must name the kind that actually ran —
    # claiming "envelope step" on a falsified PLANT step contradicts entry["step_kind"] exactly
    # where the decoupled ladder is supposed to identify the knob.
    assert entry["step_kind"] == "plant"
    assert "during this plant step" in report["selfplay"]["stopped"]


def test_next_envelope_rung_does_not_jump_a_subnormal_step_to_the_cap():
    # #703 (Codex P2, round 5): a saturating fallback "finds" a rung for a subnormal step whose
    # float product cannot move off `base` at all, and the first envelope drive would then leap
    # straight to --max-scale — turning an almost-zero requested step into an immediate jump to
    # the safety cap. A step that cannot move the envelope means the ladder is exhausted.
    from tools.ac_harness.auto_alien import next_envelope_rung

    assert next_envelope_rung(0.9, 2e-309, 1.1, 0.9, 1) is None
    # A LEGITIMATE saturation on the first rung is still honoured (0.9 + 0.15 -> capped at 1.0).
    assert next_envelope_rung(0.9, 0.15, 1.0, 0.9, 1) == 1
    assert iteration_scale(0.9, 0.15, 1, 1.0) == 1.0


def test_selfplay_stops_when_the_plant_changed_since_the_base_drive(monkeypatch, tmp_path):
    # #703 (Codex P1, round 5): the bytes on disk are not self-evidently what the BASE drive ran.
    # A peer can re-identify the combo after the base stage and before the ladder snapshots it;
    # adopting those bytes unchecked would let the first fallback envelope step pass the byte
    # check while driving a different plant AND a higher scale. auto_drive records the fit its
    # line was built from, so the two must agree before the snapshot counts as validated.
    harness = _SelfplayHarness(monkeypatch, tmp_path, stage_specs=[(0, [95000], [True])])
    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", lambda outcome: "basefit000000")
    monkeypatch.setattr(auto_alien, "_fit_sha12_of_artifact", lambda art: "peerfit000000")
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=harness.runner(),
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome={"report": {"lap_times_ms": [95000]}, "lap_archives": []},
    )
    assert selfplay["requires_rebase"] is True
    assert selfplay["iterations"] == []  # stopped before iteration 1; nothing was driven
    assert "plant changed since the base drive" in selfplay["stopped"]
    assert "basefit000000" in selfplay["stopped"]
    assert "peerfit000000" in selfplay["stopped"]


def test_selfplay_refuses_to_refine_across_two_fits(monkeypatch, tmp_path):
    # #703 (Codex P1, round 6): a peer can re-identify the combo after the previous drive's plant
    # check but before the refit snapshots the artifact. `expected_current_bytes` would accept
    # those bytes happily — it only prevents clobbering a NEWER fit, it does not prove the fit is
    # ours — so plant A's archives would be merged into peer plant B, and the candidate would then
    # become `validated_plant_bytes`, laundering a two-plant transition into a single-knob refit.
    # The window opens at a LATER plant step: at iteration 1 the ladder-start snapshot and the
    # refit read are adjacent, so a peer change before iteration 1 is round 5's gate, not this
    # one. Iteration 3 is the next plant step, and the window is between iteration 2's post-drive
    # check and iteration 3's pre-refit read.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step
            (0, [92000], [True]),  # iteration 2: envelope step
            # iteration 3 (plant step) must never drive
        ],
    )
    real_runner = harness.runner()
    drives = {"n": 0}

    def runner(argv):
        drives["n"] += 1
        return real_runner(argv)

    real_read = auto_alien._read_plant_bytes
    reads_after_iter2_drive = {"n": 0}

    def counting_read(path):
        value = real_read(path)
        if drives["n"] == 3:  # iteration 2's drive is done
            reads_after_iter2_drive["n"] += 1
            if reads_after_iter2_drive["n"] == 1:  # its post-drive check just saw a clean plant
                harness.plant_path.write_text('{"v": "peer-before-refit"}', encoding="utf-8")
        return value

    monkeypatch.setattr(auto_alien, "_read_plant_bytes", counting_read)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "4"
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    selfplay = report["selfplay"]
    entry = selfplay["iterations"][2]  # iteration 3, the next plant step
    assert entry["step_kind"] == "plant"
    assert entry["skipped"] is True
    assert "refusing to merge" in entry["refine"]["reason"]
    assert "plant changed before iteration 3's refit" in selfplay["stopped"]
    assert selfplay["requires_rebase"] is True
    assert harness.saves == 1  # only iteration 1's refit; nothing merged across the two fits
    assert "exit_code" not in entry  # never drove
    # The peer's artifact is untouched.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "peer-before-refit"}'


def test_selfplay_fails_closed_when_the_current_plant_is_unreadable(monkeypatch, tmp_path):
    # #703 (Codex P2, round 6): if the artifact is deleted or corrupted after a successful base
    # drive, base_fit stays populated while current_fit becomes None. Treating that as
    # "compatible" let the refit fail, fall through to an envelope drive, and report the
    # plant-load failure as falsifying the SCALE RUNG while the bad artifact stayed in place.
    harness = _SelfplayHarness(monkeypatch, tmp_path, stage_specs=[(0, [95000], [True])])
    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", lambda outcome: "basefit000000")
    monkeypatch.setattr(auto_alien, "_fit_sha12_of_artifact", lambda art: None)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=harness.runner(),
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome={"report": {"lap_times_ms": [95000]}, "lap_archives": []},
    )
    assert selfplay["requires_rebase"] is True
    assert selfplay["iterations"] == []  # never drove an envelope rung on a broken plant
    assert "no readable plant fit" in selfplay["stopped"]


def test_selfplay_trusts_the_drive_recorded_fit_over_the_bytes_on_disk(monkeypatch, tmp_path):
    # #703 (Codex P2, round 7): bytes-after-the-drive are necessary but not sufficient. A peer can
    # replace the plant before auto_drive loads it and restore the expected bytes right after the
    # rig lock releases — the byte comparison then passes while the iteration actually ran a
    # different fit. The drive REPORTS the provenance of the plant its line was built from, so
    # that report must win over inference from the artifact's bytes.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: bytes look right, provenance says otherwise
        ],
    )
    # The bytes on disk are never disturbed, so only the recorded provenance can catch this.
    # The BASE must agree (that is round 5's gate); only iteration 1's drive reports a foreign fit.
    monkeypatch.setattr(auto_alien, "_fit_sha12_of_artifact", lambda art: "expectedfit0")

    reads = {"n": 0}

    def fake_stage_fit(outcome):
        reads["n"] += 1
        return "expectedfit0" if reads["n"] == 1 else "someoneelsefit"

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", fake_stage_fit)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    entry = selfplay["iterations"][0]
    assert entry["valid"] is True  # the drive passed the oracle...
    assert entry["driven_plant_fit_mismatch"] == {
        "expected": "expectedfit0",
        "driven": "someoneelsefit",
    }
    assert entry["plant_changed_during_step"] is True  # ...on a plant we did not choose
    assert entry["usable_as_evidence"] is False
    assert selfplay["requires_rebase"] is True
    assert selfplay["refit_iterations"] == []  # the refit is NOT recorded as validated


def test_selfplay_valid_batch_without_recorded_provenance_is_unusable(monkeypatch, tmp_path):
    # #703 (Qodo, round 8): fail closed on MISSING proof, not only on contradicted proof. Byte
    # equality cannot show which plant was driven — a peer swap restored before the post-drive
    # read looks identical — so an oracle-valid batch with no recorded provenance must not seed
    # refinement or the scientist baseline.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: passes the oracle, records no provenance
        ],
    )
    calls = {"n": 0}
    real_stage_fit = auto_alien.stage_plant_fit_sha12

    def fit_missing_after_base(outcome):
        calls["n"] += 1
        return real_stage_fit(outcome) if calls["n"] == 1 else None

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", fit_missing_after_base)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    entry = selfplay["iterations"][0]
    assert entry["valid"] is True  # the oracle passed it...
    assert entry["driven_plant_fit_missing"]  # ...but which plant produced it is unprovable
    assert entry["usable_as_evidence"] is False
    assert selfplay["requires_rebase"] is True
    assert selfplay["refit_iterations"] == []


def test_selfplay_invalid_drive_without_provenance_is_still_attributed(monkeypatch, tmp_path):
    # The complement, and why the rule above is scoped to VALID iterations: a drive that died
    # before building a line legitimately records no provenance. That is an ordinary stage
    # failure, not a peer plant change, and must keep its knob attribution instead of demanding
    # a rebase.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (3, [], []),  # iteration 1: stage failed outright
        ],
    )
    calls = {"n": 0}
    real_stage_fit = auto_alien.stage_plant_fit_sha12

    def fit_missing_after_base(outcome):
        calls["n"] += 1
        return real_stage_fit(outcome) if calls["n"] == 1 else None

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", fit_missing_after_base)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    entry = selfplay["iterations"][0]
    assert entry["valid"] is False
    assert "driven_plant_fit_missing" not in entry
    assert entry["falsified_component"] == "plant"  # attributed, not laundered to unattributable
    assert selfplay.get("requires_rebase") is not True


def test_selfplay_reverts_a_candidate_that_never_drove_on_its_own_plant(monkeypatch, tmp_path):
    # #703 (Codex P1, round 8): when a plant step's drive reports a different fit than the
    # candidate we persisted, that candidate has survived nothing. Stopping and excluding the
    # batch is not enough — the monotone merge only ever RAISES grip and this revert is its one
    # way down, so leaving it persisted hands an unvalidated grip increase to every later
    # alien-line consumer.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step, drive reports a foreign fit
        ],
    )
    calls = {"n": 0}
    real_stage_fit = auto_alien.stage_plant_fit_sha12

    def foreign_fit_after_base(outcome):
        calls["n"] += 1
        return real_stage_fit(outcome) if calls["n"] == 1 else "someoneelsefit"

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", foreign_fit_after_base)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    entry = report["selfplay"]["iterations"][0]
    assert entry["driven_plant_fit_mismatch"]["driven"] == "someoneelsefit"
    assert entry["reverted"] is True
    assert report["selfplay"]["requires_rebase"] is True
    # THE POINT: the undriven candidate is gone from disk, not left for later consumers.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_skipped_rollback_requires_a_rebase(monkeypatch, tmp_path):
    # #703 (Codex P1, round 8 — review BODY, not an inline thread): a skipped rollback PROVES the
    # on-disk plant is no longer this ladder's, so it must set the same rebase state every other
    # detected peer change does, or --scientist runs a baseline from an older self-play outcome
    # against experiments loading the peer's plant.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000, 96000], [True, True]),  # base drive
            (0, [94000], [False]),  # iteration 1: falsified, and a peer owns the artifact by then
        ],
    )
    real_runner = harness.runner()
    drives = {"n": 0}

    def runner(argv):
        drives["n"] += 1
        code = real_runner(argv)
        if drives["n"] == 2:  # peer replaces the candidate before the revert can run
            harness.plant_path.write_text('{"v": "peer-owns-it"}', encoding="utf-8")
        return code

    called = {"scientist": False}
    monkeypatch.setattr(
        auto_alien,
        "run_scientist",
        lambda *a, **kw: called.__setitem__("scientist", True) or {"ok": True},
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "2",
        "--iterations",
        "1",
        "--setup",
        "Copilot_Balanced_Fast",
        "--scientist",
    )
    code, report = run_pipeline(args, run_stage=runner)
    assert code == 0
    entry = report["selfplay"]["iterations"][0]
    assert entry["reverted"] is False
    assert "revert skipped" in entry["revert_skipped"]
    assert entry["usable_as_evidence"] is False
    assert report["selfplay"]["requires_rebase"] is True
    assert called["scientist"] is False
    # The peer's artifact was never overwritten by our rollback.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "peer-owns-it"}'


def test_selfplay_ladder_rungs_step_from_the_validated_base_not_the_flag(monkeypatch, tmp_path):
    # #703 (Codex P2, round 7): with --stint derating the base below --ggv-scale, anchoring the
    # rungs to the flag made the first envelope step jump TWO increments and skip the envelope in
    # between, so a run could falsify at 0.95 having never tested 0.90.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive at the derated stint pace
            (0, [94000], [True]),  # iteration 1: no refit batch -> falls through to the rung
        ],
        refine_ok=False,
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "1",
        "--scale-step",
        "0.05",
        "--max-scale",
        "1.1",
    )
    runner = harness.runner()
    base_dir = tmp_path / "ev" / "drive"
    runner(["--evidence-dir", str(base_dir)])
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=runner,
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome=load_stage_outcome(base_dir),
        base_scale=0.85,  # the Layer-4 stint pace; --ggv-scale defaults to 0.9
    )
    # One requested increment above what the base actually validated — not 0.95.
    assert selfplay["iterations"][0]["ggv_scale"] == 0.9
    assert selfplay["ladder_base_scale"] == 0.85


def test_selfplay_unproven_base_archives_do_not_seed_a_refit(monkeypatch, tmp_path):
    # #703 (Codex P2, round 8): an oracle-valid base whose report carries no plant provenance is
    # the explicitly supported older-report case, so the ladder still RUNS — envelope rungs are
    # falsification-gated on their own. But its archives may not seed a refit: with no recorded
    # provenance there is no proof the plant now on disk is the fit that produced them, so a peer
    # replacement between that drive and this invocation would cross two fits inside the
    # refinement evidence itself.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive: oracle-valid, no provenance
            (0, [94000], [True]),  # iteration 1: must be an envelope step, not a refit
        ],
    )
    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", lambda outcome: None)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    assert selfplay["base"]["valid"] is True  # still good pace evidence...
    assert selfplay["base_plant_fit_unverified"] is True
    assert "refit_evidence_withheld" in selfplay["base"]  # ...but not refit evidence
    assert harness.refine_calls == []  # nothing was merged from an unprovable batch
    entry = selfplay["iterations"][0]
    assert entry["step_kind"] == "envelope"  # the ladder still ran
    assert entry["refine"]["reason"] == "no lap archives from the previous drive"


def test_unreadable_plant_is_not_treated_as_a_peer_change(monkeypatch, tmp_path):
    # Self-hosted reviewer HIGH: `_read_plant_bytes` swallowed every OSError into None, so a
    # transient read failure was indistinguishable from "the bytes changed" at each comparison.
    # A blip after a successful plant step then tripped keep-last-valid and DROPPED a
    # provenance-validated refit, while reporting an I/O fault as peer re-identification with
    # selfplay.ok still true. Absent and unreadable are different facts.
    from tools.ac_harness.auto_alien import _read_plant_bytes

    missing = tmp_path / "gone.json"
    assert _read_plant_bytes(missing) is None  # absent -> None, as before

    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{}", encoding="utf-8")

    def boom(*a, **kw):
        raise OSError("disk on fire")

    monkeypatch.setattr(type(unreadable), "read_bytes", boom)
    with pytest.raises(OSError, match="disk on fire"):
        _read_plant_bytes(unreadable)  # unreadable -> raises, never a silent "changed"


def test_selfplay_stops_loudly_when_the_plant_becomes_unreadable(monkeypatch, tmp_path):
    # The same defect end-to-end: a post-drive read failure must fail the pipeline (ok False),
    # NOT revert the refit and report a peer rebase.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: plant step, read fails right after the drive
        ],
    )
    real_read = auto_alien._read_plant_bytes
    drives = {"n": 0}
    real_runner = harness.runner()

    def runner(argv):
        drives["n"] += 1
        return real_runner(argv)

    def read_or_explode(path):
        if drives["n"] == 2:  # after iteration 1's drive
            raise OSError("disk on fire")
        return real_read(path)

    monkeypatch.setattr(auto_alien, "_read_plant_bytes", read_or_explode)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=runner)
    selfplay = report["selfplay"]
    assert selfplay["ok"] is False and code == 1  # fails closed, like the #579 filesystem path
    assert "cannot read the plant artifact" in selfplay["stopped"]
    assert "not evidence that it changed" in selfplay["stopped"]
    entry = selfplay["iterations"][0]
    assert "reverted" not in entry  # the validated refit was NOT dropped on an I/O blip
    assert selfplay.get("requires_rebase") is not True  # nor laundered into a peer rebase


def test_unproven_base_is_not_offered_as_a_scientist_baseline(tmp_path):
    # Qodo: withholding the unprovable base from REFITTING is not enough — the scientist falls
    # back to the base outcome when no attributable iteration exists, which would compare an
    # unproven baseline against candidates driven on the current plant.
    base_outcome = {"report": {"lap_times_ms": [95000]}, "lap_archives": []}
    unproven = {
        "iterations": [],
        "base": {"valid": True},  # oracle-valid, so it WOULD be the fallback...
        "base_plant_fit_unverified": True,  # ...but its plant is unprovable
    }
    assert auto_alien._scientist_baseline_outcome(unproven, base_outcome) is None
    # The same oracle-valid base WITH recorded provenance is still a legitimate fallback.
    proven = {"iterations": [], "base": {"valid": True}}
    assert auto_alien._scientist_baseline_outcome(proven, base_outcome) is base_outcome


def test_next_envelope_rung_crosses_a_wide_rounding_plateau():
    # #703 (Codex P2, round 12): a fixed three-probe window past the algebraic candidate wrongly
    # reported an exhausted ladder when the plateau is wider than two indices. Binary search finds
    # the exact smallest usable rung instead.
    from tools.ac_harness.auto_alien import next_envelope_rung

    rung = next_envelope_rung(0.9, 2e-17, 0.91, 0.9, 1)
    assert rung is not None, "a usable rung exists past the plateau; must not report exhausted"
    assert iteration_scale(0.9, 2e-17, rung, 0.91) > 0.9
    # ...and it is the SMALLEST such rung, not a leap to the cap.
    assert iteration_scale(0.9, 2e-17, rung - 1, 0.91) <= 0.9
    # A step that genuinely cannot move the envelope at all still reports exhausted (round 5).
    assert next_envelope_rung(0.9, 2e-309, 1.1, 0.9, 1) is None


def test_selfplay_reverts_a_falsified_refit_when_the_post_drive_read_fails(monkeypatch, tmp_path):
    # #703 (Codex P1 + Qodo + self-hosted HIGH, round 12): the new post-drive read guard sits
    # BEFORE the keep-last-valid block, so breaking on an OSError skipped the rollback and left a
    # falsified monotone grip increase as the combo's loadable plant. Only an oracle-VALID step is
    # protected from an I/O blip; a falsified one must still be rolled back.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [94000], [False]),  # iteration 1: refit persisted, then AC-invalid lap
        ],
    )
    real_read = auto_alien._read_plant_bytes
    drives = {"n": 0}
    real_runner = harness.runner()

    def runner(argv):
        drives["n"] += 1
        return real_runner(argv)

    def read_or_explode(path):
        if drives["n"] == 2:  # the post-drive read for the falsified plant step
            raise OSError("disk on fire")
        return real_read(path)

    monkeypatch.setattr(auto_alien, "_read_plant_bytes", read_or_explode)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=runner)
    selfplay = report["selfplay"]
    assert selfplay["ok"] is False and code == 1  # still fails closed
    entry = selfplay["iterations"][0]
    assert entry["valid"] is False
    assert entry["reverted"] is True
    # THE POINT: the rejected higher-grip candidate is not left for future alien runs.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_selfplay_refuses_to_start_without_a_valid_plant(monkeypatch, tmp_path):
    # #703 (Codex P2, round 12): with no valid on-disk artifact the ladder used to run anyway —
    # the refit reported "unloadable", fell through to an envelope rung, and that drive's
    # plant-load failure was reported as falsifying the SCALE, on a pipeline that could exit 0.
    harness = _SelfplayHarness(monkeypatch, tmp_path, stage_specs=[(0, [95000], [True])])
    monkeypatch.setattr(auto_alien, "plant_artifact_from_bytes", lambda *a, **kw: None)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    selfplay = auto_alien.run_selfplay(
        args,
        run_stage=harness.runner(),
        evidence_root=tmp_path / "ev",
        user_dir=tmp_path,
        setup_key=None,
        setup_ini=None,
        base_outcome={"report": {"lap_times_ms": [95000]}, "lap_archives": []},
    )
    assert selfplay["ok"] is False
    assert selfplay["iterations"] == []  # never drove a rung without a plant
    assert "no valid plant artifact" in selfplay["stopped"]


def test_invalid_timed_lap_without_provenance_is_unattributable(monkeypatch, tmp_path):
    # #703 (Qodo, round 14): scoping the missing-provenance rule to VALID iterations let an
    # AC-invalid TIMED lap with no provenance keep its knob attribution, so an envelope failure
    # could retain earlier refits with no proof the expected plant produced the falsifying lap.
    # A drive that produced laps DID run; only one that died before building a line is exempt.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [94000], [False]),  # iteration 1: drove, AC-invalid lap, no provenance recorded
        ],
    )
    calls = {"n": 0}
    real_stage_fit = auto_alien.stage_plant_fit_sha12

    def fit_missing_after_base(outcome):
        calls["n"] += 1
        return real_stage_fit(outcome) if calls["n"] == 1 else None

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", fit_missing_after_base)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    entry = report["selfplay"]["iterations"][0]
    assert entry["valid"] is False
    assert entry["driven_plant_fit_missing"]
    assert entry["falsified_component"] == "unattributable"  # not blamed on the selected knob
    assert report["selfplay"]["requires_rebase"] is True


def test_undriven_candidate_is_reverted_even_when_the_post_drive_read_fails(monkeypatch, tmp_path):
    # #703 (self-hosted HIGH, round 14): round 12 extended the OSError path only to oracle-INVALID
    # batches. A VALID drive on a foreign fit followed by a read failure therefore failed the
    # pipeline without reverting, leaving the undriven monotone grip raise loadable for later runs.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1: passes the oracle, but on a foreign fit
        ],
    )
    calls = {"n": 0}
    real_stage_fit = auto_alien.stage_plant_fit_sha12

    def foreign_fit_after_base(outcome):
        calls["n"] += 1
        return real_stage_fit(outcome) if calls["n"] == 1 else "someoneelsefit"

    monkeypatch.setattr(auto_alien, "stage_plant_fit_sha12", foreign_fit_after_base)

    real_read = auto_alien._read_plant_bytes
    drives = {"n": 0}
    real_runner = harness.runner()

    def runner(argv):
        drives["n"] += 1
        return real_runner(argv)

    def read_or_explode(path):
        if drives["n"] == 2:  # the post-drive read for iteration 1
            raise OSError("disk on fire")
        return real_read(path)

    monkeypatch.setattr(auto_alien, "_read_plant_bytes", read_or_explode)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=runner)
    selfplay = report["selfplay"]
    assert selfplay["ok"] is False and code == 1  # still fails closed on the I/O fault
    entry = selfplay["iterations"][0]
    assert entry["valid"] is True  # the oracle passed it...
    assert entry["plant_changed_during_step"] is True  # ...on a plant we did not choose
    assert entry["usable_as_evidence"] is False
    assert selfplay["requires_rebase"] is True
    assert entry["reverted"] is True
    # THE POINT: the undriven grip raise is gone, not left loadable behind an I/O error.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "original"}'


def test_stage_plant_fit_sha12_reads_the_recorded_line_provenance():
    # The ladder's proof of WHICH plant produced a batch. Shape matches auto_drive's report.
    outcome = {"run": {"alien_line": {"plant_provenance": {"sha12": "51fcee4af59a"}}}}
    assert auto_alien.stage_plant_fit_sha12(outcome) == "51fcee4af59a"
    assert auto_alien.stage_plant_fit_sha12({"run": {"alien_line": {}}}) is None
    assert auto_alien.stage_plant_fit_sha12(None) is None


def test_next_envelope_rung_crosses_a_rounding_plateau():
    # #703 (Codex P2, round 3): with a tiny --scale-step the six-decimal rounding leaves several
    # consecutive rungs on the same value. A closed form that ignores the rounding threshold
    # lands inside the plateau and wrongly reports the ladder exhausted while many rungs remain.
    from tools.ac_harness.auto_alien import next_envelope_rung

    rung = next_envelope_rung(0.9, 1e-7, 0.91, 0.9, 1)
    assert rung is not None, "rungs exist past the plateau; must not report the ladder exhausted"
    assert iteration_scale(0.9, 1e-7, rung, 0.91) > 0.9


def test_selfplay_reports_an_inherited_refit_as_retained(monkeypatch, tmp_path):
    # #703 (Codex P2): the refit compounds ACROSS invocations. A run whose own plant step is a
    # no-op still protects the inherited fit, so reporting "nothing was retained" would be false
    # in exactly the cross-invocation case this change exists to expose.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [94000], [False]),  # iteration 1: no-op refit -> rung -> falsified
        ],
        merge_stats={
            "lateral_bins_adopted": 0,
            "lateral_bins_raised": 0,
            "mu_lat_g_before": 1.5,
            "mu_lat_g_after": 1.5,
        },
    )
    # The plant already carries two self-play merges from earlier invocations.
    # Patch the COUNT rather than the artifact: overriding the parse gate here would also
    # change the artifact's provenance hash and trip the base-fit gate, which is not what this
    # test is about.
    monkeypatch.setattr(auto_alien, "artifact_selfplay_merge_count", lambda artifact: 2)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0
    selfplay = report["selfplay"]
    assert selfplay["inherited_selfplay_merges"] == 2
    entry = selfplay["iterations"][0]
    assert entry["falsified_component"] == "envelope"
    assert entry["plant_refit_retained"] == []  # none landed THIS run...
    assert entry["inherited_selfplay_merges"] == 2  # ...but the inherited fit is still protected


def test_selfplay_oracle_ignores_foreign_combo_archives(monkeypatch, tmp_path):
    # #579 Codex P2: another app/combo's archive must neither satisfy nor poison the batch.
    from tools.ac_harness.auto_alien import combo_filter_payloads

    own = _archive_payload(1)
    foreign = _archive_payload(1, car="other_car", track="other_trk")
    kept, dropped = combo_filter_payloads(
        [own, foreign], car_id="car_a", track_id="trk", layout=None
    )
    assert kept == [own] and dropped == 1


def test_selfplay_filesystem_error_stops_with_named_reason(monkeypatch, tmp_path):
    # #579 Qodo reliability: an OSError during the refine persist must surface as an honest
    # selfplay.stopped reason in the composed report, never crash the pipeline.
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
        ],
    )

    # Since #703 the refit no longer takes its own read — one snapshot serves the compare, the
    # parse and the write — so patching `Path.read_bytes` would now fail the ladder-start
    # provenance gate instead of the refine persist. Raise from the persist itself, which is the
    # artifact I/O this guard actually exists to survive.
    import tools.ac_harness.plant_id as plant_id_mod

    def exploding_persist(*a, **kw):
        raise OSError("disk on fire")

    monkeypatch.setattr(plant_id_mod, "persist_selfplay_refinement", exploding_persist)
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "2"
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 1 and report["ok"] is False
    selfplay = report["selfplay"]
    assert selfplay["ok"] is False
    assert "filesystem error at iteration 1" in selfplay["stopped"]
    assert "disk on fire" in selfplay["iterations"][0]["refine"]["reason"]


def test_selfplay_late_persist_error_cannot_return_green(monkeypatch, tmp_path):
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[(0, [95000], [True])],
        persist_error_after_write=True,
    )
    args = _args(
        tmp_path, "--evidence-dir", str(tmp_path / "ev"), "--laps", "1", "--iterations", "1"
    )

    code, report = run_pipeline(args, run_stage=harness.runner())

    assert code == 1 and report["ok"] is False
    assert report["selfplay"]["ok"] is False
    assert "late candidate read failed" in report["error"]
    # The candidate may already be on disk, so returning success would expose an unverified plant.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "iter1"}'


@pytest.mark.parametrize(
    ("baseline_laps", "candidate_laps", "expected_error"),
    [
        (((1, 100_000), (2, 101_000)), ((1, 90_000), (2, 91_000)), None),
        (((1, 100_000), (2, 101_000)), ((1, 90_000),), "candidate_batch_incomplete"),
        (((1, 100_000),), ((1, 90_000), (2, 91_000)), "baseline_batch_unverifiable"),
    ],
)
def test_scientist_requires_requested_laps_before_persisting(
    monkeypatch, tmp_path, baseline_laps, candidate_laps, expected_error
):
    from tools.ai_sidecar import car_schema
    from tools.ai_sidecar.car_schema import CarSetupSchema

    user_dir = tmp_path / "Assetto Corsa"
    baseline_setup = user_dir / "setups" / "car_a" / "trk" / "baseline.ini"
    baseline_setup.parent.mkdir(parents=True)
    baseline_setup.write_text("[WING_2]\nVALUE=10\n\n[FRONT_BIAS]\nVALUE=60\n", encoding="utf-8")
    schema = CarSetupSchema.from_spinners_dump(
        "car_a",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1},
            {"name": "FRONT_BIAS", "min": 50, "max": 70, "step": 1},
        ],
    )
    monkeypatch.setattr(car_schema, "load_latest_schema", lambda car: schema)

    def lap_payload(lap_n: int, lap_ms: int, *, wing: int, path: Path) -> dict:
        return {
            "schema_version": 1,
            "lap_uuid": f"lap-{wing}-{lap_n}",
            "session_uuid": f"session-{wing}",
            "exported_at": f"2026-07-22T00:00:0{lap_n}Z",
            "car": {"id": "car_a"},
            "track": {"id": "trk", "layout": None},
            "lap": {"lap_n": lap_n, "lap_ms": lap_ms, "is_valid": True},
            "setup": {
                "hash": f"setup-{wing}",
                "path": str(path),
                "snapshot": {"WING_2.VALUE": wing, "FRONT_BIAS.VALUE": 60},
            },
        }

    baseline_paths = []
    for lap_n, lap_ms in baseline_laps:
        path = tmp_path / f"baseline_lap_{lap_n}.json"
        path.write_text(
            _json.dumps(lap_payload(lap_n, lap_ms, wing=10, path=baseline_setup)),
            encoding="utf-8",
        )
        baseline_paths.append(str(path))
    base_outcome = {
        "report": {
            "lap_times_ms": [lap_ms for _, lap_ms in baseline_laps],
            "drive": {"recoveries": 0},
        },
        "lap_archives": baseline_paths,
    }

    nested_calls = []

    def fake_nested_pipeline(candidate_args, *, run_stage):
        del run_stage
        nested_calls.append(candidate_args)
        drive_dir = Path(candidate_args.evidence_dir) / "drive"
        drive_dir.mkdir(parents=True)
        paths = []
        for lap_n, lap_ms in candidate_laps:
            path = drive_dir / f"lap_{lap_n}.json"
            path.write_text(
                _json.dumps(lap_payload(lap_n, lap_ms, wing=9, path=Path(candidate_args.setup))),
                encoding="utf-8",
            )
            paths.append(str(path))
        (drive_dir / "report.json").write_text(
            _json.dumps(
                {
                    "report": {
                        "lap_times_ms": [lap_ms for _, lap_ms in candidate_laps],
                        "drive": {"recoveries": 0},
                    },
                    "lap_archives": paths,
                }
            ),
            encoding="utf-8",
        )
        return 0, {
            "stages": {"drive": {"evidence_dir": str(drive_dir)}},
            "ok": True,
        }

    monkeypatch.setattr(auto_alien, "run_pipeline", fake_nested_pipeline)
    args = _args(
        user_dir,
        "--setup",
        str(baseline_setup),
        "--laps",
        "2",
        "--iterations",
        "1",
        "--scientist",
    )
    result = run_scientist(
        args,
        run_stage=lambda argv: 0,
        evidence_root=tmp_path / "evidence",
        user_dir=user_dir,
        setup_ini=baseline_setup,
        selfplay={"base": {"valid": True}, "iterations": [], "stopped": "pace plateau"},
        base_outcome=base_outcome,
    )

    expected_nested_calls = 0 if expected_error == "baseline_batch_unverifiable" else 1
    assert len(nested_calls) == expected_nested_calls
    if nested_calls:
        assert nested_calls[0].scientist is False
    assert result["ok"] is (expected_error is None)
    if expected_error is None:
        assert result["outcomes"][0]["promoted"] is True
        assert Path(result["run_path"]).is_file()
        assert Path(result["ledger_path"]).is_file()
    else:
        assert expected_error in result["error"]
        assert not (user_dir / "journal" / "alien_scientist" / "experiments.jsonl").exists()


# --------------------------------------------------------------------- #737 setup re-bake race
def _scientist_lap_payload(lap_n: int, lap_ms: int, *, wing: int, path: Path) -> dict:
    """A combo-matched, valid archived lap for the #737 candidate-retry tests (pure)."""
    return {
        "schema_version": 1,
        "lap_uuid": f"lap-{wing}-{lap_n}",
        "session_uuid": f"session-{wing}",
        "exported_at": f"2026-08-09T00:00:0{lap_n}Z",
        "car": {"id": "car_a"},
        "track": {"id": "trk", "layout": None},
        "lap": {"lap_n": lap_n, "lap_ms": lap_ms, "is_valid": True},
        "setup": {
            "hash": f"setup-{wing}",
            "path": str(path),
            "snapshot": {"WING_2.VALUE": wing, "FRONT_BIAS.VALUE": 60},
        },
    }


def _scientist_batch_env(monkeypatch, tmp_path):
    """Schema + verifiable 2-lap baseline batch shared by the #737 candidate-retry tests."""
    from tools.ai_sidecar import car_schema
    from tools.ai_sidecar.car_schema import CarSetupSchema

    user_dir = tmp_path / "Assetto Corsa"
    baseline_setup = user_dir / "setups" / "car_a" / "trk" / "baseline.ini"
    baseline_setup.parent.mkdir(parents=True)
    baseline_setup.write_text("[WING_2]\nVALUE=10\n\n[FRONT_BIAS]\nVALUE=60\n", encoding="utf-8")
    schema = CarSetupSchema.from_spinners_dump(
        "car_a",
        [
            {"name": "WING_2", "min": 0, "max": 20, "step": 1},
            {"name": "FRONT_BIAS", "min": 50, "max": 70, "step": 1},
        ],
    )
    monkeypatch.setattr(car_schema, "load_latest_schema", lambda car: schema)

    baseline_paths = []
    for lap_n, lap_ms in ((1, 100_000), (2, 101_000)):
        path = tmp_path / f"baseline_lap_{lap_n}.json"
        path.write_text(
            _json.dumps(_scientist_lap_payload(lap_n, lap_ms, wing=10, path=baseline_setup)),
            encoding="utf-8",
        )
        baseline_paths.append(str(path))
    base_outcome = {
        "report": {"lap_times_ms": [100_000, 101_000], "drive": {"recoveries": 0}},
        "lap_archives": baseline_paths,
    }
    return user_dir, baseline_setup, base_outcome


def _race_failed_pipeline_result(candidate_args) -> tuple[int, dict]:
    """A candidate pipeline failure carrying the auto_drive #737 race signature."""
    identify_dir = Path(candidate_args.evidence_dir) / "identify"
    identify_dir.mkdir(parents=True)
    (identify_dir / "report.json").write_text(
        _json.dumps(
            {
                "report": {
                    "ok": False,
                    "stage": "setup",
                    "setup_race_suspected": True,
                    "error": "setup not applied: fuel 30.0L != setup FUEL 40.0L (±2.5)",
                }
            }
        ),
        encoding="utf-8",
    )
    return 1, {
        "stages": {"identify": {"exit_code": 1, "evidence_dir": str(identify_dir)}},
        "ok": False,
        "error": "identification stage failed (exit 1)",
    }


def _run_scientist_with_fake_pipeline(monkeypatch, tmp_path, fake_nested_pipeline):
    user_dir, baseline_setup, base_outcome = _scientist_batch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(auto_alien, "run_pipeline", fake_nested_pipeline)
    args = _args(
        user_dir, "--setup", str(baseline_setup), "--laps", "2", "--iterations", "1", "--scientist"
    )
    result = run_scientist(
        args,
        run_stage=lambda argv: 0,
        evidence_root=tmp_path / "evidence",
        user_dir=user_dir,
        setup_ini=baseline_setup,
        selfplay={"base": {"valid": True}, "iterations": [], "stopped": "pace plateau"},
        base_outcome=base_outcome,
    )
    return result, user_dir


def _successful_candidate_pipeline_result(candidate_args) -> tuple[int, dict]:
    """A complete 2-lap candidate batch faster than the baseline (promotable)."""
    drive_dir = Path(candidate_args.evidence_dir) / "drive"
    drive_dir.mkdir(parents=True)
    paths = []
    for lap_n, lap_ms in ((1, 90_000), (2, 91_000)):
        path = drive_dir / f"lap_{lap_n}.json"
        path.write_text(
            _json.dumps(
                _scientist_lap_payload(lap_n, lap_ms, wing=9, path=Path(candidate_args.setup))
            ),
            encoding="utf-8",
        )
        paths.append(str(path))
    (drive_dir / "report.json").write_text(
        _json.dumps(
            {
                "report": {"lap_times_ms": [90_000, 91_000], "drive": {"recoveries": 0}},
                "lap_archives": paths,
            }
        ),
        encoding="utf-8",
    )
    return 0, {"stages": {"drive": {"evidence_dir": str(drive_dir)}}, "ok": True}


def test_scientist_candidate_retries_once_on_setup_race_and_completes(monkeypatch, tmp_path):
    # #737: candidate 1's identify stage lost the setup re-bake race. The batch must NOT abort —
    # one fresh pipeline cycle recovers, and the completed baseline + verdict persist normally.
    nested_calls = []

    def fake_nested_pipeline(candidate_args, *, run_stage):
        del run_stage
        nested_calls.append(candidate_args)
        if len(nested_calls) == 1:
            return _race_failed_pipeline_result(candidate_args)
        return _successful_candidate_pipeline_result(candidate_args)

    result, user_dir = _run_scientist_with_fake_pipeline(
        monkeypatch, tmp_path, fake_nested_pipeline
    )

    assert result["ok"] is True
    assert len(nested_calls) == 2
    assert str(nested_calls[0].evidence_dir).endswith("candidate_01")
    assert str(nested_calls[1].evidence_dir).endswith("candidate_01_retry")
    assert nested_calls[1].setup == nested_calls[0].setup  # the same candidate file retries
    assert result["setup_race_retries"] == [
        {
            "candidate": 1,
            "stage": "identify",
            "first_evidence_root": str(tmp_path / "evidence" / "scientist" / "candidate_01"),
            "evidence_root": str(tmp_path / "evidence" / "scientist" / "candidate_01_retry"),
            "recovered": True,
        }
    ]
    assert result["outcomes"][0]["evidence_root"].endswith("candidate_01_retry")
    assert result["outcomes"][0]["promoted"] is True
    assert Path(result["run_path"]).is_file()
    assert Path(result["ledger_path"]).is_file()


def test_scientist_candidate_retry_exhaustion_aborts_batch_honestly(monkeypatch, tmp_path):
    # #737 bound: a candidate that loses the race twice still aborts the batch — the retry never
    # launders a persistently unverifiable candidate into the ledger.
    nested_calls = []

    def fake_nested_pipeline(candidate_args, *, run_stage):
        del run_stage
        nested_calls.append(candidate_args)
        return _race_failed_pipeline_result(candidate_args)

    result, user_dir = _run_scientist_with_fake_pipeline(
        monkeypatch, tmp_path, fake_nested_pipeline
    )

    assert result["ok"] is False
    assert "scientist_candidate_batch_incomplete" in result["error"]
    assert len(nested_calls) == 2  # exactly one retry — bounded
    assert result["setup_race_retries"][0]["recovered"] is False
    assert not (user_dir / "journal" / "alien_scientist" / "experiments.jsonl").exists()


def test_scientist_setup_race_retry_composes_boundedly_with_real_pipeline(monkeypatch, tmp_path):
    # Codex P2 (PR #740): the earlier retry tests mock run_pipeline, so they cannot see the
    # composed budget. This drives the REAL run_pipeline (scripted run_stage) for a candidate
    # whose identify stage persistently fails with the race signature: the scientist enters the
    # pipeline exactly TWICE (initial + one retry) and then aborts — the pipeline-level bound is
    # enforced; the per-stage launch bound is proven by the auto_drive wrapper tests, so the
    # composed worst case is 2 * (1 + setup_verify_retries) launches.
    user_dir, baseline_setup, base_outcome = _scientist_batch_env(monkeypatch, tmp_path)
    _usable_plant(monkeypatch, False)  # every candidate pipeline requires identification
    stage_calls: list[list[str]] = []

    def run_stage(argv: list[str]) -> int:
        stage_calls.append(list(argv))
        evidence_dir = Path(argv[argv.index("--evidence-dir") + 1])
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "report.json").write_text(
            _json.dumps(
                {
                    "report": {
                        "ok": False,
                        "stage": "setup",
                        "setup_race_suspected": True,
                        "error": "setup not applied: fuel 30.0L != setup FUEL 40.0L (±2.5)",
                    }
                }
            ),
            encoding="utf-8",
        )
        return 1

    args = _args(
        user_dir, "--setup", str(baseline_setup), "--laps", "2", "--iterations", "1", "--scientist"
    )
    result = run_scientist(
        args,
        run_stage=run_stage,
        evidence_root=tmp_path / "evidence",
        user_dir=user_dir,
        setup_ini=baseline_setup,
        selfplay={"base": {"valid": True}, "iterations": [], "stopped": "pace plateau"},
        base_outcome=base_outcome,
    )

    assert result["ok"] is False
    assert "scientist_candidate_batch_incomplete" in result["error"]
    # The real pipeline ran exactly twice: identify failed in the initial attempt and in the one
    # retry — no third pipeline entry, so the composed budget cannot grow beyond 2 attempts.
    assert len(stage_calls) == 2
    assert all("handshake" in call for call in stage_calls)  # both were identify stages
    assert "candidate_01" in " ".join(stage_calls[0])
    assert "candidate_01_retry" in " ".join(stage_calls[1])
    assert result["setup_race_retries"] == [
        {
            "candidate": 1,
            "stage": "identify",
            "first_evidence_root": str(tmp_path / "evidence" / "scientist" / "candidate_01"),
            "evidence_root": str(tmp_path / "evidence" / "scientist" / "candidate_01_retry"),
            "recovered": False,
        }
    ]


def test_scientist_candidate_non_race_failure_does_not_retry(monkeypatch, tmp_path):
    # Any other candidate failure keeps the pre-#737 contract: no retry, honest abort.
    nested_calls = []

    def fake_nested_pipeline(candidate_args, *, run_stage):
        del run_stage
        nested_calls.append(candidate_args)
        stage_dir = Path(candidate_args.evidence_dir) / "identify"
        return 1, {
            # No report.json on disk — the failure carries no race signature.
            "stages": {"identify": {"exit_code": 1, "evidence_dir": str(stage_dir)}},
            "ok": False,
            "error": "identification stage failed (exit 1)",
        }

    result, user_dir = _run_scientist_with_fake_pipeline(
        monkeypatch, tmp_path, fake_nested_pipeline
    )

    assert result["ok"] is False
    assert "scientist_candidate_batch_incomplete" in result["error"]
    assert len(nested_calls) == 1  # no retry burned on a non-race failure
    assert "setup_race_retries" not in result
