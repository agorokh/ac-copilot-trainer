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
            return {"ok": True}, {"ok": True, "selfplay_merge": dict(self.merge_stats)}

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


def test_selfplay_ladder_progresses_and_reports_trajectory(monkeypatch, tmp_path):
    harness = _SelfplayHarness(
        monkeypatch,
        tmp_path,
        stage_specs=[
            (0, [95000], [True]),  # base drive
            (0, [93000], [True]),  # iteration 1
            (0, [91000], [True]),  # iteration 2
        ],
    )
    args = _args(
        tmp_path,
        "--evidence-dir",
        str(tmp_path / "ev"),
        "--laps",
        "1",
        "--iterations",
        "2",
        "--scale-step",
        "0.05",
        "--max-scale",
        "1.1",
    )
    code, report = run_pipeline(args, run_stage=harness.runner())
    assert code == 0 and report["ok"]
    selfplay = report["selfplay"]
    assert selfplay["stopped"] == "completed"
    assert selfplay["lap_trajectory_ms"] == [[95000], [93000], [91000]]
    assert selfplay["best_lap_ms"] == 91000
    scales = [entry["ggv_scale"] for entry in selfplay["iterations"]]
    assert scales == [0.95, 1.0]
    assert all(entry["valid"] for entry in selfplay["iterations"])
    # Each refine consumed the PREVIOUS drive's batch (provenance-bound self-play).
    assert len(harness.refine_calls) == 2
    assert harness.saves == 2
    assert harness.persist_lock_timeouts == [0.0, 0.0]
    # The plant on disk is the last refined fit (no falsification -> no revert).
    assert _json.loads(harness.plant_path.read_text(encoding="utf-8")) == {"v": "iter2"}


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
    # Keep-last-valid: the falsified refined fit was rolled back on disk.
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
    # The peer's newer artifact survived untouched.
    assert harness.plant_path.read_text(encoding="utf-8") == '{"v": "peer"}'


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
