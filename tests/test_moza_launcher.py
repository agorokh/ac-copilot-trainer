"""Offline Game Point actions preserve the live rig boundary (synthetic inputs only)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.rig_launcher import app, settings
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointStatus,
    GamePointSupervisor,
    LauncherPaths,
    OfflineReportResult,
    ProbeResult,
)


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(tmp_path / "attributions.json"))
    paths = LauncherPaths(tmp_path / "game-point")
    config = GamePointConfig(
        paths=paths,
        reference_archive="tt-reference.json",
        voice_bank="voice-bank",
        alien_line="alien.json",
        voice_tts=False,
    )
    fail = Mock(side_effect=AssertionError("offline action touched a process/network"))
    return GamePointSupervisor(
        config,
        environ={"TT_REFRESH_TOKEN": "synthetic-test-only"},
        popen=fail,
        run=fail,
        urlopen=fail,
    )


@pytest.fixture
def report_api(monkeypatch, tmp_path):
    import tools.session_review as review

    payload = {
        "moza_review": {
            "status": "inspection_only",
            "available": False,
            "authority": "unknown",
            "reason": "processed_channels_not_native",
            "oracle": {"status": "disabled"},
        }
    }
    build = Mock(return_value=payload)
    write = Mock(return_value=SimpleNamespace(html_path=tmp_path / "journal/reports/report.html"))
    monkeypatch.setattr(review, "build_moza_session_report", build, raising=False)
    monkeypatch.setattr(review, "write_session_report", write)
    return build, write, payload


def test_offline_settings_default_off_and_cli_reconstruction(tmp_path, monkeypatch):
    monkeypatch.delenv("AC_COPILOT_REFERENCE_ARCHIVE", raising=False)
    monkeypatch.delenv("AC_COPILOT_VOICE_BANK", raising=False)
    paths = LauncherPaths(tmp_path)
    assert settings.default_settings_payload()["moza_offline_oracle"] is False
    assert settings.default_settings_payload()["moza_offline_shadow"] is False
    assert settings.default_settings_payload()["moza_offline_reference_file"] == ""
    assert GamePointConfig.from_env({}, paths=paths).moza_offline_oracle is False
    assert GamePointConfig.from_env({}, paths=paths).moza_offline_shadow is False
    assert GamePointConfig.from_env({}, paths=paths).moza_offline_reference_file is None
    settings.update_settings(
        paths,
        moza_offline_file="cache.json",
        moza_offline_native_file="native.json",
        moza_offline_evaluation_file="evaluation.json",
        moza_offline_oracle=True,
        moza_offline_shadow=True,
        moza_offline_reference_file="technique.json",
        reference_archive="tt.json",
        voice_bank="bank",
    )
    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    config = app.config_from_args(app.build_arg_parser().parse_args([]))
    assert config.moza_offline_file == "cache.json"
    assert config.moza_offline_native_file == "native.json"
    assert config.moza_offline_evaluation_file == "evaluation.json"
    assert config.moza_offline_oracle is True
    assert config.moza_offline_shadow is True
    assert config.moza_offline_reference_file == "technique.json"
    assert config.reference_archive == "tt.json"
    assert config.voice_bank == "bank"


@pytest.mark.parametrize("oracle_enabled", [False, True])
@pytest.mark.parametrize("shadow_enabled", [False, True])
def test_explicit_action_persists_only_offline_choices_and_keeps_live_config(
    supervisor,
    report_api,
    oracle_enabled,
    shadow_enabled,
):
    build, write, payload = report_api
    settings.update_settings(
        supervisor.paths,
        reference_archive="tt-reference.json",
        voice_bank="voice-bank",
        alien_line="alien.json",
        sidecar_port=8877,
    )
    before_command = supervisor.sidecar_command()
    before_env = supervisor.sidecar_environment()
    result = supervisor.run_moza_offline_report(
        "cache.json",
        matched_native_file="native.json",
        evaluation_file="eval.json",
        oracle_enabled=oracle_enabled,
        shadow_enabled=shadow_enabled,
        reference_file="technique.json",
    )
    root = supervisor.paths.root
    build.assert_called_once_with(
        str(root / "cache.json"),
        matched_native_file=str(root / "native.json"),
        evaluation_file=str(root / "eval.json"),
        oracle_enabled=oracle_enabled,
        shadow_enabled=shadow_enabled,
        reference_file=str(root / "technique.json"),
    )
    write.assert_called_once_with(
        payload,
        output_dir=root / "journal" / "reports",
        protected_inputs=(
            root / "cache.json",
            root / "native.json",
            root / "eval.json",
            root / "technique.json",
        ),
    )
    assert result.status.state == "inspection_only"
    assert "authority=unknown" in result.status.detail
    assert "processed_channels_not_native" in result.status.detail
    assert result.report_path == write.return_value.html_path
    stored = json.loads(supervisor.paths.settings_path.read_text())
    assert stored["reference_archive"] == "tt-reference.json"
    assert stored["voice_bank"] == "voice-bank"
    assert stored["alien_line"] == "alien.json"
    assert stored["sidecar_port"] == 8877
    assert stored["moza_offline_oracle"] is oracle_enabled
    assert stored["moza_offline_shadow"] is shadow_enabled
    assert stored["moza_offline_reference_file"] == str(root / "technique.json")
    assert supervisor.config.moza_offline_shadow is shadow_enabled
    assert supervisor.config.moza_offline_reference_file == str(root / "technique.json")
    assert supervisor.sidecar_command() == before_command
    assert supervisor.sidecar_environment() == before_env
    assert supervisor._sidecar_process is None
    assert supervisor._resilient_process is None


def test_real_silent_report_uses_selected_files_without_live_side_effects(
    supervisor, tmp_path, monkeypatch
):
    import builtins
    import socket
    import subprocess
    import threading
    import urllib.request

    from tests.test_voice_shadow_replay import archive, restrict
    from tools import lap_qualification
    from tools.ai_sidecar import driver_profile
    from tools.ai_sidecar.voice import client, playback

    source = tmp_path / "selected.json"
    reference = tmp_path / "technique.json"
    ledger = tmp_path / "attributions.json"
    profile = tmp_path / "live-profile.json"
    for path, payload in (
        (source, restrict(archive())),
        (reference, archive("reference")),
        (ledger, {"schema_version": 1, "entries": []}),
        (profile, {"manual": "preserve live profile"}),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
    original = {path: path.read_bytes() for path in (source, reference, ledger, profile)}
    monkeypatch.setenv("AC_COPILOT_DRIVER_PROFILE", str(profile))
    monkeypatch.setenv("AC_COPILOT_REFERENCE_ARCHIVE", "unselected-live-reference.json")
    monkeypatch.setenv("AC_COPILOT_VOICE_BANK", "unselected-live-bank")
    settings.update_settings(
        supervisor.paths,
        reference_archive=supervisor.config.reference_archive,
        voice_bank=supervisor.config.voice_bank,
        alien_line=supervisor.config.alien_line,
        ac_audio_device="keep operator endpoint",
        start_simhub=True,
    )
    before_settings = json.loads(supervisor.paths.settings_path.read_text(encoding="utf-8"))
    before_command = supervisor.sidecar_command()
    before_env = supervisor.sidecar_environment()
    before_process_env = dict(os.environ)
    forbidden = Mock(side_effect=AssertionError("silent report touched live process/network/audio"))
    for owner, name in (
        (subprocess, "Popen"),
        (subprocess, "run"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (urllib.request, "urlopen"),
        (threading.Thread, "start"),
        (playback.Bank, "__init__"),
        (playback.RtMixerPlayback, "__init__"),
        (playback.SoundDevicePlayback, "__init__"),
        (client, "_pyttsx3_speaker"),
        (driver_profile, "write_profile"),
        (lap_qualification, "register_attribution"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"sounddevice", "rtmixer", "pyttsx3"}:
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = supervisor.run_moza_offline_report(
        str(source), reference_file=str(reference), shadow_enabled=True, oracle_enabled=True
    )
    assert result.status.state == "analysis_available", result.status.detail
    assert "silent validation=replayed" in result.status.detail
    assert "human evaluation=no_go" in result.status.detail
    assert "live activation=no_go" in result.status.detail
    assert "offline advice=unavailable" in result.status.detail
    assert result.report_path is not None
    assert result.report_path.parent == supervisor.paths.root / "journal" / "reports"
    report = json.loads(result.report_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["moza_shadow"]["lanes"]["observer"]["dispatched_count"] > 0
    assert report["moza_shadow"]["lanes"]["coach_v2"]["frames_replayed"] > 0
    assert report["moza_shadow"]["stimulus"]["authority"] == "shared"
    assert report["moza_shadow"]["reference"]["authority"] == "legacy_unknown"
    assert "No speech or audio device" in result.report_path.read_text(encoding="utf-8")
    after_settings = json.loads(supervisor.paths.settings_path.read_text(encoding="utf-8"))
    for key, value in before_settings.items():
        if not key.startswith("moza_offline_"):
            assert after_settings[key] == value
    assert after_settings["moza_offline_shadow"] is True
    assert after_settings["moza_offline_reference_file"] == str(reference)
    assert supervisor.sidecar_command() == before_command
    assert supervisor.sidecar_environment() == before_env
    assert dict(os.environ) == before_process_env
    for path, content in original.items():
        assert path.read_bytes() == content
    assert supervisor.moza_offline_result == result
    assert supervisor._sidecar_process is None
    assert supervisor._resilient_process is None
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "state,authority,reason",
    [
        ("analysis_available", "legacy_unknown", "legacy_native_analysis"),
        ("input_unavailable", "unknown", "selected_file_unreadable"),
        ("inspection_only", "shared", "analysis_use_not_supported"),
    ],
)
def test_status_keeps_qualification_authority_and_oracle_unavailability(
    supervisor,
    report_api,
    state,
    authority,
    reason,
):
    _, _, payload = report_api
    payload["moza_review"].update(
        status=state,
        authority=authority,
        reason=reason,
        oracle={"status": "unavailable", "reason": "zero_evaluated_laps"},
    )
    result = supervisor.run_moza_offline_report("selected.json", oracle_enabled=True)
    assert result.status.state == state
    assert result.status.ok is (state == "analysis_available")
    assert f"authority={authority}" in result.status.detail
    assert reason in result.status.detail
    assert "zero_evaluated_laps" in result.status.detail


@pytest.mark.parametrize("shadow_enabled", [False, True])
def test_shadow_status_adds_decision_without_replacing_numeric_or_oracle_result(
    supervisor, report_api, shadow_enabled
):
    _, _, payload = report_api
    payload["moza_review"].update(
        status="analysis_available",
        authority="shared",
        reason="native_analysis_allowed",
        oracle={"status": "unavailable", "reason": "zero_evaluated_laps"},
    )
    payload["moza_shadow"] = {
        "status": "unavailable",
        "reason": "reference_not_selected",
        "decision": {
            "human_evaluation": "no_go",
            "live_activation": "no_go",
            "reasons": ["qualified_technique_reference_required"],
        },
    }
    result = supervisor.run_moza_offline_report(
        "native.json", oracle_enabled=True, shadow_enabled=shadow_enabled
    )
    assert result.status.state == "analysis_available"
    assert result.status.ok
    for detail in ("authority=shared", "native_analysis_allowed", "zero_evaluated_laps"):
        assert detail in result.status.detail
    for detail in (
        "silent validation=unavailable: reference_not_selected",
        "human evaluation=no_go",
        "live activation=no_go",
        "qualified_technique_reference_required",
    ):
        assert (detail in result.status.detail) is shadow_enabled


@pytest.mark.parametrize(
    "shadow", [None, [], "unavailable", {}, {"status": "unavailable", "decision": "no_go"}]
)
def test_missing_shadow_summary_is_explicit_and_keeps_numeric_report(
    supervisor, report_api, shadow
):
    _, _, payload = report_api
    payload["moza_shadow"] = shadow
    result = supervisor.run_moza_offline_report("cache.json", shadow_enabled=True)
    assert result.status.state == "inspection_only"
    assert result.report_path
    assert "silent validation=unavailable" in result.status.detail
    assert "go/no-go=unavailable" in result.status.detail


@pytest.mark.parametrize("selected", ["", "   ", "../escape.json"])
def test_invalid_selection_does_not_write_or_generate(supervisor, report_api, selected):
    build, write, _ = report_api
    assert supervisor.run_moza_offline_report(selected).status.state == "error"
    build.assert_not_called()
    write.assert_not_called()
    assert not supervisor.paths.settings_path.exists()


@pytest.mark.parametrize("field", ["evaluation_file", "reference_file"])
def test_invalid_optional_path_does_not_silently_drop_selection(supervisor, report_api, field):
    build, _, _ = report_api
    result = supervisor.run_moza_offline_report("cache.json", **{field: "../escape.json"})
    assert result.status.state == "error"
    build.assert_not_called()


@pytest.mark.parametrize(
    "field", ["selected_file", "matched_native_file", "evaluation_file", "reference_file"]
)
@pytest.mark.parametrize("alias", ["direct", "hardlink"])
def test_selected_settings_alias_is_rejected_before_any_write(
    supervisor,
    report_api,
    field,
    alias,
):
    build, write, _ = report_api
    settings.update_settings(supervisor.paths, reference_archive="keep-tt.json")
    path = supervisor.paths.settings_path
    before = path.read_bytes()
    selected = path
    if alias == "hardlink":
        selected = supervisor.paths.root / "selected-alias.json"
        os.link(path, selected)
    kwargs = {"selected_file": "cache.json", field: str(selected)}
    result = supervisor.run_moza_offline_report(**kwargs)
    assert result.status.state == "error"
    assert "aliases Game Point settings" in result.status.detail
    assert path.read_bytes() == before
    assert selected.read_bytes() == before
    build.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("field", ["selected_file", "reference_file"])
@pytest.mark.parametrize("alias", ["direct", "hardlink"])
@pytest.mark.parametrize("shadow_enabled", [False, True])
def test_report_output_alias_refusal_precedes_settings_write(
    supervisor, report_api, monkeypatch, field, alias, shadow_enabled
):
    import tools.session_review as api
    from tools.session_review import report as reports

    _, _, payload = report_api
    output = supervisor.paths.root / "journal" / "reports"
    output.mkdir(parents=True)
    selected = output / (reports._report_basename(payload) + ".json")
    selected.write_text('{"immutable": "synthetic selected input"}')
    before = selected.read_bytes()
    if alias == "hardlink":
        linked = supervisor.paths.root / "reference-alias.json"
        os.link(selected, linked)
        selected = linked
    monkeypatch.setattr(api, "write_session_report", reports.write_session_report)
    result = supervisor.run_moza_offline_report(
        **{"selected_file": "cache.json", field: str(selected)}, shadow_enabled=shadow_enabled
    )
    assert result.status.state == "error"
    assert selected.read_bytes() == before
    assert not supervisor.paths.settings_path.exists()
    assert len(list(output.iterdir())) == 1


def test_malformed_settings_preserved_and_action_stops(supervisor, report_api):
    build, write, _ = report_api
    supervisor.paths.root.mkdir()
    supervisor.paths.settings_path.write_text("{ manual unfinished")
    result = supervisor.run_moza_offline_report("cache.json", shadow_enabled=True)
    assert result.status.state == "error"
    assert "refusing to overwrite malformed" in result.status.detail
    assert supervisor.paths.settings_path.read_text() == "{ manual unfinished"
    build.assert_called_once()
    write.assert_called_once()
    assert result.report_path is not None
    assert "Report saved; selections not saved" in result.status.detail
    assert supervisor.config.moza_offline_file is None


@pytest.mark.parametrize("failure", ["builder", "writer", "qualification"])
def test_failed_rerun_clears_prior_report_and_can_retry(supervisor, report_api, failure):
    build, write, payload = report_api
    assert supervisor.run_moza_offline_report("cache.json").report_path
    if failure == "builder":
        build.side_effect = ValueError("input changed")
    elif failure == "writer":
        write.side_effect = OSError("cannot write report")
    else:
        payload["moza_review"]["status"] = "unexpected"
    result = supervisor.run_moza_offline_report("cache.json")
    assert result.status.state == "error"
    assert result.report_path is None
    assert supervisor.moza_offline_result == result
    assert not supervisor._moza_report_lock.locked()


def test_duplicate_action_coalesces_and_poll_uses_cached_result(
    supervisor, report_api, monkeypatch
):
    build, _, _ = report_api
    assert supervisor._moza_report_lock.acquire(blocking=False)
    try:
        assert supervisor.run_moza_offline_report("cache.json").status.state == "running"
        build.assert_not_called()
    finally:
        supervisor._moza_report_lock.release()
    result = supervisor.run_moza_offline_report("cache.json", shadow_enabled=True)
    healthy = ProbeResult("test", True, "healthy", "screen_peers=1")
    for method in (
        "_sidecar_process_status",
        "probe_voice",
        "probe_simhub",
        "probe_tablet",
        "_resilient_process_status",
        "probe_keypad",
    ):
        monkeypatch.setattr(supervisor, method, Mock(return_value=healthy))
    monkeypatch.setattr(supervisor, "_read_health_payload", Mock(return_value=(healthy, {})))
    monkeypatch.setattr(supervisor, "preflight", Mock(return_value=()))
    monkeypatch.setattr(supervisor, "write_status", Mock())
    for _ in range(3):
        status = supervisor.poll_status(start_simhub=False)
        assert status.moza_review == result.status
        assert status.ok  # inspection-only is advisory, not a START prerequisite
        assert status.to_dict()["moza_review"]["state"] == "inspection_only"
    build.assert_called_once()


def test_offline_error_is_not_part_of_readiness():
    row = ProbeResult("test", True, "healthy")
    status = GamePointStatus(0, row, row, row, row, "log", "status")
    assert replace(status, moza_review=ProbeResult("moza_review", False, "error")).ok


@pytest.mark.parametrize("closed", [False, True])
def test_dialog_callback_uses_worker_and_main_thread_completion(supervisor, monkeypatch, closed):
    from tools.rig_launcher import view

    dialog = Mock()
    dialog.window.winfo_exists.return_value = not closed
    factory = Mock(return_value=dialog)
    monkeypatch.setattr(view, "MozaReviewView", factory)
    threads = []
    monkeypatch.setattr(app.threading, "Thread", lambda **kw: threads.append(kw) or Mock())
    result = OfflineReportResult(ProbeResult("moza_review", False, "inspection_only"))
    run = Mock(return_value=result)
    monkeypatch.setattr(supervisor, "run_moza_offline_report", run)
    parent = Mock()
    app._open_moza_report_window(supervisor, parent=parent)
    callback = factory.call_args.kwargs["on_generate"]
    selection = {
        "selected_file": "cache.json",
        "oracle_enabled": False,
        "shadow_enabled": True,
        "reference_file": "technique.json",
    }
    callback(selection)
    callback(selection)  # repeat clicks cannot create a second worker
    assert len(threads) == 1
    run.assert_not_called()
    dialog.set_running.assert_called_once()
    threads[0]["target"]()
    run.assert_called_once_with(**selection)
    assert dialog.show_result.call_count == 1  # only initial cached status so far
    parent.after.call_args.args[1]()
    assert dialog.show_result.call_count == (1 if closed else 2)


def test_game_point_action_opens_only_offline_dialog(supervisor, monkeypatch):
    import tkinter as tk

    from tools.rig_launcher import view

    root, panel = Mock(), Mock()
    monkeypatch.setattr(tk, "Tk", Mock(return_value=root))
    factory = Mock(return_value=panel)
    monkeypatch.setattr(view, "build_launcher_view", factory)
    monkeypatch.setattr(app.threading, "Thread", Mock())
    opened = Mock()
    monkeypatch.setattr(app, "_open_moza_report_window", opened)
    root.mainloop.side_effect = lambda: factory.call_args.kwargs["actions"]["moza_offline_report"]()
    assert app.run_gui(supervisor) == 0
    opened.assert_called_once_with(supervisor, parent=root)
    assert supervisor._sidecar_process is None
    assert supervisor._resilient_process is None


def test_view_selection_and_invalidated_open_report_are_headless():
    from tools.rig_launcher.view import MozaReviewView

    panel = object.__new__(MozaReviewView)
    panel._vars = {
        "selected_file": Mock(get=lambda: "cache.json"),
        "matched_native_file": Mock(get=lambda: ""),
        "evaluation_file": Mock(get=lambda: "eval.json"),
        "reference_file": Mock(get=lambda: "technique.json"),
    }
    panel._oracle = Mock(get=lambda: False)
    panel._shadow = Mock(get=lambda: True)
    panel._controls = [Mock(), Mock()]
    panel._status, panel._open = Mock(), Mock()
    assert panel.selection() == {
        "selected_file": "cache.json",
        "matched_native_file": "",
        "evaluation_file": "eval.json",
        "reference_file": "technique.json",
        "oracle_enabled": False,
        "shadow_enabled": True,
    }
    panel.show_result(
        OfflineReportResult(
            ProbeResult("moza_review", False, "inspection_only", "processed channels"),
            Path("report.html"),
        )
    )
    assert "INSPECTION ONLY" in panel._status.configure.call_args.kwargs["text"]
    panel._selection_changed()
    assert panel._report_path is None
    panel._open.configure.assert_called_with(state="disabled")
    panel.set_running()
    for control in panel._controls:
        control.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("shadow_enabled", [False, True])
def test_dialog_restores_offline_choices_and_edits_invalidate_report(monkeypatch, shadow_enabled):
    from tools.rig_launcher import view

    class Variable:
        def __init__(self, *, master, value):
            self.value = value
            self.callback = None

        def get(self):
            return self.value

        def trace_add(self, mode, callback):
            assert mode == "write"
            self.callback = callback

        def set(self, value):
            self.value = value
            if self.callback:
                self.callback()

    widgets = {}
    for widget in ("Toplevel", "Frame", "Label", "Entry", "Button", "Checkbutton"):
        widgets[widget] = Mock(side_effect=lambda *_a, **_kw: Mock())
        monkeypatch.setattr(view.tk, widget, widgets[widget])
    monkeypatch.setattr(view.tk, "StringVar", Variable)
    monkeypatch.setattr(view.tk, "BooleanVar", Variable)
    config = GamePointConfig(
        moza_offline_file="selected.json",
        moza_offline_native_file="native.json",
        moza_offline_evaluation_file="eval.json",
        moza_offline_oracle=True,
        moza_offline_shadow=shadow_enabled,
        moza_offline_reference_file="technique.json",
        reference_archive="live-reference.json",
        voice_bank="live-bank",
    )
    generated = Mock()
    panel = view.MozaReviewView(Mock(), config=config, on_generate=generated, on_open=Mock())
    assert panel.selection() == {
        "selected_file": "selected.json",
        "matched_native_file": "native.json",
        "evaluation_file": "eval.json",
        "oracle_enabled": True,
        "shadow_enabled": shadow_enabled,
        "reference_file": "technique.json",
    }
    labels = " ".join(call.kwargs["text"] for call in widgets["Label"].call_args_list)
    assert "without playing audio" in labels and "qualified technique reference" in labels
    assert any(
        call.kwargs["text"] == "Silent voice validation"
        for call in widgets["Checkbutton"].call_args_list
    )
    saved = OfflineReportResult(
        ProbeResult("moza_review", True, "analysis_available"), Path("report.html")
    )
    for variable, value in (
        (panel._vars["reference_file"], "other-reference.json"),
        (panel._shadow, not shadow_enabled),
    ):
        panel.show_result(saved)
        variable.set(value)
        assert panel._report_path is None
        panel._open.configure.assert_called_with(state="disabled")
    generate = next(
        call.kwargs["command"]
        for call in widgets["Button"].call_args_list
        if call.kwargs["text"] == "SAVE SELECTIONS & GENERATE"
    )
    generate()
    generated.assert_called_once_with(panel.selection())


def test_offline_button_dispatches_only_its_supplied_action(monkeypatch):
    from tools.rig_launcher import view

    panel = object.__new__(view.LauncherView)
    panel._f_disp = "test-font"
    monkeypatch.setattr(view.tk, "Frame", Mock())
    buttons = Mock()
    monkeypatch.setattr(view.tk, "Button", buttons)
    actions = {key: Mock() for _, key, _ in view._BUTTONS}
    actions["moza_offline_report"] = Mock()
    panel._build_buttons(Mock(), actions)
    assert buttons.call_count == 8
    offline = buttons.call_args.kwargs
    assert offline["text"] == "OFFLINE REPORT"
    offline["command"]()
    actions["moza_offline_report"].assert_called_once_with()
    for _, key, _ in view._BUTTONS:
        actions[key].assert_not_called()
