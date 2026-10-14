"""Offline harness construction and owned-stop checks. No apps, audio or real lock access."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.ac_harness import live_voice


@pytest.fixture
def harness():
    return live_voice


@pytest.fixture
def prepared(tmp_path, monkeypatch, harness):
    original = tmp_path / "production"
    original.mkdir()
    settings = {
        "voice_channel_map": "5,6",
        "setup_store": "manual.jsonl",
        "start_simhub": True,
        "custom_manual": {"preserve": True},
        "external_bind": "127.0.0.1",
    }
    settings_path = original / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    reference = tmp_path / "reference.json"
    reference.write_text("{}", encoding="utf-8")
    bank = tmp_path / "bank"
    bank.mkdir()
    config = tmp_path / "capture.json"
    config.write_text(
        json.dumps(
            {
                "reference_archive": str(reference),
                "bank_dir": str(bank),
                "output_device": "Exact device",
                "output_host_api": "WASAPI",
                "output_channel_map": [5],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(harness, "read_rig_session_owner", lambda path: {"pid": 51316})
    env = {
        "LOCALAPPDATA": str(tmp_path),
        "AC_COPILOT_GAME_POINT_DIR": str(original),
        "AC_COPILOT_SIDECAR_TOKEN": "synthetic-token",
        "KEEP_CUSTOM": "unchanged",
        "AC_COPILOT_SIDECAR_SERIAL_PORT": "COM_TEST",
    }
    sup = harness.prepare_run(config, tmp_path / "run", 51316, environ=env)
    return sup, settings_path, settings, config, env


def test_canonical_command_settings_and_env_parity(prepared, harness):
    sup, settings_path, settings, config, env = prepared
    assert json.loads(settings_path.read_text()) == settings
    saved = json.loads(sup.paths.settings_path.read_text())
    assert saved["custom_manual"] == {"preserve": True}
    assert saved["setup_store"] == str(settings_path.parent / "manual.jsonl")
    assert not sup.config.start_simhub
    child_env = sup.sidecar_environment()
    assert child_env["KEEP_CUSTOM"] == "unchanged"
    assert child_env["AC_COPILOT_SIDECAR_TOKEN"] == "synthetic-token"
    assert child_env["AC_COPILOT_COACH_V2"] == "1"
    assert child_env["AC_COPILOT_VOICE_CHANNEL_MAP"] == "5"
    assert child_env["AC_COPILOT_VOICE_DEVICE"] == "Exact device"
    assert child_env["AC_COPILOT_START_SIMHUB"] == "0"
    command = sup.sidecar_command()
    original = harness.GamePointSupervisor.sidecar_command(sup)
    assert command[command.index("--") + 1 :] == original[3:]
    assert command[1:4] == ["-B", "-m", harness.INSTRUMENTED_SIDECAR_MODULE]
    assert "--tap" in command and "--stop-file" in command
    receipt = (sup.run_dir / "launcher-receipt.json").read_text()
    assert "synthetic-token" not in receipt
    assert not sup.tap_path.exists() and not sup.stop_path.exists()
    effective_capture = json.loads((sup.run_dir / "capture-config.json").read_text())
    assert effective_capture["instrument_tap"] == str(sup.tap_path)
    with pytest.raises(FileExistsError):
        harness.prepare_run(config, sup.run_dir, 51316, environ=env)


def test_explicit_observer_mode_uses_existing_producer_switch(prepared, harness):
    sup, _, _, config, env = prepared
    raw = json.loads(config.read_text())
    raw["producer_mode"] = "observer"
    config.write_text(json.dumps(raw))
    observer = harness.prepare_run(config, sup.run_dir.with_name("observer"), 51316, environ=env)
    assert observer.sidecar_environment()["AC_COPILOT_COACH_V2"] == "0"
    receipt = json.loads((observer.run_dir / "launcher-receipt.json").read_text())
    assert receipt["producer_mode"] == "observer" and receipt["coach_v2"] is False


@pytest.mark.parametrize("mode", [None, "unknown", 1])
def test_invalid_producer_mode_fails_before_creating_run(prepared, harness, mode):
    sup, _, _, config, env = prepared
    raw = json.loads(config.read_text())
    raw["producer_mode"] = mode
    config.write_text(json.dumps(raw))
    target = sup.run_dir.with_name("invalid")
    with pytest.raises(ValueError, match="producer_mode"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


def test_observer_refuses_inherited_alien_line_that_would_force_coach_v2(prepared, harness):
    sup, _, _, config, env = prepared
    raw = json.loads(config.read_text())
    raw["producer_mode"] = "observer"
    config.write_text(json.dumps(raw))
    env["AC_COPILOT_ALIEN_LINE"] = "owned-alien-line.json"
    target = sup.run_dir.with_name("invalid")
    with pytest.raises(ValueError, match="alien_line"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


@pytest.mark.parametrize("key", ["output_channel_map", "output_device", "output_host_api"])
def test_missing_route_fails_before_creating_run(prepared, harness, key):
    sup, _, _, config, env = prepared
    raw = json.loads(config.read_text())
    raw.pop(key)
    config.write_text(json.dumps(raw))
    target = sup.run_dir.with_name("invalid")
    with pytest.raises(ValueError, match="explicitly pin"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


def test_prepare_refuses_another_owner_before_writing_run(prepared, harness, monkeypatch):
    sup, _, _, config, env = prepared
    monkeypatch.setattr(harness, "read_rig_session_owner", lambda path: {"pid": 2})
    target = sup.run_dir.with_name("invalid")
    with pytest.raises(RuntimeError, match="rig owner mismatch"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


def test_run_must_be_independent_of_production_settings(prepared, harness):
    _, settings, _, config, env = prepared
    target = settings.parent / "run"
    with pytest.raises(ValueError, match="independent"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


@pytest.mark.parametrize("value", [[], None, 1, "scalar"])
def test_capture_config_must_be_object_before_creating_run(prepared, harness, value):
    sup, _, _, config, env = prepared
    config.write_text(json.dumps(value))
    target = sup.run_dir.with_name("invalid")
    with pytest.raises(ValueError, match="must be an object"):
        harness.prepare_run(config, target, 51316, environ=env)
    assert not target.exists()


@pytest.mark.parametrize("observed", [None, {}, {"pid": 1}, {"cwd": "unknown"}])
def test_owner_mismatch_blocks_before_any_spawn(prepared, harness, monkeypatch, observed):
    sup, *_ = prepared
    monkeypatch.setattr(harness, "read_rig_session_owner", lambda path: observed)
    sup._popen = lambda *args, **kwargs: pytest.fail("spawned")
    assert sup.start_sidecar().state == "blocked"
    assert any(check.state == "owner_mismatch" for check in sup.preflight())


def test_stop_signals_only_owned_wrapper_before_canonical_cleanup(prepared):
    sup, *_ = prepared
    calls = []

    class Process:
        pid = 9001
        code = None

        def poll(self):
            return self.code

        def wait(self, *, timeout):
            assert sup.stop_path.exists()
            calls.append("wait")
            self.code = 0

        def terminate(self):
            pytest.fail("terminated graceful child")

        def kill(self):
            pytest.fail("killed graceful child")

    sup._sidecar_process = Process()
    assert sup.stop_sidecar().ok
    assert calls == ["wait"]
    assert sup._sidecar_process is None
    assert json.loads(sup.stop_path.read_text())["sidecar_pid"] == 9001


def test_adopted_peer_is_never_signalled(prepared):
    sup, *_ = prepared
    assert sup._sidecar_process is None
    assert sup.stop_sidecar().ok
    assert not sup.stop_path.exists()


def test_timeout_is_explicit_and_cleanup_only_targets_owned_process(prepared):
    sup, *_ = prepared
    calls = []

    class Process:
        pid = 9002
        code = None

        def poll(self):
            return self.code

        def wait(self, *, timeout):
            if self.code is None:
                raise subprocess.TimeoutExpired("owned", timeout)

        def terminate(self):
            calls.append(self.pid)
            self.code = 0

    sup._sidecar_process = Process()
    result = sup.stop_sidecar()
    assert not result.ok and result.state == "graceful_stop_timeout"
    assert calls == [9002]


def test_main_uses_canonical_gui_and_cleanup(harness, monkeypatch, tmp_path):
    calls = []
    sup = SimpleNamespace(close=lambda: calls.append("close"))
    monkeypatch.setattr(harness, "prepare_run", lambda *args: sup)
    monkeypatch.setattr(harness, "run_gui", lambda supervisor: calls.append("gui") or 0)
    assert (
        harness.main(
            ["--run-dir", str(tmp_path), "--owner-pid", "51316", "--capture-config", "config.json"]
        )
        == 0
    )
    assert calls == ["gui", "close"]


def test_main_refuses_adopted_sidecar_and_closes_without_opening_ui(harness, monkeypatch, tmp_path):
    calls = []
    sup = SimpleNamespace(
        _sidecar_process=None,
        start_sidecar=lambda: SimpleNamespace(ok=True),
        close=lambda: calls.append("close"),
    )
    monkeypatch.setattr(harness, "prepare_run", lambda *args: sup)
    monkeypatch.setattr(harness, "run_gui", lambda supervisor: pytest.fail("opened UI"))
    with pytest.raises(RuntimeError, match="owned instrumented sidecar did not start"):
        harness.main(
            [
                "--run-dir",
                str(tmp_path),
                "--owner-pid",
                "51316",
                "--capture-config",
                "config.json",
                "--start-sidecar",
            ]
        )
    assert calls == ["close"]


@pytest.mark.parametrize(
    "module, argument",
    [
        ("tools.ac_harness.live_voice", "--owner-pid"),
        ("tools.ai_sidecar.voice.instrumented_sidecar", "--tap"),
    ],
)
def test_package_entrypoint_help_does_not_start_devices_or_ui(module, argument):
    completed = subprocess.run(
        [sys.executable, "-B", "-m", module, "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert argument in completed.stdout
