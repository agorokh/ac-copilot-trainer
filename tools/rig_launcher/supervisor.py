"""Windows Game Point supervisor for the rig-screen sidecar stack.

The launcher is intentionally stdlib-only so it can be frozen with PyInstaller
without introducing another runtime service. OS-facing probes are small and
injectable; tests exercise the behavior without requiring the physical rig.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8765
DEFAULT_EXTERNAL_BIND = "0.0.0.0"
APP_FOLDER_NAME = "AC Copilot Trainer"
GAME_POINT_FOLDER_NAME = "GamePoint"


@dataclass(frozen=True)
class LauncherPaths:
    """Per-user launcher storage paths."""

    root: Path

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def status_path(self) -> Path:
        return self.root / "status.json"

    @property
    def sidecar_log_path(self) -> Path:
        return self.logs_dir / "sidecar.log"


@dataclass(frozen=True)
class ProbeResult:
    """One user-visible preflight or runtime status row."""

    name: str
    ok: bool
    state: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "state": self.state,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GamePointConfig:
    """Configuration read from user env/config, never from committed secrets."""

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    external_bind: str | None = DEFAULT_EXTERNAL_BIND
    token: str | None = None
    reference_archive: str | None = None
    voice_bank: str | None = None
    voice_tts: bool = False
    setup_store: str | None = None
    simhub_exe: str | None = None
    start_simhub: bool = False
    paths: LauncherPaths | None = None

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        paths: LauncherPaths | None = None,
    ) -> GamePointConfig:
        env_map = env if env is not None else os.environ
        port = _coerce_port(env_map.get("AC_COPILOT_SIDECAR_PORT"), DEFAULT_PORT)
        external_bind = env_map.get("AC_COPILOT_SIDECAR_EXTERNAL_BIND", DEFAULT_EXTERNAL_BIND)
        if external_bind == "":
            external_bind = None
        return cls(
            port=port,
            external_bind=external_bind,
            token=_none_if_blank(env_map.get("AC_COPILOT_SIDECAR_TOKEN")),
            reference_archive=_none_if_blank(env_map.get("AC_COPILOT_REFERENCE_ARCHIVE")),
            voice_bank=_none_if_blank(env_map.get("AC_COPILOT_VOICE_BANK")),
            voice_tts=_env_bool(env_map.get("AC_COPILOT_VOICE_TTS")),
            setup_store=_none_if_blank(env_map.get("AC_COPILOT_SETUP_STORE")),
            simhub_exe=_none_if_blank(env_map.get("AC_COPILOT_SIMHUB_EXE")),
            start_simhub=_env_bool(env_map.get("AC_COPILOT_START_SIMHUB")),
            paths=paths or default_paths(env_map),
        )


@dataclass(frozen=True)
class GamePointStatus:
    """Snapshot rendered by the GUI and persisted to status.json."""

    generated_at: float
    sidecar: ProbeResult
    screen: ProbeResult
    hotspot: ProbeResult
    voice: ProbeResult
    simhub: ProbeResult
    log_path: str
    status_path: str
    checks: tuple[ProbeResult, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        rows = (self.sidecar, self.screen, self.hotspot, self.voice, self.simhub, *self.checks)
        return all(row.ok for row in rows if row.state not in {"skipped", "absent"})

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "sidecar": self.sidecar.to_dict(),
            "screen": self.screen.to_dict(),
            "hotspot": self.hotspot.to_dict(),
            "voice": self.voice.to_dict(),
            "simhub": self.simhub.to_dict(),
            "log_path": self.log_path,
            "status_path": self.status_path,
            "checks": [check.to_dict() for check in self.checks],
        }


class GamePointSupervisor:
    """Start and monitor the local rig-screen sidecar stack."""

    def __init__(
        self,
        config: GamePointConfig,
        *,
        environ: Mapping[str, str] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        python_executable: str | None = None,
        frozen: bool | None = None,
    ) -> None:
        self.config = config
        self.paths = config.paths or default_paths(environ)
        self._environ = dict(environ if environ is not None else os.environ)
        self._popen = popen
        self._run = run
        self._urlopen = urlopen
        self._python = python_executable or sys.executable
        self._frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._sidecar_process: Any | None = None
        self._log_handles: list[Any] = []

    def sidecar_command(self) -> list[str]:
        if self._frozen:
            args = [self._python, "--sidecar-child"]
        else:
            args = [self._python, "-m", "tools.ai_sidecar"]
        args.extend(["--port", str(self.config.port)])
        if self.config.external_bind:
            args.extend(["--external-bind", self.config.external_bind])
        else:
            args.extend(["--host", self.config.host])
        if self.config.setup_store:
            args.extend(["--setup-store", self.config.setup_store])
        return args

    def sidecar_environment(self) -> dict[str, str]:
        env = dict(self._environ)
        _put_if_present(env, "AC_COPILOT_SIDECAR_TOKEN", self.config.token)
        _put_if_present(env, "AC_COPILOT_REFERENCE_ARCHIVE", self.config.reference_archive)
        _put_if_present(env, "AC_COPILOT_VOICE_BANK", self.config.voice_bank)
        if self.config.voice_tts:
            env["AC_COPILOT_VOICE_TTS"] = "1"
        return env

    def preflight(self) -> tuple[ProbeResult, ...]:
        checks: list[ProbeResult] = []
        if self.config.external_bind and not _is_loopback(self.config.external_bind):
            if not self.config.token:
                checks.append(
                    ProbeResult(
                        "sidecar_token",
                        False,
                        "missing",
                        "Set AC_COPILOT_SIDECAR_TOKEN before exposing the sidecar.",
                    )
                )
            else:
                checks.append(ProbeResult("sidecar_token", True, "configured"))
        else:
            checks.append(ProbeResult("sidecar_token", True, "loopback"))

        voice_requested = self.config.voice_bank or self.config.voice_tts
        if voice_requested and not self.config.reference_archive:
            checks.append(
                ProbeResult(
                    "voice_reference",
                    False,
                    "missing",
                    "Voice playback needs AC_COPILOT_REFERENCE_ARCHIVE for cue anchoring.",
                )
            )
        elif self.config.reference_archive:
            checks.append(ProbeResult("voice_reference", True, "configured"))
        else:
            checks.append(ProbeResult("voice_reference", True, "skipped"))
        return tuple(checks)

    def start_sidecar(self) -> ProbeResult:
        blocking = [check for check in self.preflight() if not check.ok]
        if blocking:
            detail = "; ".join(check.detail or check.name for check in blocking)
            return ProbeResult("sidecar", False, "blocked", detail)
        if self._sidecar_process is not None and self._sidecar_process.poll() is None:
            return ProbeResult("sidecar", True, "running", f"pid={self._sidecar_process.pid}")
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        log = self.paths.sidecar_log_path.open("a", encoding="utf-8")
        self._log_handles.append(log)
        self._sidecar_process = self._popen(
            self.sidecar_command(),
            cwd=str(Path.cwd()),
            env=self.sidecar_environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return ProbeResult("sidecar", True, "starting", f"pid={self._sidecar_process.pid}")

    def stop_sidecar(self, *, timeout: float = 5.0) -> ProbeResult:
        proc = self._sidecar_process
        if proc is None:
            return ProbeResult("sidecar", True, "stopped")
        if proc.poll() is not None:
            return ProbeResult("sidecar", True, "stopped", f"exit={proc.poll()}")
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001 - final cleanup should be best-effort
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - no further recovery available
                return ProbeResult("sidecar", False, "stop_failed")
        return ProbeResult("sidecar", True, "stopped")

    def poll_status(self) -> GamePointStatus:
        checks = self.preflight()
        sidecar = self._sidecar_process_status()
        health = self._read_health()
        if health.ok:
            sidecar = health
        screen = _screen_from_health(health)
        status = GamePointStatus(
            generated_at=time.time(),
            sidecar=sidecar,
            screen=screen,
            hotspot=self.probe_hotspot(),
            voice=self.probe_voice(),
            simhub=self.probe_simhub(start=self.config.start_simhub),
            log_path=str(self.paths.sidecar_log_path),
            status_path=str(self.paths.status_path),
            checks=checks,
        )
        self.write_status(status)
        return status

    def write_status(self, status: GamePointStatus) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.status_path.write_text(
            json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def probe_voice(self) -> ProbeResult:
        if self.config.reference_archive and self.config.voice_bank:
            return ProbeResult("voice", True, "configured", "reference archive + bank configured")
        if self.config.reference_archive and self.config.voice_tts:
            return ProbeResult("voice", True, "tts", "reference archive + pyttsx3 fallback")
        if self.config.voice_tts:
            return ProbeResult("voice", False, "missing_reference", "TTS enabled without reference")
        if self.config.reference_archive:
            return ProbeResult("voice", True, "observer_only", "reference archive configured")
        return ProbeResult("voice", True, "skipped", "no voice env configured")

    def probe_hotspot(self) -> ProbeResult:
        if os.name != "nt":
            return ProbeResult("hotspot", True, "skipped", "Windows hotspot probe skipped")
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _HOTSPOT_PROBE_SCRIPT,
        ]
        try:
            proc = self._run(command, capture_output=True, text=True, timeout=8)
        except Exception as exc:  # noqa: BLE001 - preflight should report, not crash
            return ProbeResult("hotspot", False, "probe_failed", str(exc))
        if proc.returncode != 0:
            return ProbeResult("hotspot", False, "probe_failed", _short(proc.stderr))
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ProbeResult("hotspot", False, "probe_failed", _short(proc.stdout))
        state = str(payload.get("state") or "unknown")
        clients = payload.get("client_count")
        ok = state.lower() == "on"
        detail = f"state={state}"
        if clients is not None:
            detail += f" clients={clients}"
        return ProbeResult("hotspot", ok, state.lower(), detail)

    def probe_simhub(self, *, start: bool = False) -> ProbeResult:
        exe = self._simhub_exe()
        running = self._simhub_running()
        if running:
            return ProbeResult("simhub", True, "running")
        if exe is None:
            return ProbeResult("simhub", True, "absent", "SimHub executable not found")
        if not start:
            return ProbeResult("simhub", True, "available", str(exe))
        try:
            self._popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001 - visible status beats hidden failure
            return ProbeResult("simhub", False, "start_failed", str(exc))
        return ProbeResult("simhub", True, "started", str(exe))

    def close(self) -> None:
        self.stop_sidecar()
        for handle in self._log_handles:
            try:
                handle.close()
            except OSError:
                pass
        self._log_handles.clear()

    def _read_health(self) -> ProbeResult:
        url = f"http://127.0.0.1:{self.config.port}/health"
        try:
            with self._urlopen(url, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return ProbeResult("sidecar", False, "unreachable", str(exc))
        peers = int(payload.get("connected_peers") or 0)
        screens = int(payload.get("screen_peers") or 0)
        return ProbeResult("sidecar", True, "healthy", f"peers={peers} screen_peers={screens}")

    def _sidecar_process_status(self) -> ProbeResult:
        if self._sidecar_process is None:
            return ProbeResult("sidecar", False, "stopped")
        code = self._sidecar_process.poll()
        if code is None:
            return ProbeResult("sidecar", True, "running", f"pid={self._sidecar_process.pid}")
        return ProbeResult("sidecar", False, "exited", f"exit={code}")

    def _simhub_exe(self) -> Path | None:
        candidates: list[Path] = []
        if self.config.simhub_exe:
            candidates.append(Path(self.config.simhub_exe))
        for env_key in ("ProgramFiles(x86)", "ProgramFiles"):
            base = self._environ.get(env_key)
            if base:
                candidates.append(Path(base) / "SimHub" / "SimHubWPF.exe")
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _simhub_running(self) -> bool:
        if os.name != "nt":
            return False
        try:
            proc = self._run(
                ["tasklist", "/FI", "IMAGENAME eq SimHubWPF.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:  # noqa: BLE001 - inability to query means "not known running"
            return False
        return proc.returncode == 0 and "SimHubWPF.exe" in proc.stdout


def default_paths(env: Mapping[str, str] | None = None) -> LauncherPaths:
    env_map = env if env is not None else os.environ
    override = _none_if_blank(env_map.get("AC_COPILOT_GAME_POINT_DIR"))
    if override:
        return LauncherPaths(Path(override).expanduser())
    local_app_data = _none_if_blank(env_map.get("LOCALAPPDATA"))
    if local_app_data:
        root = Path(local_app_data) / APP_FOLDER_NAME / GAME_POINT_FOLDER_NAME
    else:
        root = Path.home() / ".ac-copilot-trainer" / GAME_POINT_FOLDER_NAME
    return LauncherPaths(root)


def build_pyinstaller_args(
    project_root: Path,
    *,
    onefile: bool = True,
    windowed: bool = True,
) -> list[str]:
    entry = project_root / "tools" / "rig_launcher" / "__main__.py"
    args = [
        "--name",
        "AC-Copilot-Game-Point",
        "--clean",
        "--collect-submodules",
        "tools.ai_sidecar",
        "--collect-submodules",
        "tools.rig_launcher",
        "--hidden-import",
        "tools.ai_sidecar.voice.engine",
        "--hidden-import",
        "tools.ai_sidecar.voice.playback",
    ]
    if onefile:
        args.append("--onefile")
    if windowed:
        args.append("--noconsole")
    args.append(str(entry))
    return args


def _screen_from_health(health: ProbeResult) -> ProbeResult:
    if not health.ok:
        return ProbeResult("screen", False, "unknown", "sidecar health unavailable")
    marker = "screen_peers="
    count = 0
    if marker in health.detail:
        tail = health.detail.split(marker, 1)[1].split()[0]
        try:
            count = int(tail)
        except ValueError:
            count = 0
    if count > 0:
        return ProbeResult("screen", True, "connected", f"screen_peers={count}")
    return ProbeResult("screen", False, "waiting", "no ESP32 screen peer connected")


def _coerce_port(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        port = int(value)
    except ValueError:
        return default
    if 1 <= port <= 65535:
        return port
    return default


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _none_if_blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _put_if_present(env: MutableMapping[str, str], key: str, value: str | None) -> None:
    if value:
        env[key] = value


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _short(text: str | None, limit: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "..."


_HOTSPOT_PROBE_SCRIPT = "\n".join(
    [
        "$ErrorActionPreference = 'Stop'",
        "[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,"
        "Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null",
        "[Windows.Networking.Connectivity.NetworkInformation,"
        "Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null",
        "$profile = "
        "[Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()",
        "if ($null -eq $profile) { "
        "throw 'No active internet connection profile for Mobile Hotspot.' }",
        "$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]"
        "::CreateFromConnectionProfile($profile)",
        "[pscustomobject]@{",
        "  state = $mgr.TetheringOperationalState.ToString()",
        "  client_count = $mgr.ClientCount",
        "} | ConvertTo-Json -Compress",
    ]
)


def render_status_lines(status: GamePointStatus) -> list[str]:
    rows = [
        status.sidecar,
        status.screen,
        status.hotspot,
        status.voice,
        status.simhub,
        *status.checks,
    ]
    return [f"{row.name}: {row.state}{(' - ' + row.detail) if row.detail else ''}" for row in rows]


def command_without_secrets(command: Iterable[str]) -> str:
    """Render a command for logs/status. Tokens are env-only, so this is safe."""
    return " ".join(str(part) for part in command)
