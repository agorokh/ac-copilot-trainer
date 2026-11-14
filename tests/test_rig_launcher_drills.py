"""Canonical Game Point practice selection and truthful operational readback."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tools.rig_launcher.app import build_arg_parser, config_from_args
from tools.rig_launcher.settings import (
    LauncherSettings,
    default_settings_payload,
    ensure_settings_file,
)
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
    render_status_lines,
)


def _supervisor(tmp_path, *, enabled=False, environ=None, payload=None, popen=None):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(payload or {"status": "ok"}).encode()

    return GamePointSupervisor(
        GamePointConfig(
            paths=LauncherPaths(tmp_path), coach_drills=enabled, rig_lock_path=tmp_path / "rig.lock"
        ),
        environ={} if environ is None else environ,
        urlopen=lambda *args, **kwargs: Response(),
        run=lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout=""),
        popen=popen or (lambda *args, **kwargs: pytest.fail("Unexpected process start")),
    )


@pytest.fixture(scope="module")
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        if sys.platform == "win32":
            raise
        pytest.skip("Tk display unavailable")
    root.withdraw()
    yield root
    root.destroy()


def test_practice_drill_default_is_persisted_off(tmp_path):
    paths = LauncherPaths(tmp_path)
    assert default_settings_payload()["coach_drills"] is False
    path = ensure_settings_file(paths)
    assert LauncherSettings.load(path).coach_drills is False
    assert GamePointConfig.from_env({}, paths=paths).coach_drills is False


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, True),
        ({"AC_COPILOT_COACH_DRILLS": "0"}, False),
        ({"AC_COPILOT_COACH_DRILLS": ""}, False),
        ({"AC_COPILOT_COACH_DRILLS": "1"}, True),
    ],
)
def test_practice_setting_env_precedence_including_explicit_off(tmp_path, env, expected):
    paths = LauncherPaths(tmp_path)
    paths.settings_path.write_text(json.dumps({"coach_drills": True}), encoding="utf-8")
    config = GamePointConfig.from_env(env, paths=paths)
    assert config.coach_drills is expected


def test_ordinary_config_args_preserve_the_practice_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    monkeypatch.setenv("AC_COPILOT_COACH_DRILLS", "1")
    args = build_arg_parser().parse_args([])
    assert config_from_args(args).coach_drills is True


def test_child_gets_practice_and_coach_v2_without_arming_audio_or_experiments(tmp_path):
    inherited = {
        "AC_COPILOT_COACH_V2": "0",
        "AC_COPILOT_PRESSURE_EXPERIMENT": "0",
        "AC_COPILOT_TRAFFIC_SHADOW": "0",
    }
    supervisor = _supervisor(tmp_path, enabled=True, environ=inherited)
    child = supervisor.sidecar_environment()
    assert child["AC_COPILOT_COACH_DRILLS"] == "1" and child["AC_COPILOT_COACH_V2"] == "1"
    assert "AC_COPILOT_VOICE_BANK" not in child and "AC_COPILOT_VOICE_TTS" not in child
    assert child["AC_COPILOT_PRESSURE_EXPERIMENT"] == "0"
    assert child["AC_COPILOT_TRAFFIC_SHADOW"] == "0"
    assert (
        _supervisor(tmp_path, environ={"AC_COPILOT_COACH_DRILLS": "1"}).sidecar_environment()[
            "AC_COPILOT_COACH_DRILLS"
        ]
        == "0"
    )


def test_toggle_saves_without_stopping_or_reconfiguring_an_active_session(tmp_path):
    class Running:
        def poll(self):
            return None

        def terminate(self):
            pytest.fail("Toggle stopped the active session")

    supervisor = _supervisor(tmp_path)
    running = Running()
    supervisor._sidecar_process = running
    assert supervisor.set_coach_drills(True)
    assert supervisor._sidecar_process is running
    assert json.loads(supervisor.paths.settings_path.read_text())["coach_drills"] is True
    old_runtime = {"voice": {"practice_drill": {"configured": False, "active": False}}}
    pending = supervisor.probe_practice_drill(old_runtime)
    assert pending.state == "restart_required" and "after your driving session" in pending.detail
    new_runtime = {
        "voice": {"practice_drill": {"configured": True, "active": True, "phase": "retention"}}
    }
    assert supervisor.probe_practice_drill(new_runtime).state == "retention"


def test_toggle_honors_environment_off_and_preserves_unrelated_settings(tmp_path):
    supervisor = _supervisor(tmp_path, environ={"AC_COPILOT_COACH_DRILLS": "0"})
    supervisor.paths.settings_path.write_text(
        json.dumps({"reference_archive": "manual-reference.json"}), encoding="utf-8"
    )
    assert supervisor.set_coach_drills(True) is False
    payload = json.loads(supervisor.paths.settings_path.read_text())
    assert payload["reference_archive"] == "manual-reference.json"
    assert payload["coach_drills"] is True
    assert supervisor.sidecar_environment()["AC_COPILOT_COACH_DRILLS"] == "0"


def test_failed_preference_write_preserves_configuration_and_manual_file(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor.paths.settings_path.write_text("{manual unfinished", encoding="utf-8")
    with pytest.raises(ValueError):
        supervisor.set_coach_drills(True)
    assert not supervisor.config.coach_drills
    assert supervisor.paths.settings_path.read_text() == "{manual unfinished"


@pytest.mark.parametrize(
    "state,expected,detail",
    [
        ({"configured": False, "active": False}, "disabled", "off"),
        ({"configured": True, "active": True, "phase": "cued"}, "practice", "one corner"),
        ({"configured": True, "active": True, "phase": "retention"}, "retention", "without"),
        (
            {
                "configured": True,
                "active": False,
                "phase": "failed",
                "reason": "exit_speed_degraded",
            },
            "stopped",
            "exit speed",
        ),
        (
            {
                "configured": True,
                "active": False,
                "phase": "aborted",
                "reason": "lap_budget_exhausted",
            },
            "stopped",
            "lap limit",
        ),
        ({"configured": True, "active": False, "phase": "passed"}, "passed", "completed"),
        (
            {
                "configured": True,
                "active": False,
                "phase": "waiting",
                "reason": "qualified_human_reference_required",
            },
            "waiting",
            "human",
        ),
    ],
)
def test_status_comes_from_operational_health_not_requested_settings(
    tmp_path, state, expected, detail
):
    # Desired setting is off, yet readback must show the actual adopted sidecar's state.
    supervisor = _supervisor(tmp_path, enabled=False)
    result = supervisor.probe_practice_drill({"voice": {"practice_drill": state}})
    assert result.state == expected and detail in result.detail


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"configured": True},
        {"configured": False, "active": True},
        {"configured": 1, "active": True},
    ],
)
def test_missing_or_inconsistent_health_is_unavailable(tmp_path, state):
    supervisor = _supervisor(tmp_path, enabled=True)
    assert (
        supervisor.probe_practice_drill({"voice": {"practice_drill": state}}).state == "unavailable"
    )


def test_poll_status_writes_operational_practice_row_without_personal_targets(tmp_path):
    payload = {
        "status": "ok",
        "voice": {
            "practice_drill": {
                "configured": True,
                "active": True,
                "phase": "retention",
                "reason": "target_band_met",
                "reference_identity": "private-reference-identity",
                "cued_successes": 2,
            }
        },
    }
    supervisor = _supervisor(tmp_path, payload=payload)
    status = supervisor.poll_status(start_simhub=False)
    assert status.practice_drill.state == "retention"
    assert any(line.startswith("practice_drill: retention") for line in render_status_lines(status))
    saved = supervisor.paths.status_path.read_text()
    assert "private-reference-identity" not in saved and "cued_successes" not in saved


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_actual_checkbox_follows_effective_value_and_can_render_retention(tk_root, scaling):
    import tkinter as tk

    from tools.rig_launcher.preview import _NOOP_ACTIONS, demo_status
    from tools.rig_launcher.supervisor import ProbeResult
    from tools.rig_launcher.view import build_launcher_view

    root = tk.Toplevel(tk_root)
    root.withdraw()
    root.tk.call("tk", "scaling", scaling)
    seen = []
    try:
        view = build_launcher_view(
            root,
            actions=_NOOP_ACTIONS,
            status_path="status.json",
            coach_drills=False,
            on_toggle_simhub=lambda enabled: None,
            on_toggle_drills=lambda enabled: seen.append(enabled) or False,
        )
        controls = []

        def collect(parent):
            for child in parent.winfo_children():
                if isinstance(child, tk.Checkbutton) and child.cget("text") == "Practice drill":
                    controls.append(child)
                collect(child)

        collect(root)
        assert len(controls) == 1
        controls[0].invoke()
        assert seen == [True] and view._coach_drills_var.get() is False
        from dataclasses import replace

        view.update(
            replace(
                demo_status(),
                practice_drill=ProbeResult(
                    "practice_drill", True, "retention", "Drive without practice instructions."
                ),
            )
        )
        view.fit_window()
        root.deiconify()
        root.update()
        assert (
            view._rows["practice_drill"]["detail"].cget("text")
            == "Drive without practice instructions."
        )
        for widget in controls:
            assert widget.winfo_ismapped()
            assert widget.winfo_y() + widget.winfo_height() <= widget.master.winfo_height()
    finally:
        root.destroy()
