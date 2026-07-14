"""Tests for the #572 one-button alien pipeline orchestration (no rig needed)."""

from __future__ import annotations

import pytest

from tools.ac_harness import auto_alien
from tools.ac_harness.auto_alien import (
    _build_arg_parser,
    drive_argv,
    identify_argv,
    needs_identification,
    run_pipeline,
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
