from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tools.rig_launcher.app import config_from_args, run_sidecar_child
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
    build_pyinstaller_args,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _Proc:
    pid = 4242
    terminated = False

    def poll(self) -> int | None:
        if self.terminated:
            return 0
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.terminated = True
        return 0

    def kill(self) -> None:
        self.terminated = True


def test_sidecar_command_uses_env_for_token_and_voice(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="secret-token",
        reference_archive="ref.json",
        voice_bank="voice-bank",
        voice_tts=True,
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(cfg, environ={}, python_executable="python")

    command = sup.sidecar_command()
    env = sup.sidecar_environment()

    assert "--token" not in command
    assert "secret-token" not in command
    assert command == [
        "python",
        "-m",
        "tools.ai_sidecar",
        "--port",
        "8765",
        "--external-bind",
        "0.0.0.0",
    ]
    assert env["AC_COPILOT_SIDECAR_TOKEN"] == "secret-token"
    assert env["AC_COPILOT_REFERENCE_ARCHIVE"] == "ref.json"
    assert env["AC_COPILOT_VOICE_BANK"] == "voice-bank"
    assert env["AC_COPILOT_VOICE_TTS"] == "1"


def test_frozen_sidecar_command_uses_bundled_child_mode(tmp_path: Path) -> None:
    cfg = GamePointConfig(external_bind="127.0.0.1", paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg,
        environ={},
        python_executable="AC-Copilot-Game-Point.exe",
        frozen=True,
    )

    command = sup.sidecar_command()

    assert command[:2] == ["AC-Copilot-Game-Point.exe", "--sidecar-child"]
    assert "-m" not in command
    assert "tools.ai_sidecar" not in command


def test_preflight_blocks_external_bind_without_token(tmp_path: Path) -> None:
    cfg = GamePointConfig(external_bind="0.0.0.0", token=None, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    rows = {row.name: row for row in sup.preflight()}
    start = sup.start_sidecar()

    assert rows["sidecar_token"].ok is False
    assert start.state == "blocked"
    assert "AC_COPILOT_SIDECAR_TOKEN" in start.detail


def test_preflight_blocks_voice_tts_without_reference(tmp_path: Path) -> None:
    cfg = GamePointConfig(voice_tts=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    rows = {row.name: row for row in sup.preflight()}
    voice = sup.probe_voice()

    assert rows["voice_reference"].ok is False
    assert voice.state == "missing_reference"


def test_status_reads_health_and_writes_status_file(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        assert timeout == 1.0
        return _Response({"status": "ok", "connected_peers": 2, "screen_peers": 1})

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.sidecar.ok is True
    assert status.screen.ok is True
    assert status.screen.state == "connected"
    saved = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert saved["screen"]["state"] == "connected"
    assert saved["log_path"].endswith("sidecar.log")


def test_start_sidecar_writes_to_predictable_log_dir(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        calls.append({"args": args, "kwargs": kwargs})
        return _Proc()

    sup = GamePointSupervisor(cfg, environ={}, popen=fake_popen, python_executable="python")
    result = sup.start_sidecar()
    sup.close()

    assert result.state == "starting"
    assert (tmp_path / "logs").is_dir()
    assert calls[0]["kwargs"]["stdout"].name == str(tmp_path / "logs" / "sidecar.log")
    assert "AC_COPILOT_SIDECAR_TOKEN" in calls[0]["kwargs"]["env"]


def test_close_terminates_supervised_sidecar(tmp_path: Path) -> None:
    proc = _Proc()
    cfg = GamePointConfig(external_bind="127.0.0.1", paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, popen=lambda *a, **kw: proc)

    sup.start_sidecar()
    sup.close()

    assert proc.terminated is True


def test_simhub_absence_is_visible_but_not_fatal(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={"ProgramFiles": str(tmp_path / "missing")})

    result = sup.probe_simhub(start=True)

    assert result.ok is True
    assert result.state == "absent"
    assert "not found" in result.detail


def test_simhub_starts_when_requested_and_executable_exists(tmp_path: Path) -> None:
    exe = tmp_path / "SimHub" / "SimHubWPF.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    calls: list[Any] = []
    cfg = GamePointConfig(start_simhub=True, paths=LauncherPaths(tmp_path))

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        calls.append((args, kwargs))
        return _Proc()

    sup = GamePointSupervisor(
        cfg,
        environ={"ProgramFiles": str(tmp_path)},
        popen=fake_popen,
    )

    result = sup.probe_simhub(start=True)

    assert result.state == "started"
    assert calls[0][0][0] == [str(exe)]


def test_config_from_env_and_args_uses_launcher_overrides(tmp_path: Path, monkeypatch) -> None:
    from tools.rig_launcher.app import build_arg_parser

    monkeypatch.setenv("AC_COPILOT_SIDECAR_TOKEN", "token")
    monkeypatch.setenv("AC_COPILOT_VOICE_BANK", "bank")
    monkeypatch.setenv("AC_COPILOT_VOICE_TTS", "1")
    args = build_arg_parser().parse_args(
        ["--port", "9999", "--external-bind", "127.0.0.1", "--log-dir", str(tmp_path)]
    )

    cfg = config_from_args(args)

    assert cfg.port == 9999
    assert cfg.external_bind == "127.0.0.1"
    assert cfg.token == "token"
    assert cfg.voice_bank == "bank"
    assert cfg.voice_tts is True
    assert cfg.paths is not None
    assert cfg.paths.root == tmp_path


def test_build_pyinstaller_args_targets_launcher_entrypoint(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert "--onefile" in args
    assert "--noconsole" in args
    assert "tools.ai_sidecar" in args
    assert str(tmp_path / "tools" / "rig_launcher" / "__main__.py") == args[-1]


def test_sidecar_child_entrypoint_rewrites_sys_argv(monkeypatch) -> None:
    from tools.ai_sidecar import server

    seen: dict[str, list[str]] = {}

    def fake_main() -> None:
        import sys

        seen["argv"] = list(sys.argv)

    monkeypatch.setattr(server, "main", fake_main)

    assert run_sidecar_child(["--port", "8765"]) == 0
    assert seen["argv"] == ["ai_sidecar", "--port", "8765"]


def test_hotspot_probe_parses_windows_state(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"state":"On","client_count":1}',
            stderr="",
        )

    sup = GamePointSupervisor(cfg, run=fake_run)
    result = sup.probe_hotspot()

    if result.state == "skipped":
        assert result.ok is True
    else:
        assert result.ok is True
        assert result.state == "on"
        assert "clients=1" in result.detail
