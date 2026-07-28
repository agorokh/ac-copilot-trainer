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


def _archive_payload(lap_n=1, valid=True, car="car_a", track="trk"):
    return {
        "car": {"id": car},
        "track": {"id": track, "layout": None},
        "lap": {"lap_n": lap_n, "lap_ms": 90000, "is_valid": valid},
    }


def test_evaluate_selfplay_iteration_falsification_branches():
    ok_payloads = [_archive_payload(1), _archive_payload(2)]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 93000]), ok_payloads)
    assert valid and "AC-valid" in reason

    valid, reason = evaluate_selfplay_iteration(0, None, ok_payloads)
    assert not valid and "report missing" in reason

    valid, reason = evaluate_selfplay_iteration(
        1, _stage_outcome([95000], stage="drive", error="boom"), ok_payloads
    )
    assert not valid and "exit 1" in reason and "boom" in reason

    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([95000], recoveries=2), ok_payloads
    )
    assert not valid and "recovery" in reason

    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([]), ok_payloads)
    assert not valid and "no timed lap" in reason

    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000]), [])
    assert not valid and "no lap archives" in reason

    bad = [_archive_payload(1), _archive_payload(2, valid=False)]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 96000]), bad)
    assert not valid and "AC-invalid lap" in reason and "lap_n=2" in reason

    # A payload with no explicit lap-validity verdict fails CLOSED (#579 Qodo).
    malformed = [_archive_payload(1), {"car": {"id": "car_a"}, "trace": {}}]
    valid, reason = evaluate_selfplay_iteration(0, _stage_outcome([95000, 96000]), malformed)
    assert not valid and "without a lap-validity verdict" in reason

    # A partial archive set leaves counted laps unverifiable -> falsified (#579 Codex P2).
    valid, reason = evaluate_selfplay_iteration(
        0, _stage_outcome([95000, 93000, 92000]), [_archive_payload(1)]
    )
    assert not valid and "archive count 1 < 3 timed laps" in reason


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
                p.write_text(_json.dumps(_archive_payload(n, valid)), encoding="utf-8")
                paths.append(str(p))
            payload = {
                "report": {
                    "ok": exit_code == 0,
                    "stage": "done" if exit_code == 0 else "drive",
                    "lap_times_ms": lap_times,
                    "drive": {"recoveries": 0},
                },
                "lap_archives": paths,
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


def test_selfplay_reproduces_the_529_g2_recipe_unchanged(monkeypatch, tmp_path):
    """The hand-run recipe that produced G2 must drive the SAME sequence after #703.

    Ladder 3 of the #529 Magione session ran ``--ggv-scale 1.0 --scale-step 0.15 --max-scale
    1.15 --iterations 2 --laps 3`` and both iterations drove at 1.15 (the rung is capped at the
    first step), with iteration 1's refit a no-op and iteration 2's real. That recipe IS a
    decoupled ladder run by hand — capping the rung so the top step can never falsify is exactly
    how the operator kept the refit — so decoupling must reproduce it rather than perturb the
    configuration that broke the 82.7 s floor.
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
    assert selfplay["stopped"] == "completed"
    # Identical drive sequence to the recorded ladder: both iterations at the capped 1.15 rung.
    assert [entry["ggv_scale"] for entry in selfplay["iterations"]] == [1.15, 1.15]
    # Iteration 1's no-op refit falls through to the rung; iteration 2 is the plant step that
    # actually raised bins — and it is retained, exactly as the live ladder recorded.
    assert [entry["step_kind"] for entry in selfplay["iterations"]] == ["envelope", "plant"]
    assert selfplay["refit_iterations"] == [2]
    assert selfplay["best_lap_ms"] == 80791
    assert _json.loads(harness.plant_path.read_text(encoding="utf-8")) == {"v": "iter1"}


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
    assert selfplay["ladder_base_scale"] == 0.9
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
    monkeypatch.setattr(auto_alien, "_current_plant_fit_sha12", lambda *a, **kw: "peerfit000000")
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
    monkeypatch.setattr(auto_alien, "_current_plant_fit_sha12", lambda *a, **kw: None)
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
    monkeypatch.setattr(
        auto_alien,
        "load_plant_artifact",
        lambda *a, **kw: {
            "fit": 1,
            "ggv": {"model": {"provenance": {"selfplay_merges": [{"n": 1}, {"n": 2}]}}},
        },
    )
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

    def exploding_read(*a, **kw):
        raise OSError("disk on fire")

    monkeypatch.setattr(type(harness.plant_path), "read_bytes", exploding_read)
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
        (((1, 100_000), (2, 101_000)), ((3, 90_000), (4, 91_000)), None),
        (((1, 100_000), (2, 101_000)), ((3, 90_000),), "candidate_batch_incomplete"),
        (((1, 100_000),), ((3, 90_000), (4, 91_000)), "baseline_batch_unverifiable"),
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
