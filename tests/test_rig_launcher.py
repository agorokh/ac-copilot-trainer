from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest

import tools.rig_launcher.supervisor as supervisor_module
from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner
from tools.rig_launcher.app import (
    _open_path,
    _resilient_start_accepted,
    config_from_args,
    main,
    render_setup_diff_lines,
    run_gui,
    run_resilient_launch_child,
    run_setup_diff_gui,
    run_sidecar_child,
)
from tools.rig_launcher.install import (
    SHORTCUT_NAME,
    default_exe_path,
    install_desktop_shortcut,
)
from tools.rig_launcher.settings import (
    LauncherSettings,
    default_settings_payload,
    ensure_settings_file,
    update_settings,
)
from tools.rig_launcher.supervisor import (
    _WINDOWS_NO_WINDOW,
    GamePointConfig,
    GamePointStatus,
    GamePointSupervisor,
    LauncherPaths,
    ProbeResult,
    _repo_root,
    _resolve_launcher_path,
    _subprocess_kwargs,
    build_pyinstaller_args,
    render_status_lines,
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


def _refused_urlopen(_url: str, timeout: float) -> _Response:
    """Health probe that always fails — keeps spawn-path tests hermetic.

    ``start_sidecar`` now probes ``/health`` before spawning so it can adopt an already-running
    sidecar instead of double-binding the port. Tests that assert a *spawn* inject this so the
    probe deterministically misses regardless of whatever is (or isn't) listening on 8765.
    """
    del timeout
    raise OSError("connection refused")


def _serving_urlopen(_target: object, timeout: float) -> _Response:
    """A sidecar that answers 200 for any GET — used by managed-tablet tests where probe_tablet
    now ground-truth-probes /tablet/dash (returns 200 → the dash actually loads)."""
    del timeout
    return _Response({"status": "ok"})


def _no_simhub_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
    """`tasklist` stub reporting no SimHub — keeps probe_simhub tests off the real machine.

    ``_simhub_running()`` shells out to the real ``tasklist`` by default, so on a dev box with
    SimHub actually running the absence/start assertions would flake. Inject this for determinism.
    """
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


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
    assert env["AC_COPILOT_REFERENCE_ARCHIVE"] == str((tmp_path / "ref.json").resolve())
    assert env["AC_COPILOT_VOICE_BANK"] == str((tmp_path / "voice-bank").resolve())
    assert env["AC_COPILOT_VOICE_TTS"] == "1"


def test_sidecar_command_includes_serial_port_when_configured(tmp_path: Path) -> None:
    """Issue #463: the launcher forwards --serial-port so the screen uses USB, not hotspot."""
    cfg = GamePointConfig(serial_port="COM6", paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, python_executable="python")

    command = sup.sidecar_command()

    assert command[-2:] == ["--serial-port", "COM6"]


def test_config_reads_serial_port_from_env(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_SIDECAR_SERIAL_PORT": "COM6"},
        paths=LauncherPaths(tmp_path),
    )
    assert cfg.serial_port == "COM6"


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


def test_resilient_command_routes_source_and_frozen_launcher(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        resilient_car="ks_porsche_911_gt3_r_2016",
        resilient_track="spa",
        resilient_layout="gp",
        resilient_cm_exe=r"D:\Portable CM\Content Manager.exe",
        rig_lock_path=tmp_path / "rig-session.lock",
        paths=LauncherPaths(tmp_path),
    )

    source = GamePointSupervisor(cfg, environ={}, python_executable="python")
    frozen = GamePointSupervisor(
        cfg,
        environ={},
        python_executable="AC-Copilot-Game-Point.exe",
        frozen=True,
    )

    assert source.resilient_command() == [
        "python",
        "-m",
        "tools.ac_harness.resilient_launch",
        "--car",
        "ks_porsche_911_gt3_r_2016",
        "--track",
        "spa",
        "--layout",
        "gp",
        "--cm-exe",
        r"D:\Portable CM\Content Manager.exe",
        "--rig-lock-path",
        str(tmp_path / "rig-session.lock"),
        "--rig-release-path",
        str(tmp_path / "rig-session.release"),
        "--rig-lock-timeout",
        "1.0",
    ]
    assert frozen.resilient_command()[:2] == [
        "AC-Copilot-Game-Point.exe",
        "--resilient-launch-child",
    ]


def test_resilient_command_resolves_relative_cm_path_from_launcher_root(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        resilient_cm_exe="portable/Content Manager.exe",
        paths=LauncherPaths(tmp_path),
    )

    command = GamePointSupervisor(cfg, environ={}, python_executable="python").resilient_command()

    cm_flag = command.index("--cm-exe")
    assert command[cm_flag + 1] == str((tmp_path / "portable/Content Manager.exe").resolve())


def test_invalid_relative_cm_path_blocks_resilient_start(tmp_path: Path) -> None:
    spawned: list[bool] = []
    cfg = GamePointConfig(
        resilient_car="ks_porsche_911_gt3_r_2016",
        resilient_track="spa",
        resilient_cm_exe="../outside/Content Manager.exe",
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(
        cfg,
        environ={},
        popen=lambda *_args, **_kwargs: spawned.append(True),
        python_executable="python",
    )

    result = sup.start_resilient_session()
    status = sup._resilient_process_status()

    assert result.ok is False
    assert result.state == "unconfigured"
    assert "resilient_cm_exe" in result.detail
    assert status == result
    assert spawned == []
    with pytest.raises(ValueError, match="resilient_cm_exe"):
        sup.resilient_command()


def test_start_resilient_session_is_configured_and_detached(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    proc = _Proc()

    def fake_popen(command: list[str], **kwargs: Any) -> _Proc:
        calls.append((command, kwargs))
        return proc

    cfg = GamePointConfig(
        resilient_car="car",
        resilient_track="track",
        rig_lock_path=tmp_path / "rig-session.lock",
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(
        cfg,
        environ={},
        popen=fake_popen,
        python_executable="python",
    )

    release_path = tmp_path / "rig-session.release"
    release_path.touch()
    started = sup.start_resilient_session()
    running = sup._resilient_process_status()
    sup.close()

    assert started.state == "starting"
    assert started.ok is False
    assert running.state == "stabilizing"
    assert running.ok is False
    assert calls[0][0][-10:] == [
        "--car",
        "car",
        "--track",
        "track",
        "--rig-lock-path",
        str(tmp_path / "rig-session.lock"),
        "--rig-release-path",
        str(release_path),
        "--rig-lock-timeout",
        "1.0",
    ]
    assert not release_path.exists()
    assert calls[0][1]["cwd"] == str(_repo_root())
    assert (tmp_path / "logs" / "resilient-launch.log").exists()
    assert proc.terminated is False


@pytest.mark.parametrize("state", ["starting", "stabilizing", "running"])
def test_resilient_start_acceptance_is_distinct_from_readiness(state: str) -> None:
    result = ProbeResult("ac_session", False, state, "phase is not stable yet")

    assert _resilient_start_accepted(result) is True


@pytest.mark.parametrize("state", ["unconfigured", "start_failed", "busy_other_session", "unknown"])
def test_resilient_start_hard_failures_are_not_accepted(state: str) -> None:
    result = ProbeResult("ac_session", False, state, "hard failure")

    assert _resilient_start_accepted(result) is False


def test_start_resilient_session_requires_car_and_track(tmp_path: Path) -> None:
    sup = GamePointSupervisor(GamePointConfig(paths=LauncherPaths(tmp_path)), environ={})

    result = sup.start_resilient_session()

    assert result.ok is False
    assert result.state == "unconfigured"
    assert "resilient_car" in result.detail
    assert "resilient_track" in result.detail


def test_release_resilient_session_signals_detached_child(tmp_path: Path) -> None:
    lock_path = tmp_path / "rig-session.lock"
    proc = _Proc()
    cfg = GamePointConfig(
        resilient_car="car",
        resilient_track="track",
        rig_lock_path=lock_path,
        paths=LauncherPaths(tmp_path / "game-point"),
    )
    sup = GamePointSupervisor(cfg, environ={}, popen=lambda *_args, **_kwargs: proc)

    assert sup.start_resilient_session().state == "starting"
    released = sup.release_resilient_session()

    assert released.ok is True
    assert released.state == "release_requested"
    assert (tmp_path / "rig-session.release").exists()
    assert proc.terminated is False


def test_reopened_game_point_can_signal_detached_lock_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "rig-session.lock"
    cfg = GamePointConfig(
        resilient_car="car",
        resilient_track="track",
        rig_lock_path=lock_path,
        paths=LauncherPaths(tmp_path / "game-point"),
    )
    sup = GamePointSupervisor(cfg, environ={})
    owner = RigSessionOwner(
        pid=os.getpid(),
        cwd="detached-game-point",
        car="car",
        track="track",
        session_kind="resilient_launch",
    )

    with RigSessionLock(lock_path, owner=owner):
        released = sup.release_resilient_session()

    assert released.state == "release_requested"
    assert (tmp_path / "rig-session.release").exists()


def test_release_ac_refuses_unrelated_machine_wide_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "rig-session.lock"
    sup = GamePointSupervisor(
        GamePointConfig(
            resilient_car="car",
            resilient_track="track",
            rig_lock_path=lock_path,
            paths=LauncherPaths(tmp_path / "game-point"),
        ),
        environ={},
    )
    owner = RigSessionOwner(
        pid=os.getpid(),
        cwd="auto-drive-worktree",
        car="car",
        track="track",
        session_kind="auto_drive",
    )

    with RigSessionLock(lock_path, owner=owner):
        released = sup.release_resilient_session()

    assert released.ok is False
    assert released.state == "release_unsupported"
    assert not (tmp_path / "rig-session.release").exists()


def test_non_resilient_owner_is_busy_not_healthy_stable_ac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[bool] = []
    sup = GamePointSupervisor(
        GamePointConfig(
            resilient_car="car",
            resilient_track="track",
            paths=LauncherPaths(tmp_path / "game-point"),
        ),
        environ={},
        popen=lambda *_args, **_kwargs: spawned.append(True),
    )
    monkeypatch.setattr(
        sup,
        "_rig_session_owner",
        lambda: {
            "pid": 123,
            "cwd": "auto-drive-worktree",
            "session_kind": "auto_drive",
        },
    )

    status = sup._resilient_process_status()
    started = sup.start_resilient_session()

    assert status.ok is False
    assert status.state == "busy_other_session"
    assert "session_kind=auto_drive" in status.detail
    assert started == status
    assert spawned == []


def test_release_ac_signals_unknown_lock_owner_for_no_console_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    sup = GamePointSupervisor(
        GamePointConfig(
            resilient_car="car",
            resilient_track="track",
            rig_lock_path=tmp_path / "rig-session.lock",
            paths=LauncherPaths(tmp_path / "game-point"),
        ),
        environ={},
    )
    monkeypatch.setattr(sup, "_rig_session_owner", lambda: {"cwd": "unknown"})

    released = sup.release_resilient_session()

    assert released.ok is True
    assert released.state == "release_requested"
    assert (tmp_path / "rig-session.release").exists()


def test_unknown_rig_lock_status_is_visible_and_blocks_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[bool] = []
    cfg = GamePointConfig(
        resilient_car="car",
        resilient_track="track",
        rig_lock_path=tmp_path / "rig-session.lock",
        paths=LauncherPaths(tmp_path / "game-point"),
    )
    sup = GamePointSupervisor(
        cfg,
        environ={},
        popen=lambda *_args, **_kwargs: spawned.append(True),
    )
    monkeypatch.setattr(sup, "_rig_session_owner", lambda: {"cwd": "unknown"})

    status = sup._resilient_process_status()
    started = sup.start_resilient_session()

    assert status.ok is False
    assert status.state == "unknown"
    assert "lock status unavailable" in status.detail
    assert started == status
    assert spawned == []


def test_resilient_status_adopts_machine_wide_lock_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "rig-session.lock"
    cfg = GamePointConfig(
        resilient_car="configured-car",
        resilient_track="configured-track",
        rig_lock_path=lock_path,
        paths=LauncherPaths(tmp_path / "game-point"),
    )

    def fail_popen(*_args: Any, **_kwargs: Any) -> _Proc:
        raise AssertionError("an owned rig must not spawn a second resilient child")

    sup = GamePointSupervisor(cfg, environ={}, popen=fail_popen)
    owner = RigSessionOwner(
        pid=os.getpid(),
        cwd="other-game-point",
        car="live-car",
        track="live-track",
        started_at="2026-07-18T21:00:00Z",
        session_kind="resilient_launch",
        phase="stable",
    )
    with RigSessionLock(lock_path, owner=owner):
        status = sup._resilient_process_status()
        started = sup.start_resilient_session()

    assert status.ok is True
    assert status.state == "running"
    assert f"pid={os.getpid()}" in status.detail
    assert "live-car" in status.detail
    assert started == status


def test_resilient_status_stays_non_green_until_owner_publishes_stable(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "rig-session.lock"
    sup = GamePointSupervisor(
        GamePointConfig(
            resilient_car="car",
            resilient_track="track",
            rig_lock_path=lock_path,
            paths=LauncherPaths(tmp_path / "game-point"),
        ),
        environ={},
    )
    lock = RigSessionLock(
        lock_path,
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd="game-point",
            car="car",
            track="track",
            session_kind="resilient_launch",
            phase="stabilizing",
        ),
    )

    with lock:
        stabilizing = sup._resilient_process_status()
        lock.set_phase("stable")
        stable = sup._resilient_process_status()

    assert stabilizing.ok is False
    assert stabilizing.state == "stabilizing"
    assert stable.ok is True
    assert stable.state == "running"


def test_resilient_status_probes_rig_owner_outside_process_lock(
    tmp_path: Path, monkeypatch
) -> None:
    sup = GamePointSupervisor(
        GamePointConfig(paths=LauncherPaths(tmp_path)),
        environ={},
    )

    def owner() -> None:
        assert not sup._proc_lock._is_owned()  # type: ignore[attr-defined]
        return None

    monkeypatch.setattr(sup, "_rig_session_owner", owner)

    assert sup._resilient_process_status().state == "unconfigured"


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


def test_status_uses_sidecar_voice_health(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        voice_bank="bank",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        assert timeout == 1.0
        return _Response(
            {
                "status": "ok",
                "connected_peers": 1,
                "screen_peers": 1,
                "voice": {
                    "configured": True,
                    "enabled": True,
                    "state": "enabled",
                    "backend": "sounddevice",
                    "device_name": "5.1 Speakers (USB Sound Device)",
                    "host_api": "Windows WASAPI",
                    "bank_channels": 1,
                    "max_output_channels": 6,
                    "stream_channels": 6,
                    "channel_map": [3],
                },
            }
        )

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.voice.ok is True
    assert status.voice.state == "enabled"
    assert status.voice.detail == (
        "backend=sounddevice; device=5.1 Speakers (USB Sound Device) (Windows WASAPI); "
        "layout=1ch bank -> 6ch stream/6ch max map=[3]"
    )


def test_status_rejects_skipped_sidecar_voice_when_launcher_requested_voice(
    tmp_path: Path,
) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        voice_bank="bank",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "status": "ok",
                "connected_peers": 1,
                "screen_peers": 1,
                "voice": {
                    "configured": False,
                    "enabled": False,
                    "state": "skipped",
                },
            }
        )

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.ok is False
    assert status.voice.ok is False
    assert status.voice.state == "DISABLED"
    assert "requested" in status.voice.detail


def test_status_rejects_missing_voice_health_when_launcher_requested_voice(
    tmp_path: Path,
) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        voice_bank="bank",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response({"status": "ok", "connected_peers": 1, "screen_peers": 1})

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.ok is False
    assert status.voice.ok is False
    assert status.voice.state == "DISABLED"
    assert "no voice runtime status" in status.voice.detail


def test_status_rejects_observer_only_health_when_playback_requested(
    tmp_path: Path,
) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        voice_bank="bank",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "status": "ok",
                "connected_peers": 1,
                "screen_peers": 1,
                "voice": {
                    "configured": True,
                    "enabled": False,
                    "state": "observer_only",
                },
            }
        )

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.ok is False
    assert status.voice.ok is False
    assert status.voice.state == "DISABLED"
    assert "observer-only" in status.voice.detail


def test_status_accepts_observer_only_health_for_reference_only_launcher(
    tmp_path: Path,
) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "status": "ok",
                "connected_peers": 1,
                "screen_peers": 1,
                "voice": {
                    "configured": True,
                    "enabled": False,
                    "state": "observer_only",
                },
            }
        )

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.voice.ok is True
    assert status.voice.state == "observer_only"


def test_status_surfaces_disabled_voice_reason_and_overall_summary(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive="ref.json",
        voice_bank="bank",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "status": "ok",
                "connected_peers": 1,
                "screen_peers": 1,
                "voice": {
                    "configured": True,
                    "enabled": False,
                    "state": "disabled",
                    "disabled_reason": "manifest version 1 is not supported by schema 2",
                    "backend": "rtmixer",
                },
            }
        )

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()
    lines = render_status_lines(status)

    assert status.ok is False
    assert status.voice.ok is False
    assert status.voice.state == "DISABLED"
    assert "manifest version 1" in status.voice.detail
    assert lines[0] == "overall: needs_attention"
    assert any(line.startswith("voice: DISABLED - manifest version 1") for line in lines)


def test_read_health_tolerates_non_utf8_response_bytes(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        paths=LauncherPaths(tmp_path),
    )

    class BadUtf8Response:
        def __enter__(self) -> BadUtf8Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"\xff\xfe not json"

    sup = GamePointSupervisor(cfg, environ={}, urlopen=lambda _url, timeout: BadUtf8Response())
    result = sup._read_health()

    assert result.ok is False
    assert result.state == "unreachable"


def test_read_health_rejects_non_object_payload(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        paths=LauncherPaths(tmp_path),
    )

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response([])

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    result = sup._read_health()

    assert result.ok is False
    assert result.state == "unreachable"
    assert "not an object" in (result.detail or "")


def test_subprocess_kwargs_adds_create_no_window_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(supervisor_module.os, "name", "nt")
    kwargs = _subprocess_kwargs(capture_output=True, text=True)
    assert kwargs["creationflags"] == _WINDOWS_NO_WINDOW


def test_status_polls_concrete_external_bind_health(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="192.168.137.1",
        token="token",
        paths=LauncherPaths(tmp_path),
    )
    seen: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        del timeout
        seen.append(url)
        return _Response({"status": "ok", "connected_peers": 2, "screen_peers": 1})

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    status = sup.poll_status()

    assert status.sidecar.ok is True
    assert seen == ["http://192.168.137.1:8765/health"]


def test_status_polls_loopback_for_wildcard_external_bind(tmp_path: Path) -> None:
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        paths=LauncherPaths(tmp_path),
    )
    seen: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        del timeout
        seen.append(url)
        return _Response({"status": "ok", "connected_peers": 2, "screen_peers": 1})

    sup = GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)
    sup.poll_status()

    assert seen == ["http://127.0.0.1:8765/health"]


def test_start_sidecar_writes_to_predictable_log_dir(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        calls.append({"args": args, "kwargs": kwargs})
        return _Proc()

    sup = GamePointSupervisor(
        cfg, environ={}, popen=fake_popen, urlopen=_refused_urlopen, python_executable="python"
    )
    result = sup.start_sidecar()
    sup.close()

    assert result.state == "starting"
    assert (tmp_path / "logs").is_dir()
    assert calls[0]["kwargs"]["stdout"].name == str(tmp_path / "logs" / "sidecar.log")
    assert "AC_COPILOT_SIDECAR_TOKEN" in calls[0]["kwargs"]["env"]


def test_start_sidecar_adopts_healthy_existing_instance(tmp_path: Path) -> None:
    """Clicking Start when a sidecar is already healthy must adopt it, never spawn a duplicate.

    A second spawn would bind the same port and crash the child with WinError 10048 — exactly the
    failure in the rig log. Guards that regression: a healthy /health probe → no popen call.
    """
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))
    spawned: list[Any] = []

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        spawned.append((args, kwargs))
        return _Proc()

    def healthy_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response({"status": "ok", "connected_peers": 1, "screen_peers": 1})

    sup = GamePointSupervisor(
        cfg, environ={}, popen=fake_popen, urlopen=healthy_urlopen, python_executable="python"
    )
    result = sup.start_sidecar()

    assert spawned == []  # no duplicate spawn → no WinError 10048
    assert result.ok is True
    assert result.state == "running"
    assert "adopted" in (result.detail or "")
    assert sup._sidecar_process is None
    assert sup._log_handles == []


def test_start_sidecar_adoption_closes_stale_log_handles(tmp_path: Path) -> None:
    """Adopting after a prior supervised spawn must close the leftover log handle, not leak it.

    Regression for the Qodo finding on PR #387: the adopt early-return ran before
    ``_close_log_handles()``, so a handle opened by an earlier spawn stayed open for the launcher's
    lifetime (kept sidecar.log held open). The cleanup now precedes the health probe.
    """
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))
    health = {"ok": False}

    def staged_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        if not health["ok"]:
            raise OSError("connection refused")
        return _Response({"status": "ok", "connected_peers": 1, "screen_peers": 1})

    procs: list[_Proc] = []

    def fake_popen(*_args: Any, **_kwargs: Any) -> _Proc:
        proc = _Proc()
        procs.append(proc)
        return proc

    sup = GamePointSupervisor(
        cfg, environ={}, popen=fake_popen, urlopen=staged_urlopen, python_executable="python"
    )
    # First start: nothing healthy yet → spawns and opens a log handle.
    first = sup.start_sidecar()
    assert first.state == "starting"
    assert len(sup._log_handles) == 1
    # The supervised child exits; an external healthy sidecar is now on the port.
    procs[0].terminated = True
    health["ok"] = True
    second = sup.start_sidecar()
    # Adopts the external sidecar (no second spawn) and closes the stale handle.
    assert second.state == "running"
    assert "adopted" in (second.detail or "")
    assert len(procs) == 1
    assert sup._log_handles == []


def test_start_sidecar_returns_probe_result_on_spawn_failure(tmp_path: Path) -> None:
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))

    def failing_popen(*_args: Any, **_kwargs: Any) -> _Proc:
        raise FileNotFoundError("missing sidecar executable")

    sup = GamePointSupervisor(
        cfg, environ={}, popen=failing_popen, urlopen=_refused_urlopen, python_executable="python"
    )
    result = sup.start_sidecar()

    assert result.ok is False
    assert result.state == "start_failed"
    assert "missing sidecar executable" in (result.detail or "")
    assert sup._sidecar_process is None
    assert sup._log_handles == []


def test_resolve_launcher_path_makes_relative_paths_absolute(tmp_path: Path) -> None:
    base = tmp_path / "GamePoint"
    archive = base / "archives" / "ref.json"
    archive.parent.mkdir(parents=True)
    archive.write_text("{}", encoding="utf-8")

    resolved = _resolve_launcher_path("archives/ref.json", base=base)

    assert resolved == str(archive.resolve())


def test_resolve_launcher_path_rejects_traversal_outside_base(tmp_path: Path) -> None:
    base = tmp_path / "GamePoint"
    base.mkdir()

    assert _resolve_launcher_path("../outside/ref.json", base=base) is None


def test_start_sidecar_uses_repo_root_cwd_in_dev_mode(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        calls.append(kwargs)
        return _Proc()

    sup = GamePointSupervisor(
        cfg,
        environ={},
        popen=fake_popen,
        urlopen=_refused_urlopen,
        python_executable="python",
        frozen=False,
    )
    sup.start_sidecar()
    sup.close()

    assert calls[0]["cwd"] == str(_repo_root())


def test_sidecar_environment_resolves_relative_voice_paths(tmp_path: Path) -> None:
    bank_dir = tmp_path / "banks" / "default"
    bank_dir.mkdir(parents=True)
    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        reference_archive=str(tmp_path / "ref.json"),
        voice_bank="banks/default",
        paths=LauncherPaths(tmp_path),
    )
    (tmp_path / "ref.json").write_text("{}", encoding="utf-8")

    env = GamePointSupervisor(cfg, environ={}).sidecar_environment()

    assert env["AC_COPILOT_VOICE_BANK"] == str(bank_dir.resolve())
    assert env["AC_COPILOT_REFERENCE_ARCHIVE"] == str((tmp_path / "ref.json").resolve())


def test_close_terminates_supervised_sidecar(tmp_path: Path) -> None:
    proc = _Proc()
    cfg = GamePointConfig(external_bind="127.0.0.1", paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={}, popen=lambda *a, **kw: proc, urlopen=_refused_urlopen
    )

    sup.start_sidecar()
    sup.close()

    assert proc.terminated is True


def test_simhub_absence_is_visible_but_not_fatal(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={"ProgramFiles": str(tmp_path / "missing")}, run=_no_simhub_run
    )

    result = sup.probe_simhub(start=True)

    assert result.ok is True
    assert result.state == "absent"
    assert "not found" in result.detail


def test_simhub_discovery_treats_windows_env_keys_case_insensitively(tmp_path: Path) -> None:
    exe = tmp_path / "SimHub" / "SimHubWPF.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg,
        environ={"PROGRAMFILES(X86)": str(tmp_path)},
        run=_no_simhub_run,
    )

    result = sup.probe_simhub(start=False)

    assert result.state == "available"
    assert result.detail == str(exe)


def test_launcher_env_reads_are_case_insensitive(tmp_path: Path) -> None:
    env = {
        "ac_copilot_start_simhub": "1",
        "ac_copilot_simhub_exe": "C:/SimHub/SimHubWPF.exe",
        "localappdata": str(tmp_path / "LocalAppData"),
    }

    cfg = GamePointConfig.from_env(env, paths=LauncherPaths(tmp_path))
    paths = supervisor_module.default_paths(env)

    assert cfg.start_simhub is True
    assert cfg.simhub_exe == "C:/SimHub/SimHubWPF.exe"
    assert paths.root == tmp_path / "LocalAppData" / "AC Copilot Trainer" / "GamePoint"


def test_launcher_env_snapshot_preserves_exact_case_values(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={"Path": "mixed", "PATH": "upper"})

    env = sup.sidecar_environment()

    assert env["Path"] == "mixed"
    assert env["PATH"] == "upper"


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
        run=_no_simhub_run,
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


def test_config_from_env_defaults_to_loopback_without_token(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env({}, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, python_executable="python")

    assert cfg.external_bind is None
    assert sup.sidecar_command() == [
        "python",
        "-m",
        "tools.ai_sidecar",
        "--port",
        "8765",
        "--host",
        "127.0.0.1",
    ]
    assert {row.name: row for row in sup.preflight()}["sidecar_token"].state == "loopback"


def test_launcher_setup_diff_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = tmp_path / "baseline.ini"
    candidate = tmp_path / "candidate.ini"
    baseline.write_text(
        "[FRONT_BIAS]\nVALUE=66\n[TRACTION_CONTROL]\nVALUE=3\n",
        encoding="utf-8",
    )
    candidate.write_text(
        "[FRONT_BIAS]\nVALUE=64\n[TRACTION_CONTROL]\nVALUE=4\n",
        encoding="utf-8",
    )

    assert main(["--setup-diff", str(baseline), str(candidate), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["changed_count"] == 2
    assert any("Brake bias" in line for line in out["display_lines"])
    lines = render_setup_diff_lines(out)
    assert lines[0] == "setup diff: 2 changed knobs"
    assert any(str(candidate) in line for line in lines)


def test_launcher_setup_diff_json_reports_file_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.ini"
    candidate = tmp_path / "candidate.ini"
    candidate.write_text("[FRONT_BIAS]\nVALUE=64\n", encoding="utf-8")

    assert main(["--setup-diff", str(missing), str(candidate), "--json"]) == 1

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["status"] == "setup_diff_failed"
    assert out["baseline"]["path"] == str(missing)
    assert out["candidate"]["path"] == str(candidate)
    assert "missing.ini" in out["error"]


def test_setup_diff_gui_fallback_keeps_success_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_window(_diff: dict[str, Any], *, parent: Any | None = None) -> int:
        del parent
        raise RuntimeError("no display")

    monkeypatch.setattr("tools.rig_launcher.app._open_setup_diff_window", fail_window)

    rc = run_setup_diff_gui(
        {"ok": True, "changed_count": 1, "display_lines": ["Brake bias: 66 -> 64 %"]}
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "Setup diff window unavailable" in captured.err
    assert "setup diff: 1 changed knob" in captured.out


def test_direct_config_default_is_loopback_safe(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, python_executable="python")

    assert cfg.external_bind is None
    assert "--external-bind" not in sup.sidecar_command()
    assert "--host" in sup.sidecar_command()


def test_config_from_env_defaults_to_external_bind_with_token(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_SIDECAR_TOKEN": "token"},
        paths=LauncherPaths(tmp_path),
    )

    assert cfg.external_bind == "0.0.0.0"


def test_config_from_settings_file_supplies_non_secret_defaults(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "external_bind": "127.0.0.1",
                "reference_archive": "ref.json",
                "setup_store": "setup.jsonl",
                "sidecar_port": 9999,
                "simhub_exe": "SimHubWPF.exe",
                "start_simhub": True,
                "resilient_car": "ks_porsche_911_gt3_r_2016",
                "resilient_track": "spa",
                "resilient_layout": "gp",
                "resilient_cm_exe": r"D:\Portable CM\Content Manager.exe",
                "voice_bank": "bank",
                "voice_tts": True,
            }
        ),
        encoding="utf-8",
    )

    cfg = GamePointConfig.from_env({}, paths=LauncherPaths(tmp_path))

    assert cfg.port == 9999
    assert cfg.external_bind == "127.0.0.1"
    assert cfg.reference_archive == "ref.json"
    assert cfg.voice_bank == "bank"
    assert cfg.voice_tts is True
    assert cfg.setup_store == "setup.jsonl"
    assert cfg.simhub_exe == "SimHubWPF.exe"
    assert cfg.start_simhub is True
    assert cfg.resilient_car == "ks_porsche_911_gt3_r_2016"
    assert cfg.resilient_track == "spa"
    assert cfg.resilient_layout == "gp"
    assert cfg.resilient_cm_exe == r"D:\Portable CM\Content Manager.exe"
    assert cfg.token is None


def test_env_overrides_settings_file(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "sidecar_port": 9999,
                "voice_tts": False,
                "start_simhub": False,
                "resilient_car": "settings-car",
                "resilient_track": "settings-track",
                "resilient_cm_exe": "settings-cm.exe",
            }
        ),
        encoding="utf-8",
    )

    cfg = GamePointConfig.from_env(
        {
            "AC_COPILOT_SIDECAR_PORT": "8766",
            "AC_COPILOT_VOICE_TTS": "1",
            "AC_COPILOT_START_SIMHUB": "1",
            "AC_COPILOT_RESILIENT_CAR": "env-car",
            "AC_COPILOT_RESILIENT_TRACK": "env-track",
            "AC_COPILOT_RESILIENT_CM_EXE": "env-cm.exe",
        },
        paths=LauncherPaths(tmp_path),
    )

    assert cfg.port == 8766
    assert cfg.voice_tts is True
    assert cfg.start_simhub is True
    assert cfg.resilient_car == "env-car"
    assert cfg.resilient_track == "env-track"
    assert cfg.resilient_cm_exe == "env-cm.exe"


def test_ensure_settings_file_writes_non_secret_template(tmp_path: Path) -> None:
    path = ensure_settings_file(LauncherPaths(tmp_path))

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path == tmp_path / "settings.json"
    assert payload["sidecar_port"] == 8765
    assert payload["external_bind"] == ""
    assert payload["resilient_car"] == ""
    assert payload["resilient_track"] == ""
    assert payload["resilient_cm_exe"] == ""
    assert "token" not in json.dumps(payload).lower()


def test_open_path_uses_macos_open(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(args: list[str]) -> _Proc:
        calls.append(args)
        return _Proc()

    monkeypatch.setattr("tools.rig_launcher.app.os.name", "posix")
    monkeypatch.setattr("tools.rig_launcher.app.sys.platform", "darwin")
    monkeypatch.setattr("tools.rig_launcher.app.subprocess.Popen", fake_popen)

    _open_path(tmp_path)

    assert calls == [["open", str(tmp_path)]]


def test_open_path_falls_back_to_explorer_for_windows_directories(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def fake_startfile(_path: Path) -> None:
        raise OSError("no file association")

    def fake_popen(args: list[str]) -> _Proc:
        calls.append(args)
        return _Proc()

    monkeypatch.setattr("tools.rig_launcher.app.os.name", "nt")
    monkeypatch.setattr("tools.rig_launcher.app.os.startfile", fake_startfile, raising=False)
    monkeypatch.setattr("tools.rig_launcher.app.subprocess.Popen", fake_popen)

    _open_path(tmp_path)

    assert calls == [["explorer.exe", str(tmp_path)]]


def test_open_path_falls_back_to_notepad_for_windows_files(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []
    path = tmp_path / "settings.json"
    path.write_text("{}\n", encoding="utf-8")

    def fake_startfile(_path: Path) -> None:
        raise OSError("no file association")

    def fake_popen(args: list[str]) -> _Proc:
        calls.append(args)
        return _Proc()

    monkeypatch.setattr("tools.rig_launcher.app.os.name", "nt")
    monkeypatch.setattr("tools.rig_launcher.app.os.startfile", fake_startfile, raising=False)
    monkeypatch.setattr("tools.rig_launcher.app.subprocess.Popen", fake_popen)

    _open_path(path)

    assert calls == [["notepad.exe", str(path)]]


def test_settings_load_falls_back_on_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe")
    settings = LauncherSettings.load(path)
    assert settings == LauncherSettings()


def test_restart_sidecar_reuses_single_log_handle(tmp_path: Path) -> None:
    procs: list[_Proc] = []

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        proc = _Proc()
        procs.append(proc)
        return proc

    cfg = GamePointConfig(external_bind="0.0.0.0", token="token", paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={}, popen=fake_popen, urlopen=_refused_urlopen, python_executable="python"
    )
    sup.start_sidecar()
    assert len(sup._log_handles) == 1
    procs[0].terminated = True
    sup.start_sidecar()
    assert len(sup._log_handles) == 1
    sup.close()


def test_build_pyinstaller_args_targets_launcher_entrypoint(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert "--onefile" in args
    assert "--noconsole" in args
    assert "tools.ai_sidecar" in args
    assert "--collect-data" in args
    assert _has_option_value(
        args,
        "--add-data",
        f"{tmp_path / 'assets' / 'setups' / '_schema'}{os.pathsep}assets/setups/_schema",
    )
    assert str(tmp_path / "tools" / "rig_launcher" / "__main__.py") == args[-1]


def test_build_pyinstaller_args_collects_voice_runtime_floor(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert _has_option_value(args, "--collect-data", "_sounddevice_data")
    assert _has_option_value(args, "--collect-binaries", "sounddevice")
    assert _has_option_value(args, "--hidden-import", "numpy")
    assert _has_option_value(args, "--hidden-import", "sounddevice")
    assert _has_option_value(args, "--hidden-import", "pyttsx3")
    assert _has_option_value(args, "--hidden-import", "pyttsx3.drivers.sapi5")


def test_build_pyinstaller_args_bundles_pyserial_for_serial_transport(tmp_path: Path) -> None:
    # Issue #463: pyserial is imported lazily by the sidecar, so it must be a
    # declared hidden-import or the frozen --serial-port sidecar fails at runtime.
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert _has_option_value(args, "--hidden-import", "serial")
    assert _has_option_value(args, "--hidden-import", "serial.tools.list_ports")


def test_build_pyinstaller_args_bundles_resilient_child(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    for module in (
        "tools.ac_harness.resilient_launch",
        "tools.ac_harness.entry_launcher",
        "tools.ac_harness.custom_ai",
        "tools.ac_harness.preset_utils",
        "tools.ac_harness.rig_lock",
        "tools.ac_harness.shared_memory",
        "tools.ac_harness.window_utils",
    ):
        assert _has_option_value(args, "--hidden-import", module)


def test_build_pyinstaller_args_collects_optional_rtmixer_when_installed(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_find_spec(module: str) -> object | None:
        if module in {"rtmixer", "pa_ringbuffer"}:
            return object()
        return None

    monkeypatch.setattr(supervisor_module, "find_spec", fake_find_spec)
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert _has_option_value(args, "--hidden-import", "rtmixer")
    assert _has_option_value(args, "--collect-binaries", "rtmixer")
    assert _has_option_value(args, "--hidden-import", "pa_ringbuffer")
    assert _has_option_value(args, "--collect-binaries", "pa_ringbuffer")


def test_build_pyinstaller_args_bundles_design_fonts_when_present(tmp_path: Path) -> None:
    fonts_dir = tmp_path / "src" / "ac_copilot_trainer" / "content" / "fonts"
    fonts_dir.mkdir(parents=True)

    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    # Destination "fonts" matches the sys._MEIPASS/fonts lookup in
    # tools.rig_launcher.fonts.load_private_fonts.
    assert _has_option_value(args, "--add-data", f"{fonts_dir}{os.pathsep}fonts")


def test_build_pyinstaller_args_omits_fonts_when_dir_missing(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert not any(value.endswith(f"{os.pathsep}fonts") for value in args)


def _has_option_value(args: list[str], option: str, value: str) -> bool:
    return any(
        left == option and right == value for left, right in zip(args, args[1:], strict=False)
    )


def test_launcher_extra_includes_sidecar_voice_runtime_deps() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    launcher = set(project["project"]["optional-dependencies"]["launcher"])

    # Always-installable floor: numpy + sounddevice ship bundled-PortAudio wheels that install
    # cleanly on a clean Windows rig, so `pip install -e ".[launcher]"` does not hard-fail there.
    assert "websockets>=16.0" in launcher
    assert "numpy>=2.4.4" in launcher
    assert "sounddevice>=0.5.1" in launcher
    assert "pyttsx3>=2.90" in launcher
    # rtmixer (#383) has no prebuilt Windows wheels and would hard-fail the documented launcher
    # install path — it must stay OUT of this default extra and is opt-in via `voice-rtmixer`
    # (asserted by test_voice_rtmixer_extra_is_opt_in_and_pulls_floor).
    assert not any(dep.startswith("rtmixer") for dep in launcher)


def test_voice_extra_floor_excludes_rtmixer() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    voice = set(project["project"]["optional-dependencies"]["voice"])

    # numpy + sounddevice are the always-installable voice floor; the engine falls back to the
    # sounddevice backend when rtmixer is absent (PR #387), so rtmixer is opt-in only.
    assert "numpy>=2.4.4" in voice
    assert "sounddevice>=0.5.1" in voice
    assert not any(dep.startswith("rtmixer") for dep in voice)


def test_voice_rtmixer_extra_is_opt_in_and_pulls_floor() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    voice_rtmixer = set(extras["voice-rtmixer"])

    # The opt-in, best-effort low-latency rtmixer backend lives here (and only here).
    assert "rtmixer>=0.1.7" in voice_rtmixer
    # Self-references the `voice` extra so `pip install -e ".[voice-rtmixer]"` also installs the
    # numpy + sounddevice floor — rtmixer alone is not useful.
    assert "ac-copilot-trainer[voice]" in voice_rtmixer


def test_default_exe_path_targets_dist_launcher(tmp_path: Path) -> None:
    assert default_exe_path(tmp_path) == tmp_path / "dist" / "AC-Copilot-Game-Point.exe"


def test_install_desktop_shortcut_invokes_powershell(tmp_path: Path) -> None:
    target = tmp_path / "dist" / "AC-Copilot-Game-Point.exe"
    target.parent.mkdir()
    target.write_text("", encoding="utf-8")
    shortcut = tmp_path / "Desktop" / SHORTCUT_NAME
    calls: list[dict[str, Any]] = []

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, "kwargs": kwargs})
        shortcut.write_text("shortcut", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=f"{shortcut}\n",
            stderr="",
        )

    result = install_desktop_shortcut(
        target,
        working_directory=tmp_path,
        shortcut_path=shortcut,
        run=fake_run,
        require_windows=False,
    )

    assert result.shortcut_path == shortcut.resolve()
    assert result.target_path == target.resolve()
    assert result.working_directory == tmp_path.resolve()
    assert calls[0]["args"][0][:4] == [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
    ]
    assert calls[0]["kwargs"]["env"]["AC_COPILOT_SHORTCUT_TARGET"] == str(target.resolve())


def test_sidecar_child_entrypoint_rewrites_sys_argv(monkeypatch) -> None:
    from tools.ai_sidecar import server

    seen: dict[str, list[str]] = {}

    def fake_main() -> None:
        import sys

        seen["argv"] = list(sys.argv)

    monkeypatch.setattr(server, "main", fake_main)

    assert run_sidecar_child(["--port", "8765"]) == 0
    assert seen["argv"] == ["ai_sidecar", "--port", "8765"]


def test_resilient_child_entrypoint_forwards_arguments(monkeypatch) -> None:
    from tools.ac_harness import resilient_launch

    seen: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        seen.append(argv)
        return 7

    monkeypatch.setattr(resilient_launch, "main", fake_main)

    assert run_resilient_launch_child(["--car", "car", "--track", "track"]) == 7
    assert seen == [["--car", "car", "--track", "track"]]


def test_run_gui_falls_back_when_tk_init_fails(monkeypatch, capsys) -> None:
    tk_mod = types.ModuleType("tkinter")
    ttk_mod = types.ModuleType("tkinter.ttk")

    class FailingTk:
        def __init__(self) -> None:
            raise RuntimeError("no display")

    tk_mod.Tk = FailingTk
    tk_mod.ttk = ttk_mod
    monkeypatch.setitem(sys.modules, "tkinter", tk_mod)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk_mod)

    ok = ProbeResult("sidecar", True, "ok")
    status = GamePointStatus(
        generated_at=0.0,
        sidecar=ok,
        screen=ProbeResult("screen", True, "connected"),
        voice=ProbeResult("voice", True, "skipped"),
        simhub=ProbeResult("simhub", True, "absent"),
        log_path="sidecar.log",
        status_path="status.json",
    )

    class DummySupervisor:
        def poll_status(self) -> GamePointStatus:
            return status

    assert run_gui(DummySupervisor()) == 0  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert "GUI unavailable: no display" in captured.err
    assert "sidecar: ok" in captured.out


# -- SimHub auto-start toggle (issue #479) ------------------------------------


def test_default_settings_keep_simhub_autostart_off(tmp_path: Path) -> None:
    """Packaged default stays opt-in (matches the PR #207 opt-in house pattern)."""
    assert default_settings_payload()["start_simhub"] is False
    path = ensure_settings_file(LauncherPaths(tmp_path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["start_simhub"] is False


def test_update_settings_merges_and_preserves_other_keys(tmp_path: Path) -> None:
    paths = LauncherPaths(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "_schema": "ac-copilot-game-point-settings-v1",
                "sidecar_port": 9999,
                "voice_tts": True,
                "start_simhub": False,
            }
        ),
        encoding="utf-8",
    )

    path = update_settings(paths, start_simhub=True)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["start_simhub"] is True
    # Untouched keys survive the merge — the toggle must not clobber other settings.
    assert payload["sidecar_port"] == 9999
    assert payload["voice_tts"] is True
    # And the persisted value round-trips through the loader the config uses.
    assert GamePointConfig.from_env({}, paths=paths).start_simhub is True


def test_update_settings_creates_template_when_file_missing(tmp_path: Path) -> None:
    paths = LauncherPaths(tmp_path)

    path = update_settings(paths, start_simhub=True)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path == tmp_path / "settings.json"
    assert payload["start_simhub"] is True
    # Falls back to the non-secret template for the other keys; never invents a token.
    assert payload["voice_bank"] == ""
    assert "token" not in json.dumps(payload).lower()


def test_update_settings_refuses_to_overwrite_malformed_existing_file(tmp_path: Path) -> None:
    """Preserve manual work: a present-but-malformed settings.json is never overwritten."""
    paths = LauncherPaths(tmp_path)
    original = "{ oops, hand-edited typo"  # valid utf-8, invalid JSON
    (tmp_path / "settings.json").write_text(original, encoding="utf-8")

    with pytest.raises(ValueError):
        update_settings(paths, start_simhub=True)

    # The operator's file is left exactly as written — not clobbered with defaults.
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == original


def test_update_settings_refuses_to_overwrite_unreadable_existing_file(tmp_path: Path) -> None:
    """A present-but-unreadable (bad-encoding) settings.json is preserved, raising OSError."""
    paths = LauncherPaths(tmp_path)
    (tmp_path / "settings.json").write_bytes(b"\xff\xfe not utf-8")

    with pytest.raises(OSError):
        update_settings(paths, start_simhub=True)

    assert (tmp_path / "settings.json").read_bytes() == b"\xff\xfe not utf-8"


def test_update_settings_refuses_to_overwrite_non_object_json_root(tmp_path: Path) -> None:
    """A valid-JSON-but-non-object settings.json (e.g. a list) is preserved, raising."""
    paths = LauncherPaths(tmp_path)
    original = "[1, 2, 3]"
    (tmp_path / "settings.json").write_text(original, encoding="utf-8")

    with pytest.raises(ValueError):
        update_settings(paths, start_simhub=True)

    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == original


def test_update_settings_never_persists_secret_like_keys(tmp_path: Path) -> None:
    """update_settings writes only the non-secret schema; a stray token is dropped (contract)."""
    paths = LauncherPaths(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sidecar_port": 8765, "token": "SHOULD-NOT-PERSIST", "voice_bank": "b"}),
        encoding="utf-8",
    )

    path = update_settings(paths, start_simhub=True, token="ALSO-NOT")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["start_simhub"] is True
    assert payload["sidecar_port"] == 8765
    assert payload["voice_bank"] == "b"
    assert "token" not in payload
    assert "SHOULD-NOT-PERSIST" not in json.dumps(payload)
    assert "ALSO-NOT" not in json.dumps(payload)


def test_update_settings_fills_template_for_partial_file(tmp_path: Path) -> None:
    """An existing but partial/empty settings.json keeps template keys on merge.

    Regression for the PR #480 daemon finding: merging onto ``dict(loaded)`` for any
    Mapping would strip _schema/defaults from an existing ``{}`` and write a bare
    ``{"start_simhub": true}``. The merge must baseline on the template instead.
    """
    paths = LauncherPaths(tmp_path)
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")

    path = update_settings(paths, start_simhub=True)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["start_simhub"] is True
    assert payload["_schema"] == "ac-copilot-game-point-settings-v1"
    assert payload["sidecar_port"] == 8765
    assert payload["voice_bank"] == ""


def test_set_start_simhub_persists_and_updates_live_config(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    assert sup.set_start_simhub(True) is True
    assert sup.config.start_simhub is True
    persisted = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert persisted["start_simhub"] is True

    assert sup.set_start_simhub(False) is False
    assert sup.config.start_simhub is False
    persisted = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert persisted["start_simhub"] is False


def test_set_start_simhub_applies_runtime_change_even_if_persist_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A settings-write failure must not swallow the runtime toggle — but must warn."""

    def boom(*_args: Any, **_kwargs: Any) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("tools.rig_launcher.settings.update_settings", boom)
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    assert sup.set_start_simhub(True) is True
    assert sup.config.start_simhub is True
    # Not silent: the persist failure surfaces on stderr (daemon #480 review).
    assert "could not persist start_simhub" in capsys.readouterr().err


def test_set_start_simhub_preserves_malformed_settings_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Toggling with a malformed settings.json applies at runtime, warns, and leaves the
    operator's file untouched (preserve manual work — daemon #480 antigravity HIGH)."""
    paths = LauncherPaths(tmp_path)
    original = "{ manual typo"
    (tmp_path / "settings.json").write_text(original, encoding="utf-8")
    sup = GamePointSupervisor(GamePointConfig(paths=paths), environ={})

    assert sup.set_start_simhub(True) is True
    assert sup.config.start_simhub is True
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == original
    assert "could not persist start_simhub" in capsys.readouterr().err


def test_toggle_then_poll_starts_simhub(tmp_path: Path) -> None:
    """Enabling the toggle makes the next poll start SimHub — the one-icon outcome."""
    exe = tmp_path / "SimHub" / "SimHubWPF.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    calls: list[Any] = []

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        calls.append((args, kwargs))
        return _Proc()

    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg,
        environ={"ProgramFiles": str(tmp_path)},
        popen=fake_popen,
        urlopen=_refused_urlopen,
        run=_no_simhub_run,
    )

    # Before the toggle: SimHub is detected but NOT started (start=False).
    assert sup.probe_simhub(start=sup.config.start_simhub).state == "available"
    assert calls == []

    sup.set_start_simhub(True)
    status = sup.poll_status()

    assert status.simhub.state == "started"
    assert status.simhub.ok is True
    assert calls[0][0][0] == [str(exe)]


def test_simhub_started_does_not_block_overall_status(tmp_path: Path) -> None:
    """A started SimHub row must not force overall status to needs_attention (#479)."""
    exe = tmp_path / "SimHub" / "SimHubWPF.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")

    def fake_popen(*_args: Any, **_kwargs: Any) -> _Proc:
        return _Proc()

    def healthy_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response({"status": "ok", "connected_peers": 1, "screen_peers": 1})

    cfg = GamePointConfig(
        external_bind="0.0.0.0",
        token="token",
        start_simhub=True,
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(
        cfg,
        environ={"ProgramFiles": str(tmp_path)},
        popen=fake_popen,
        urlopen=healthy_urlopen,
        run=_no_simhub_run,
    )

    status = sup.poll_status()

    assert status.simhub.state == "started"
    assert status.simhub.ok is True
    assert status.ok is True


# -- Tablet adb reverse tunnel keeper + endpoint self-test (issue #567) --------


def test_probe_tablet_unmanaged_by_default(tmp_path: Path) -> None:
    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, urlopen=_refused_urlopen)
    tablet = sup.probe_tablet()
    assert tablet.state == "unmanaged"
    assert tablet.ok is True


def test_config_reads_manage_tablet_tunnel_from_env(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_MANAGE_TABLET_TUNNEL": "1"},
        paths=LauncherPaths(tmp_path),
    )
    assert cfg.manage_tablet_tunnel is True


def test_probe_tablet_managed_asserts_reverse_and_reports_dash(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        args = cmd[1:]
        if len(args) >= 2 and args[0] == "-s":
            args = args[2:]  # drop the transport selector
        sub = args[0] if args else ""
        if sub == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\n1c00\tdevice\n", ""
            )
        if sub == "reverse" and len(args) >= 2 and args[1] == "--list":
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cfg = GamePointConfig(manage_tablet_tunnel=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg,
        environ={"AC_COPILOT_ADB": str(adb)},
        urlopen=_serving_urlopen,  # /tablet/dash ground-truth probe returns 200
        run=fake_run,
    )
    # sidecar serves /tablet/dash (200) → not stale
    healthy = {"endpoints": ["/health", "/tablet/dash", "/tablet/voice"], "browser_peers": 0}
    tablet = sup.probe_tablet(healthy)
    assert tablet.state == "tunnel-up"
    assert tablet.ok is True

    tablet2 = sup.probe_tablet({**healthy, "browser_peers": 1})
    assert tablet2.state == "dash-connected"
    assert "browser_peers=1" in tablet2.detail
    assert any("devices" in cmd for cmd in calls)


def test_self_test_endpoints_flags_stale_build(tmp_path: Path) -> None:
    import urllib.error

    ok_health = {"status": "ok", "connected_peers": 0, "screen_peers": 0}

    def urlopen(url: str, timeout: float) -> _Response:
        del timeout
        if url.endswith("/health"):
            return _Response(ok_health)
        raise urllib.error.HTTPError(url, 426, "Upgrade Required", {}, None)

    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, urlopen=urlopen)
    results = sup.self_test_endpoints(wait_timeout=1.0)
    assert results
    assert all(row.state == "stale_build" and not row.ok for row in results)
    assert any("/tablet/dash" in row.name for row in results)


def test_self_test_endpoints_passes_when_routes_serve(tmp_path: Path) -> None:
    def urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response({"status": "ok"})  # 200 for /health and both tablet routes

    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, urlopen=urlopen)
    results = sup.self_test_endpoints(wait_timeout=1.0)
    assert results
    assert all(row.state == "serving" and row.ok for row in results)


def test_config_from_args_propagates_manage_tablet_tunnel(tmp_path: Path, monkeypatch) -> None:
    """P1 regression (#568 review): the CLI/packaged config must carry the flag through, or
    the keeper never runs even with AC_COPILOT_MANAGE_TABLET_TUNNEL=1."""
    from tools.rig_launcher.app import build_arg_parser, config_from_args

    monkeypatch.setenv("AC_COPILOT_MANAGE_TABLET_TUNNEL", "1")
    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    args = build_arg_parser().parse_args(["--log-dir", str(tmp_path)])
    cfg = config_from_args(args)
    assert cfg.manage_tablet_tunnel is True


def test_config_from_args_propagates_adb_overrides(tmp_path: Path, monkeypatch) -> None:
    """HIGH regression (#568 review): config_from_args must thread adb_path/adb_serial through,
    or env overrides are silently dropped in the CLI/packaged path."""
    from tools.rig_launcher.app import build_arg_parser, config_from_args

    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    monkeypatch.setenv("AC_COPILOT_ADB", "/opt/adb")
    monkeypatch.setenv("AC_COPILOT_ADB_SERIAL", "SER9")
    cfg = config_from_args(build_arg_parser().parse_args(["--log-dir", str(tmp_path)]))
    assert cfg.adb_path == "/opt/adb"
    assert cfg.adb_serial == "SER9"


def test_self_test_sends_token_header_for_authenticated_bind(tmp_path: Path) -> None:
    """P2 (#568 review): a concrete non-loopback bind + token gates /tablet/* — the probe must
    carry X-AC-Copilot-Token or it 401s and misreports stale_build."""
    import urllib.request

    seen: list[tuple[str, dict[str, str]]] = []

    def urlopen(target: object, timeout: float) -> _Response:
        del timeout
        if isinstance(target, urllib.request.Request):
            seen.append((target.full_url, dict(target.headers)))
        else:
            seen.append((str(target), {}))
        return _Response({"status": "ok"})

    cfg = GamePointConfig(
        external_bind="192.168.1.50", token="secret", paths=LauncherPaths(tmp_path)
    )
    sup = GamePointSupervisor(cfg, environ={}, urlopen=urlopen)
    results = sup.self_test_endpoints(wait_timeout=1.0)
    assert all(row.state == "serving" for row in results)
    dash = [headers for (url, headers) in seen if url.endswith("/tablet/dash")]
    assert dash
    assert any(any(key.lower() == "x-ac-copilot-token" for key in headers) for headers in dash)


def test_summary_caption_surfaces_failing_tablet(tmp_path: Path) -> None:
    """P2 (#568 review): a managed-tablet failure must reach the GUI summary caption, not just
    flip overall red with a generic message."""
    from tools.rig_launcher import theme

    status = GamePointStatus(
        generated_at=0.0,
        sidecar=ProbeResult("sidecar", True, "healthy"),
        screen=ProbeResult("screen", True, "connected"),
        voice=ProbeResult("voice", True, "skipped"),
        simhub=ProbeResult("simhub", True, "absent"),
        tablet=ProbeResult("tablet", False, "unauthorized", "accept the prompt on the tablet"),
        log_path="x",
        status_path="y",
    )
    assert status.ok is False
    text, _tone, caption = theme.summary_for(status)
    assert text == "PRESS START"
    assert "accept the prompt" in caption


def test_probe_tablet_rejects_concrete_external_bind(tmp_path: Path) -> None:
    """P2 (#568 review): adb reverse targets PC loopback, so a concrete non-loopback bind
    cannot serve the tablet — fail loud instead of a false tunnel-up, and never call adb."""

    def _boom_run(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("adb must not run when the bind is unreachable")

    cfg = GamePointConfig(
        manage_tablet_tunnel=True,
        external_bind="192.168.1.50",
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(cfg, environ={}, urlopen=_refused_urlopen, run=_boom_run)
    tablet = sup.probe_tablet()
    assert tablet.state == "bind-unreachable"
    assert tablet.ok is False


def test_probe_tablet_wildcard_bind_is_allowed(tmp_path: Path) -> None:
    """0.0.0.0 includes loopback, so the managed tunnel is fine — no bind-unreachable."""
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "devices":
            return subprocess.CompletedProcess(cmd, 0, "List of devices attached\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cfg = GamePointConfig(
        manage_tablet_tunnel=True,
        external_bind="0.0.0.0",
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(
        cfg, environ={"AC_COPILOT_ADB": str(adb)}, urlopen=_refused_urlopen, run=fake_run
    )
    tablet = sup.probe_tablet()
    assert tablet.state == "no-device"  # reached the keeper; no tablet plugged in
    assert tablet.ok is True


def test_probe_tablet_managed_adb_missing_fails(tmp_path: Path, monkeypatch) -> None:
    """P2 (#568 review): once management is opted in, a missing adb is a failing status."""
    monkeypatch.setattr("tools.rig_launcher.tablet_tunnel.resolve_adb", lambda *_a, **_k: None)
    cfg = GamePointConfig(manage_tablet_tunnel=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={}, urlopen=_refused_urlopen)
    tablet = sup.probe_tablet()
    assert tablet.state == "adb-missing"
    assert tablet.ok is False


def test_self_test_cli_stops_sidecar_it_started(tmp_path: Path, monkeypatch) -> None:
    """HIGH (#568 review): the --self-test path must tear down the sidecar it started, not
    leave an orphan for the next launch to adopt."""
    import tools.rig_launcher.app as app

    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    made: list[Any] = []

    class _FakeSup:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.events: list[str] = []
            made.append(self)

        def start_sidecar(self) -> ProbeResult:
            self.events.append("start")
            return ProbeResult("sidecar", True, "starting")

        def self_test_endpoints(self, **_k: Any) -> tuple[ProbeResult, ...]:
            self.events.append("selftest")
            return (ProbeResult("endpoint /tablet/dash", True, "serving"),)

        def stop_sidecar(self, **_k: Any) -> ProbeResult:
            self.events.append("stop")
            return ProbeResult("sidecar", True, "stopped")

        def close(self) -> None:
            self.events.append("close")

    monkeypatch.setattr(app, "GamePointSupervisor", _FakeSup)
    rc = app.main(["--self-test"])
    assert rc == 0
    assert made[0].events == ["start", "selftest", "stop", "close"]


def test_probe_tablet_flags_stale_adopted_sidecar(tmp_path: Path) -> None:
    """P2 (#568 review): an adopted stale sidecar whose /health omits /tablet/dash must not
    read as a healthy tunnel — the dash would still 426."""
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        sub = cmd[2] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1]
        if sub == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nSER\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cfg = GamePointConfig(manage_tablet_tunnel=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={"AC_COPILOT_ADB": str(adb)}, urlopen=_refused_urlopen, run=fake_run
    )
    # health from a stale build: endpoints present but missing /tablet/dash
    stale = {"endpoints": ["/health", "/metrics"], "browser_peers": 0}
    tablet = sup.probe_tablet(stale)
    assert tablet.state == "stale-sidecar"
    assert tablet.ok is False


def test_poll_status_read_only_does_not_start_simhub(tmp_path: Path) -> None:
    """P2 (#568 review): the continuous read-only poll must not relaunch SimHub every tick."""
    exe = tmp_path / "SimHub" / "SimHubWPF.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    spawned: list[Any] = []

    def fake_popen(*args: Any, **kwargs: Any) -> _Proc:
        spawned.append(args)
        return _Proc()

    cfg = GamePointConfig(start_simhub=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg,
        environ={"ProgramFiles": str(tmp_path)},
        popen=fake_popen,
        urlopen=_refused_urlopen,
        run=_no_simhub_run,
    )
    status = sup.poll_status(start_simhub=False)
    assert status.simhub.state == "available"  # discovered, NOT started
    assert spawned == []  # SimHub was never launched by a read-only poll


def test_supervisor_handle_access_is_thread_safe(tmp_path: Path) -> None:
    """HIGH (#568 review): the GUI worker reads the sidecar handle while START/stop mutate it on
    the Tk thread. The _proc_lock must serialize those so concurrent access never crashes or
    tears state. Smoke-stress the locked read against start/stop cycles."""
    import threading as _threading

    cfg = GamePointConfig(paths=LauncherPaths(tmp_path))

    def fake_popen(*_a: Any, **_k: Any) -> _Proc:
        return _Proc()

    sup = GamePointSupervisor(
        cfg,
        environ={},
        popen=fake_popen,
        urlopen=_refused_urlopen,  # never adopts → always spawns the fake
        run=_no_simhub_run,
    )
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(300):
                sup._sidecar_process_status()
        except BaseException as exc:  # noqa: BLE001 - capture any race-induced failure
            errors.append(exc)

    def cycler() -> None:
        try:
            for _ in range(150):
                sup.start_sidecar()
                sup.stop_sidecar()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [_threading.Thread(target=reader) for _ in range(3)]
    threads += [_threading.Thread(target=cycler) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    # Final state is coherent (stopped after the last cycle's stop).
    assert sup._sidecar_process_status().state in {"stopped", "running", "exited"}
    sup.close()


def test_probe_tablet_ground_truth_probe_when_endpoints_absent(tmp_path: Path) -> None:
    """P2 (#568 review): a sidecar predating the /health `endpoints` field but still serving
    /tablet/dash (200) must NOT be flagged stale — confirm against reality, not the field."""
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[2:] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1:]
        if args and args[0] == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nSER\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response({"status": "ok"})  # 200 for the /tablet/dash ground-truth probe

    cfg = GamePointConfig(manage_tablet_tunnel=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={"AC_COPILOT_ADB": str(adb)}, urlopen=urlopen, run=fake_run
    )
    # health payload with NO endpoints field (older sidecar), but dash actually serves 200
    tablet = sup.probe_tablet({"browser_peers": 0})
    assert tablet.state == "tunnel-up"
    assert tablet.ok is True


def test_probe_tablet_ground_truth_probe_catches_pre531_stale(tmp_path: Path) -> None:
    """The original stale-EXE case: no endpoints field AND /tablet/dash 426s → stale-sidecar."""
    import urllib.error

    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[2:] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1:]
        if args and args[0] == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nSER\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def urlopen(url: str, timeout: float) -> _Response:
        del timeout
        raise urllib.error.HTTPError(url, 426, "Upgrade Required", {}, None)

    cfg = GamePointConfig(manage_tablet_tunnel=True, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(
        cfg, environ={"AC_COPILOT_ADB": str(adb)}, urlopen=urlopen, run=fake_run
    )
    tablet = sup.probe_tablet({"browser_peers": 0})  # no endpoints field
    assert tablet.state == "stale-sidecar"
    assert tablet.ok is False


def test_config_reads_adb_overrides_from_env(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_ADB": "/opt/adb", "AC_COPILOT_ADB_SERIAL": "SER"},
        paths=LauncherPaths(tmp_path),
    )
    assert cfg.adb_path == "/opt/adb"
    assert cfg.adb_serial == "SER"


def test_probe_tablet_routes_config_adb_serial(tmp_path: Path) -> None:
    """#568 review: the tablet serial comes from GamePointConfig, not an ad-hoc env read."""
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[2:] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1:]
        if args and args[0] == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nAAA\tdevice\nBBB\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cfg = GamePointConfig(
        manage_tablet_tunnel=True,
        adb_path=str(adb),
        adb_serial="BBB",  # two devices attached; config picks BBB
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(cfg, environ={}, urlopen=_serving_urlopen, run=fake_run)
    tablet = sup.probe_tablet({"endpoints": ["/tablet/dash"], "browser_peers": 0})
    assert tablet.state == "tunnel-up"


def test_probe_tablet_tunnel_up_when_sidecar_down_is_not_stale(tmp_path: Path) -> None:
    """HIGH (#568 review): a stopped sidecar (health_payload=None) must read tunnel-up, not a
    false `stale-sidecar` — the sidecar row carries the down state; the tunnel itself is up."""
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    probed: list[str] = []

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[2:] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1:]
        if args and args[0] == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nSER\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def urlopen(url: str, timeout: float) -> _Response:
        del timeout
        probed.append(url)
        raise OSError("connection refused")  # sidecar is down

    cfg = GamePointConfig(
        manage_tablet_tunnel=True, adb_path=str(adb), paths=LauncherPaths(tmp_path)
    )
    sup = GamePointSupervisor(cfg, environ={}, urlopen=urlopen, run=fake_run)
    tablet = sup.probe_tablet(None)  # sidecar down → no health payload
    assert tablet.state == "tunnel-up"
    assert tablet.ok is True
    # must NOT have probed /tablet/dash against the dead port
    assert not any("/tablet/dash" in u for u in probed)


def test_probe_tablet_flags_missing_asset_even_when_advertised(tmp_path: Path) -> None:
    """P2 (#568 review): handler compiled in (so /health advertises /tablet/dash) but the bundled
    HTML asset is missing → GET 404. The ground-truth probe must catch it (advertisement lies)."""
    import urllib.error

    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")

    def fake_run(cmd: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[2:] if len(cmd) > 2 and cmd[1] == "-s" else cmd[1:]
        if args and args[0] == "devices":
            return subprocess.CompletedProcess(
                cmd, 0, "List of devices attached\nSER\tdevice\n", ""
            )
        if "reverse" in cmd and "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "UsbFfs tcp:8765 tcp:8765\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def urlopen(url: str, timeout: float) -> _Response:
        del timeout
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # asset missing

    cfg = GamePointConfig(
        manage_tablet_tunnel=True, adb_path=str(adb), paths=LauncherPaths(tmp_path)
    )
    sup = GamePointSupervisor(cfg, environ={}, urlopen=urlopen, run=fake_run)
    # /health advertises the route, but the page 404s
    tablet = sup.probe_tablet({"endpoints": ["/tablet/dash"], "browser_peers": 0})
    assert tablet.state == "stale-sidecar"
    assert tablet.ok is False


def test_self_test_cli_refuses_to_validate_adopted_sidecar(tmp_path: Path, monkeypatch) -> None:
    """P2 (#568 review): --self-test must not pass by validating a foreign adopted sidecar."""
    import tools.rig_launcher.app as app

    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    made: list[Any] = []

    class _AdoptingSup:
        config = GamePointConfig(paths=LauncherPaths(tmp_path))

        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.events: list[str] = []
            made.append(self)

        def start_sidecar(self) -> ProbeResult:
            self.events.append("start")
            return ProbeResult("sidecar", True, "running", "adopted existing sidecar on port 8765")

        def self_test_endpoints(self, **_k: Any) -> tuple[ProbeResult, ...]:
            self.events.append("selftest")  # must NOT be reached
            return ()

        def stop_sidecar(self, **_k: Any) -> ProbeResult:
            self.events.append("stop")
            return ProbeResult("sidecar", True, "stopped")

        def close(self) -> None:
            self.events.append("close")

    monkeypatch.setattr(app, "GamePointSupervisor", _AdoptingSup)
    rc = app.main(["--self-test"])
    assert rc == 1
    assert "selftest" not in made[0].events  # refused before validating the foreign process


def test_self_test_cli_fails_fast_on_start_failure(tmp_path: Path, monkeypatch) -> None:
    """Bug (#568 Qodo): --self-test must fail fast if start_sidecar returned ok=False, not probe
    the port and emit misleading endpoint errors."""
    import tools.rig_launcher.app as app

    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    made: list[Any] = []

    class _FailingStartSup:
        config = GamePointConfig(paths=LauncherPaths(tmp_path))

        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.events: list[str] = []
            made.append(self)

        def start_sidecar(self) -> ProbeResult:
            self.events.append("start")
            return ProbeResult("sidecar", False, "start_failed", "boom")

        def self_test_endpoints(self, **_k: Any) -> tuple[ProbeResult, ...]:
            self.events.append("selftest")  # must NOT be reached
            return ()

        def stop_sidecar(self, **_k: Any) -> ProbeResult:
            self.events.append("stop")
            return ProbeResult("sidecar", True, "stopped")

        def close(self) -> None:
            self.events.append("close")

    monkeypatch.setattr(app, "GamePointSupervisor", _FailingStartSup)
    rc = app.main(["--self-test"])
    assert rc == 1
    assert "selftest" not in made[0].events
