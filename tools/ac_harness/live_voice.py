"""Owner-run acoustic acceptance using the canonical Game Point UI and sidecar.

Creates fresh per-run settings and a diagnostic tap; does not automatically launch AC or enable AI.
Arm the independent rig watchdog before enabling driving through the ordinary rig controls.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.ac_harness.rig_lock import (
    default_rig_session_lock_path,
    read_rig_session_owner,
)
from tools.ai_sidecar.voice.config import parse_channel_map
from tools.rig_launcher.app import run_gui
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
    ProbeResult,
    default_paths,
)

INSTRUMENTED_SIDECAR_MODULE = "tools.ai_sidecar.voice.instrumented_sidecar"
_PATH_FIELDS = (
    "reference_archive",
    "alien_line",
    "voice_bank",
    "setup_store",
    "simhub_exe",
    "resilient_cm_exe",
    "ac_user_dir",
    "keypad_profiles",
    "moza_offline_file",
    "moza_offline_native_file",
    "moza_offline_evaluation_file",
    "moza_offline_reference_file",
)


def verify_owner(owner_pid: int, lock_path: Path) -> dict:
    """Use the canonical authoritative-byte reader; never acquire or replace ownership."""
    if type(owner_pid) is not int or owner_pid <= 0:
        raise ValueError("owner PID must be positive")
    owner = read_rig_session_owner(lock_path)
    if not owner or owner.get("pid") != owner_pid:
        raise RuntimeError(f"rig owner mismatch: expected PID {owner_pid}; observed {owner}")
    return owner


def _absolute_setting(value: str | None, base: Path) -> str | None:
    if not value:
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"relative production setting escapes Game Point root: {value}")
    return str(resolved)


class CaptureSupervisor(GamePointSupervisor):
    def __init__(self, config, *, run_dir, owner_pid, **kwargs):
        super().__init__(config, **kwargs)
        self.run_dir = Path(run_dir).resolve()
        self.owner_pid = owner_pid
        self.tap_path = self.run_dir / "sidecar-tap.jsonl"
        self.stop_path = self.run_dir / "sidecar.stop"

    def preflight(self, health_payload=None):
        checks = super().preflight(health_payload)
        try:
            verify_owner(self.owner_pid, self._rig_lock_path())
            owner_check = ProbeResult("capture_owner", True, "verified", f"pid={self.owner_pid}")
        except (OSError, ValueError, RuntimeError) as exc:
            owner_check = ProbeResult("capture_owner", False, "owner_mismatch", str(exc))
        return (*checks, owner_check)

    def sidecar_command(self):
        original = super().sidecar_command()
        if original[1:3] != ["-m", "tools.ai_sidecar"]:
            raise RuntimeError("capture wrapper requires the source Game Point entrypoint")
        return [
            original[0],
            "-B",
            "-m",
            INSTRUMENTED_SIDECAR_MODULE,
            "--tap",
            str(self.tap_path),
            "--stop-file",
            str(self.stop_path),
            "--",
            *original[3:],
        ]

    def stop_sidecar(self, *, timeout=5.0):
        with self._proc_lock:
            proc = self._sidecar_process
            timed_out = False
            if proc is not None and proc.poll() is None:
                # The handle was created by this supervisor. An adopted peer has no handle, so
                # neither its process nor a stop path is touched by this operation.
                try:
                    with self.stop_path.open("x", encoding="utf-8") as stream:
                        json.dump({"owner_pid": self.owner_pid, "sidecar_pid": proc.pid}, stream)
                except FileExistsError:
                    pass  # A second close joins the same one-shot stop request.
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
            result = super().stop_sidecar(timeout=timeout)
            if timed_out:
                return ProbeResult(
                    result.name,
                    False,
                    "graceful_stop_timeout",
                    f"owned wrapper required canonical cleanup; {result.detail}",
                )
            return result


def prepare_run(capture_config: Path, run_dir: Path, owner_pid: int, *, environ=None):
    env = dict(os.environ if environ is None else environ)
    production_paths = default_paths(env)
    production = GamePointConfig.from_env(env, paths=production_paths)
    lock_path = default_rig_session_lock_path(local_app_data=env.get("LOCALAPPDATA"))
    owner = verify_owner(owner_pid, lock_path)
    capture = json.loads(capture_config.read_text(encoding="utf-8"))
    if not isinstance(capture, dict):
        raise ValueError("capture config must be an object")
    producer_mode = capture.get("producer_mode", "coach_v2")
    if producer_mode not in ("coach_v2", "observer"):
        raise ValueError("producer_mode must explicitly select coach_v2 or observer")
    if producer_mode == "observer" and production.alien_line:
        raise ValueError("observer capture conflicts with the inherited Coach v2 alien_line")
    reference = Path(capture["reference_archive"]).expanduser().resolve(strict=True)
    bank = Path(capture["bank_dir"]).expanduser().resolve(strict=True)
    if not reference.is_file() or not bank.is_dir():
        raise ValueError("capture reference must be a file and bank must be a directory")
    channels = parse_channel_map(capture.get("output_channel_map"))
    if channels is None:
        raise ValueError("capture config must explicitly pin output_channel_map")
    device = capture.get("output_device")
    host_api = capture.get("output_host_api")
    if (
        not isinstance(device, str)
        or not device.strip()
        or not isinstance(host_api, str)
        or not host_api.strip()
    ):
        raise ValueError("capture config must explicitly pin output_device and output_host_api")
    new_root = run_dir.expanduser().resolve()
    if new_root.is_relative_to(
        production_paths.root.resolve()
    ) or production_paths.root.resolve().is_relative_to(new_root):
        raise ValueError("capture directory must be independent of the production Game Point root")
    # Resolve production-relative paths before changing the settings/status root. No production
    # setting or inherited environment entry is discarded; only the explicit run overrides below.
    path_values = {
        name: _absolute_setting(getattr(production, name), production_paths.root)
        for name in _PATH_FIELDS
    }
    path_values.update(reference_archive=str(reference), voice_bank=str(bank))
    paths = LauncherPaths(new_root / "GamePoint")
    config = dataclasses.replace(
        production,
        **path_values,
        paths=paths,
        rig_lock_path=lock_path,
        voice_channel_map=",".join(map(str, channels)),
        voice_tts=False,
        start_simhub=False,
    )
    env.update(
        {
            "AC_COPILOT_GAME_POINT_DIR": str(paths.root),
            "AC_COPILOT_REFERENCE_ARCHIVE": str(reference),
            "AC_COPILOT_VOICE_BANK": str(bank),
            "AC_COPILOT_VOICE_DEVICE": device,
            "AC_COPILOT_VOICE_HOST_API": host_api,
            "AC_COPILOT_VOICE_CHANNEL_MAP": config.voice_channel_map,
            "AC_COPILOT_COACH_V2": "1" if producer_mode == "coach_v2" else "0",
            "AC_COPILOT_START_SIMHUB": "0",
            "AC_COPILOT_VOICE_TTS": "0",
        }
    )
    production_settings = {}
    if production_paths.settings_path.exists():
        production_settings = json.loads(production_paths.settings_path.read_text(encoding="utf-8"))
        if not isinstance(production_settings, dict):
            raise ValueError("production settings root must be an object")
    production_settings.update(
        {
            **path_values,
            "voice_channel_map": config.voice_channel_map,
            "voice_tts": False,
            "start_simhub": False,
        }
    )
    new_root.mkdir(parents=True, exist_ok=False)
    paths.root.mkdir()
    with paths.settings_path.open("x", encoding="utf-8") as stream:
        json.dump(production_settings, stream, indent=2)
    supervisor = CaptureSupervisor(
        config,
        run_dir=new_root,
        owner_pid=owner_pid,
        environ=env,
        python_executable=sys.executable,
        frozen=False,
    )
    capture["instrument_tap"] = str(supervisor.tap_path)
    with (new_root / "capture-config.json").open("x", encoding="utf-8") as stream:
        json.dump(capture, stream, indent=2)
    receipt = {
        "owner": owner,
        "lock_path": str(lock_path),
        "game_point_root": str(paths.root),
        "production_settings_source": str(production_paths.settings_path),
        "reference_archive": str(reference),
        "bank_dir": str(bank),
        "output_device": device,
        "output_host_api": host_api,
        "output_channel_map": list(channels),
        "coach_v2": producer_mode == "coach_v2",
        "producer_mode": producer_mode,
        "start_simhub": False,
        "sidecar_command": supervisor.sidecar_command(),
    }
    with (new_root / "launcher-receipt.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    return supervisor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--capture-config", type=Path, required=True)
    parser.add_argument("--start-sidecar", action="store_true")
    args = parser.parse_args(argv)
    supervisor = prepare_run(args.capture_config, args.run_dir, args.owner_pid)
    try:
        if args.start_sidecar:
            result = supervisor.start_sidecar()
            if not result.ok or supervisor._sidecar_process is None:
                raise RuntimeError(f"owned instrumented sidecar did not start: {result}")
        return run_gui(supervisor)
    finally:
        supervisor.close()


if __name__ == "__main__":
    raise SystemExit(main())
