"""Prospective declarations use the normal launcher without global configuration changes."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import wave
from dataclasses import replace

import pytest
from _voice_support import build_manifest

from tools.human_session import HumanSessionPermit, campaign_path
from tools.rig_launcher.app import _open_human_session_window
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
    ProbeResult,
    build_pyinstaller_args,
)

ASSISTANCE = {
    "human_steering": True,
    "human_throttle": True,
    "human_brake": True,
    "ai": False,
    "shared": False,
    "harness": False,
    "mode": "live",
    "abs": "factory",
    "tc": "factory",
    "gears": "manual",
    "clutch": "off",
    "blip": "off",
    "stability": "off",
    "abs_level": "3",
    "tc_level": "2",
    "stability_level": "0",
}


def bank_at(path):
    """Explicit synthetic PCM fixture; no audio backend or production qualification."""
    path.mkdir(parents=True)
    pcm = io.BytesIO()
    with wave.open(pcm, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(b"\0\0" * 80)
    raw = pcm.getvalue()
    manifest = build_manifest()
    for key, entry in list(manifest.clips.items()):
        (path / entry.file).write_bytes(raw)
        manifest.clips[key] = replace(entry, sha256=hashlib.sha256(raw).hexdigest())
    (path / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return path


def supervisor_at(tmp_path, *, environ=None, config=None):
    supervisor = GamePointSupervisor(
        config or GamePointConfig(paths=LauncherPaths(tmp_path), token="synthetic-test-token"),
        environ={} if environ is None else environ,
        popen=lambda *_args, **_kwargs: pytest.fail("Arming started a process"),
        run=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    supervisor._read_health = lambda: ProbeResult("sidecar", False, "not_running")
    return supervisor


def test_prepare_uses_one_valid_staged_bank_and_never_changes_settings_or_environment(tmp_path):
    bank = bank_at(tmp_path / "voice-banks" / "test-bank")
    inherited = {
        "AC_COPILOT_REFERENCE_ARCHIVE": "magione.json",
        "AC_COPILOT_ALIEN_LINE": "magione-alien.json",
        "AC_COPILOT_VOICE_TTS": "1",
        "AC_COPILOT_VOICE_DEVICE": "USB Sound Device",
        "AC_COPILOT_VOICE_HOST_API": "WASAPI",
    }
    config = GamePointConfig(
        paths=LauncherPaths(tmp_path),
        token="synthetic-test-token",
        reference_archive="magione.json",
        alien_line="magione-alien.json",
    )
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{"reference_archive":"manual-magione.json"}\n')
    before = settings.read_bytes()
    supervisor = supervisor_at(tmp_path, config=config, environ=inherited)
    status = supervisor.prepare_human_session(driver_id="private-driver", assistance=ASSISTANCE)
    assert status["phase"] == "prepared" and status["voice_bank"] == str(bank)
    assert status["attempted_laps"] == 0
    child = supervisor.sidecar_environment()
    assert child["AC_COPILOT_PRACTICE_PERMIT"] == str(campaign_path(tmp_path))
    assert child["AC_COPILOT_COACH_DRILLS"] == child["AC_COPILOT_COACH_V2"] == "1"
    assert child["AC_COPILOT_VOICE_BANK"] == str(bank)
    assert child["AC_COPILOT_VOICE_TTS"] == "0"
    assert "AC_COPILOT_REFERENCE_ARCHIVE" not in child and "AC_COPILOT_ALIEN_LINE" not in child
    assert child["AC_COPILOT_VOICE_DEVICE"] == inherited["AC_COPILOT_VOICE_DEVICE"]
    assert child["AC_COPILOT_VOICE_HOST_API"] == inherited["AC_COPILOT_VOICE_HOST_API"]
    assert dict(supervisor._environ) == inherited and supervisor.config is config
    assert settings.read_bytes() == before
    public = supervisor.human_session_status()
    assert "private-driver" not in json.dumps(public)
    assert str(bank) not in json.dumps(public)
    assert "private-driver" not in json.dumps(supervisor.probe_human_session().to_dict())
    assert not supervisor.probe_voice(
        {"voice": {"configured": True, "enabled": False, "state": "observer_only"}}
    ).ok  # the scoped bank is requested even though ordinary config.voice_bank is empty.
    # Merely inspecting or building the child environment cannot consume the campaign.
    assert supervisor.human_session_status(private=True)["phase"] == "prepared"


@pytest.mark.parametrize("kind", ["none", "ambiguous", "invalid"])
def test_arm_requires_an_unambiguous_valid_bank(tmp_path, kind):
    if kind in {"ambiguous", "invalid"}:
        bank = bank_at(tmp_path / "voice-banks" / "first")
        if kind == "ambiguous":
            bank_at(tmp_path / "voice-banks" / "second")
        else:
            next(bank.glob("*.wav")).write_bytes(b"modified")
    supervisor = supervisor_at(tmp_path)
    with pytest.raises(ValueError, match="voice_bank"):
        supervisor.prepare_human_session(driver_id="private-driver", assistance=ASSISTANCE)
    assert not campaign_path(tmp_path).exists()


def test_selected_bank_is_revalidated_before_a_child_can_start(tmp_path):
    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path)
    supervisor.prepare_human_session(
        driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
    )
    next(bank.glob("*.wav")).write_bytes(b"modified after preparation")
    result = supervisor.start_sidecar()
    assert not result.ok and result.state == "start_failed"
    assert supervisor.human_session_status(private=True)["phase"] == "prepared"


def test_ambient_permit_cannot_arm_an_ordinary_child(tmp_path):
    supervisor = supervisor_at(tmp_path, environ={"ac_copilot_practice_permit": "foreign.json"})
    assert all(
        key.upper() != "AC_COPILOT_PRACTICE_PERMIT" for key in supervisor.sidecar_environment()
    )


def test_private_campaign_requires_a_configured_token_before_any_preparation(tmp_path):
    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path, config=GamePointConfig(paths=LauncherPaths(tmp_path)))
    with pytest.raises(ValueError, match="^human_session_token_required$"):
        supervisor.prepare_human_session(
            driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
        )
    assert not campaign_path(tmp_path).exists()
    assert supervisor._sidecar_process is None


def test_corrupt_existing_campaign_is_visible_and_cannot_arm_or_start(tmp_path):
    campaign_path(tmp_path).write_text("malformed", encoding="utf-8")
    supervisor = supervisor_at(tmp_path)
    status = supervisor.probe_human_session()
    assert not status.ok and status.state == "unavailable"
    assert supervisor.start_sidecar().state == "blocked"


def test_running_and_adopted_sidecars_are_preserved(tmp_path):
    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path)
    supervisor._sidecar_process = type("Running", (), {"poll": lambda _self: None})()
    with pytest.raises(ValueError, match="running_sidecar"):
        supervisor.prepare_human_session(
            driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
        )
    supervisor._sidecar_process = None
    supervisor._read_health = lambda: ProbeResult("sidecar", True, "running")
    with pytest.raises(ValueError, match="running_sidecar"):
        supervisor.prepare_human_session(
            driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
        )
    assert not campaign_path(tmp_path).exists()
    HumanSessionPermit.prepare(
        campaign_path(tmp_path),
        driver_id="private-driver",
        assistance=ASSISTANCE,
        voice_bank=str(bank),
    )
    assert supervisor.start_sidecar().state == "restart_required"
    assert supervisor._sidecar_process is None


def test_restart_inspection_and_disclosure_do_not_create_another_campaign(tmp_path):
    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path)
    supervisor.prepare_human_session(
        driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
    )
    replacement = supervisor_at(tmp_path)
    assert replacement.human_session_status()["phase"] == "prepared"
    assert replacement.revoke_human_session()["phase"] == "aborted"
    with pytest.raises(ValueError, match="campaign_already_exists"):
        replacement.prepare_human_session(
            driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
        )
    assert campaign_path(tmp_path).exists()


@pytest.mark.parametrize("end", ["closed", "aborted"])
@pytest.mark.parametrize("normal_drills", [False, True])
def test_terminal_receipt_preserves_ordinary_start_without_resetting_campaign(
    tmp_path, end, normal_drills
):
    bank = bank_at(tmp_path / "selected")
    config = GamePointConfig(
        paths=LauncherPaths(tmp_path),
        token="synthetic-test-token",
        reference_archive="normal-magione.json",
        coach_drills=normal_drills,
    )
    supervisor = supervisor_at(tmp_path, config=config)
    normal_env = supervisor.sidecar_environment()
    supervisor.prepare_human_session(
        driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
    )
    if end == "closed":
        supervisor.close_human_session({"driver_id": "private-driver", "assistance": ASSISTANCE})
    else:
        supervisor.revoke_human_session()
    before = campaign_path(tmp_path).read_bytes()
    (
        bank / "manifest.json"
    ).unlink()  # a spent campaign must not require its bank for normal START.
    calls = []

    class Running:
        pid = 12345

        def poll(self):
            return None

    supervisor._popen = lambda *_args, **kwargs: calls.append(kwargs) or Running()
    assert supervisor.start_sidecar().state == "starting"
    assert calls[0]["env"] == normal_env
    assert calls[0]["env"]["AC_COPILOT_COACH_DRILLS"] == ("1" if normal_drills else "0")
    assert not supervisor._sidecar_human_session
    assert campaign_path(tmp_path).read_bytes() == before
    supervisor._sidecar_process = None
    with pytest.raises(ValueError, match="campaign_already_exists"):
        supervisor.prepare_human_session(driver_id="private-driver", assistance=ASSISTANCE)


def test_voice_status_tracks_the_actual_owned_child_after_the_campaign_ends(tmp_path):
    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path)
    supervisor.prepare_human_session(
        driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
    )

    class OwnedChild:
        pid = 12345
        running = True

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.running = False

        def wait(self, timeout):
            return 0

    child = OwnedChild()
    calls = []
    supervisor._popen = lambda *_args, **kwargs: calls.append(kwargs) or child
    assert supervisor.start_sidecar().state == "starting"
    assert calls[0]["env"]["AC_COPILOT_VOICE_BANK"] == str(bank)
    assert calls[0]["env"]["AC_COPILOT_PRACTICE_PERMIT"] == str(campaign_path(tmp_path))
    assert supervisor._sidecar_human_session
    supervisor.revoke_human_session()
    assert "AC_COPILOT_PRACTICE_PERMIT" not in supervisor.sidecar_environment()
    assert supervisor._voice_playback_requested()  # the actual owned child has not exited yet.
    assert supervisor.stop_sidecar().state == "stopped"
    assert not supervisor._voice_playback_requested()


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


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_actual_modal_requires_every_field_and_a_fresh_end_declaration(tmp_path, tk_root, scaling):
    supervisor = supervisor_at(tmp_path)
    bank_at(tmp_path / "voice-banks" / "test-bank")
    tk_root.tk.call("tk", "scaling", scaling)
    view = _open_human_session_window(supervisor, parent=tk_root)
    try:
        view.window.update()
        assert view._driver.get() == "" and all(var.get() == "" for var in view._vars.values())
        view._prepare.invoke()
        assert not campaign_path(tmp_path).exists()
        view._driver.set("private-driver")
        for key, variable in view._vars.items():
            choices = view._choices[key]
            if choices:
                variable.set(
                    next(label for label, value in choices.items() if value == ASSISTANCE[key])
                )
            else:
                variable.set(ASSISTANCE[key])
        view._prepare.invoke()
        assert supervisor.human_session_status()["phase"] == "prepared"
        assert str(view._prepare.cget("state")) == "disabled"
        assert view._driver.get() == "" and all(var.get() == "" for var in view._vars.values())
        view._end.invoke()  # an empty end form cannot silently confirm the start values.
        assert supervisor.human_session_status()["phase"] == "prepared"
        for control in [view._prepare, view._end, view._revoke, *view._selectors]:
            assert control.winfo_ismapped()
            assert control.winfo_y() + control.winfo_height() <= control.master.winfo_height()
        view._revoke.invoke()
        assert supervisor.human_session_status()["phase"] == "aborted"
        assert str(view._prepare.cget("state")) == "disabled"
    finally:
        view.window.destroy()


@pytest.mark.parametrize("mismatch", [False, True])
def test_actual_sealed_capture_keeps_a_fresh_end_form_available(
    tmp_path, monkeypatch, tk_root, mismatch
):
    from tests.test_human_session import native_identity
    from tests.test_practice_attribution import complete_archive

    bank = bank_at(tmp_path / "selected")
    permit = HumanSessionPermit.prepare(
        campaign_path(tmp_path),
        driver_id="private-driver",
        assistance=ASSISTANCE,
        voice_bank=str(bank),
    )
    archive_root = tmp_path / "journal" / "laps"
    archive_root.mkdir(parents=True)
    permit.admit(native_identity(), archive_root=archive_root)
    for ordinal in range(1, 11):
        path = complete_archive(permit, archive_root, ordinal)
        permit.accept_archive(path)
    assert permit.seal_capture()["reason"] == "awaiting_end_declaration"
    supervisor = supervisor_at(tmp_path)
    assert supervisor.probe_human_session().state == "awaiting_end_declaration"
    view = _open_human_session_window(supervisor, parent=tk_root)
    try:
        assert view._driver.get() == "" and all(var.get() == "" for var in view._vars.values())
        assert str(view._end.cget("state")) == "normal"
        assert str(view._prepare.cget("state")) == "disabled"
        assert "unverified" in view._status.cget("text")
        view._driver.set("private-driver")
        for key, variable in view._vars.items():
            choices = view._choices[key]
            value = "9" if mismatch and key == "abs_level" else ASSISTANCE[key]
            if choices:
                variable.set(next(label for label, chosen in choices.items() if chosen == value))
            else:
                variable.set(value)
        view._end.invoke()
        status = supervisor.human_session_status(private=True)
        assert status["end_confirmed"] is (not mismatch)
        assert str(view._end.cget("state")) == "disabled"
        assert str(view._prepare.cget("state")) == "disabled"
    finally:
        view.window.destroy()


def test_frozen_bundle_includes_shared_human_session_authority(tmp_path):
    args = build_pyinstaller_args(tmp_path)
    assert "tools.human_session" in args


@pytest.mark.parametrize("mismatch", [False, True])
def test_automatically_aborted_session_keeps_first_end_declaration_available(
    tmp_path, tk_root, mismatch
):
    from tests.test_human_session import native_identity

    bank = bank_at(tmp_path / "selected")
    supervisor = supervisor_at(tmp_path)
    supervisor.prepare_human_session(
        driver_id="private-driver", assistance=ASSISTANCE, voice_bank=str(bank)
    )
    permit = HumanSessionPermit.load(campaign_path(tmp_path))
    archive_root = tmp_path / "journal" / "laps"
    archive_root.mkdir(parents=True)
    permit.admit(native_identity(), archive_root=archive_root)
    permit.revoke("native_session_disconnected")  # an automatic transport stop, not a UI action.
    view = _open_human_session_window(supervisor, parent=tk_root)
    try:
        before = supervisor.human_session_status(private=True)
        assert before["phase"] == "aborted" and not before["end_recorded"]
        assert view._driver.get() == "" and all(var.get() == "" for var in view._vars.values())
        assert str(view._prepare.cget("state")) == "disabled"
        assert str(view._end.cget("state")) == "normal"
        assert str(view._revoke.cget("state")) == "disabled"
        assert "permanently unverified" in view._status.cget("text")
        view._driver.set("private-driver")
        for key, variable in view._vars.items():
            choices = view._choices[key]
            value = "9" if mismatch and key == "abs_level" else ASSISTANCE[key]
            variable.set(
                next(label for label, chosen in choices.items() if chosen == value)
                if choices
                else value
            )
        view._end.invoke()  # invokes the real supervisor close_campaign adapter.
        after = supervisor.human_session_status(private=True)
        assert after["phase"] == "aborted" and after["reason"] == "native_session_disconnected"
        assert after["end_recorded"] and after["end_confirmed"] is (not mismatch)
        assert after["accepted_laps"] == [] and after["attempted_laps"] == 0
        saved = json.loads(campaign_path(tmp_path).read_bytes())
        assert saved["end_declaration"]["driver_id"] == "private-driver"
        assert saved["end_declaration"]["assistance"]["abs_level"] == ("9" if mismatch else "3")
        assert "end_recorded" not in supervisor.human_session_status()
        assert str(view._end.cget("state")) == "disabled"
        assert str(view._prepare.cget("state")) == "disabled"
        assert "permanently unverified" in view._status.cget("text")
    finally:
        view.window.destroy()


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_main_launcher_exposes_human_session_without_hiding_existing_actions(tk_root, scaling):
    import tkinter as tk

    from tools.rig_launcher.preview import _NOOP_ACTIONS
    from tools.rig_launcher.view import build_launcher_view

    window = tk.Toplevel(tk_root)
    window.withdraw()
    window.tk.call("tk", "scaling", scaling)
    try:
        view = build_launcher_view(
            window,
            actions={
                **_NOOP_ACTIONS,
                "human_session": lambda: None,
                "moza_offline_report": lambda: None,
            },
            status_path="status.json",
        )
        view.fit_window()
        window.deiconify()
        window.update()

        def buttons(parent):
            for child in parent.winfo_children():
                if isinstance(child, tk.Button):
                    yield child
                yield from buttons(child)

        found = list(buttons(window))
        assert {button.cget("text") for button in found} >= {
            "HUMAN SESSION",
            "OFFLINE REPORT",
            "▶ START",
            "SETTINGS",
        }
        for button in found:
            assert button.winfo_ismapped()
            assert button.winfo_x() + button.winfo_width() <= button.master.winfo_width()
            assert button.winfo_y() + button.winfo_height() <= button.master.winfo_height()
    finally:
        window.destroy()
