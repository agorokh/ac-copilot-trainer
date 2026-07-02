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
from importlib.util import find_spec
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8765
DEFAULT_EXTERNAL_BIND = "0.0.0.0"
APP_FOLDER_NAME = "AC Copilot Trainer"
GAME_POINT_FOLDER_NAME = "GamePoint"
_WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _subprocess_kwargs(**kwargs: Any) -> dict[str, Any]:
    if os.name == "nt":
        kwargs.setdefault("creationflags", _WINDOWS_NO_WINDOW)
    return kwargs


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_launcher_path(value: str | None, *, base: Path) -> str | None:
    text = _none_if_blank(value)
    if text is None:
        return None
    root = base.expanduser().resolve(strict=False)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            return None
    else:
        path = path.resolve(strict=False)
    return str(path)


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
    def settings_path(self) -> Path:
        return self.root / "settings.json"

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
    external_bind: str | None = None
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
        resolved_paths = paths or default_paths(env_map)
        from tools.rig_launcher.settings import LauncherSettings

        settings = LauncherSettings.load(resolved_paths.settings_path)
        token = _none_if_blank(env_map.get("AC_COPILOT_SIDECAR_TOKEN"))
        port = _configured_port(env_map.get("AC_COPILOT_SIDECAR_PORT"), settings.sidecar_port)
        external_bind = _configured_external_bind(
            env_map.get("AC_COPILOT_SIDECAR_EXTERNAL_BIND"),
            settings.external_bind,
            token=token,
        )
        voice_tts = _env_bool_or(
            env_map.get("AC_COPILOT_VOICE_TTS"),
            default=bool(settings.voice_tts),
        )
        start_simhub = _env_bool_or(
            env_map.get("AC_COPILOT_START_SIMHUB"),
            default=bool(settings.start_simhub),
        )
        return cls(
            port=port,
            external_bind=external_bind,
            token=token,
            reference_archive=_configured_text(
                env_map.get("AC_COPILOT_REFERENCE_ARCHIVE"),
                settings.reference_archive,
            ),
            voice_bank=_configured_text(env_map.get("AC_COPILOT_VOICE_BANK"), settings.voice_bank),
            voice_tts=voice_tts,
            setup_store=_configured_text(
                env_map.get("AC_COPILOT_SETUP_STORE"),
                settings.setup_store,
            ),
            simhub_exe=_configured_text(env_map.get("AC_COPILOT_SIMHUB_EXE"), settings.simhub_exe),
            start_simhub=start_simhub,
            paths=resolved_paths,
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
        self._environ_upper = {key.upper(): value for key, value in self._environ.items()}
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
            setup_store = _resolve_launcher_path(
                self.config.setup_store,
                base=self._launcher_path_base(),
            )
            if setup_store:
                args.extend(["--setup-store", setup_store])
        return args

    def _launcher_path_base(self) -> Path:
        if self.paths is not None:
            return self.paths.root
        return Path.cwd()

    def _sidecar_working_directory(self) -> str:
        if self._frozen:
            return str(self._launcher_path_base())
        return str(_repo_root())

    def sidecar_environment(self) -> dict[str, str]:
        env = dict(self._environ)
        base = self._launcher_path_base()
        _put_if_present(env, "AC_COPILOT_SIDECAR_TOKEN", self.config.token)
        _put_if_present(
            env,
            "AC_COPILOT_REFERENCE_ARCHIVE",
            _resolve_launcher_path(self.config.reference_archive, base=base),
        )
        _put_if_present(
            env,
            "AC_COPILOT_VOICE_BANK",
            _resolve_launcher_path(self.config.voice_bank, base=base),
        )
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

    def _close_log_handles(self) -> None:
        for handle in self._log_handles:
            try:
                handle.close()
            except OSError:
                pass
        self._log_handles.clear()

    def start_sidecar(self) -> ProbeResult:
        blocking = [check for check in self.preflight() if not check.ok]
        if blocking:
            detail = "; ".join(check.detail or check.name for check in blocking)
            return ProbeResult("sidecar", False, "blocked", detail)
        if self._sidecar_process is not None and self._sidecar_process.poll() is None:
            return ProbeResult("sidecar", True, "running", f"pid={self._sidecar_process.pid}")
        if self._sidecar_process is not None and self._sidecar_process.poll() is not None:
            self._sidecar_process = None
        # Close handles left by a prior supervised spawn before EITHER adopting or spawning, so the
        # adopt early-return below cannot leak a held-open sidecar.log handle (Qodo, PR #387).
        self._close_log_handles()
        # A sidecar from a previous launcher run (or a boot autostart) may already own the port.
        # Spawning a second one would crash the child with WinError 10048 (address already in use)
        # and pop an unhandled-exception dialog. Adopt the healthy instance instead.
        existing = self._read_health()
        if existing.ok:
            return ProbeResult(
                "sidecar",
                True,
                "running",
                f"adopted existing sidecar on port {self.config.port}",
            )
        try:
            self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
            log = self.paths.sidecar_log_path.open("a", encoding="utf-8")
            self._log_handles.append(log)
            self._sidecar_process = self._popen(
                self.sidecar_command(),
                **_subprocess_kwargs(
                    cwd=self._sidecar_working_directory(),
                    env=self.sidecar_environment(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                ),
            )
        except (OSError, FileNotFoundError) as exc:
            self._sidecar_process = None
            self._close_log_handles()
            return ProbeResult("sidecar", False, "start_failed", str(exc))
        return ProbeResult("sidecar", True, "starting", f"pid={self._sidecar_process.pid}")

    def stop_sidecar(self, *, timeout: float = 5.0) -> ProbeResult:
        proc = self._sidecar_process
        if proc is None:
            self._close_log_handles()
            return ProbeResult("sidecar", True, "stopped")
        if proc.poll() is not None:
            self._sidecar_process = None
            self._close_log_handles()
            return ProbeResult("sidecar", True, "stopped", f"exit={proc.poll()}")
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001 - final cleanup should be best-effort
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - no further recovery available
                return ProbeResult("sidecar", False, "stop_failed")
        self._sidecar_process = None
        self._close_log_handles()
        return ProbeResult("sidecar", True, "stopped")

    def poll_status(self) -> GamePointStatus:
        checks = self.preflight()
        sidecar = self._sidecar_process_status()
        health, health_payload = self._read_health_payload()
        if health.ok:
            sidecar = health
        screen = _screen_from_health(health)
        status = GamePointStatus(
            generated_at=time.time(),
            sidecar=sidecar,
            screen=screen,
            hotspot=self.probe_hotspot(),
            voice=self.probe_voice(health_payload),
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

    def probe_voice(self, health_payload: Mapping[str, object] | None = None) -> ProbeResult:
        if health_payload is not None:
            voice = health_payload.get("voice")
            if isinstance(voice, Mapping):
                return _voice_from_health(
                    voice,
                    requested=self._voice_requested(),
                    playback_requested=self._voice_playback_requested(),
                )
            if self._voice_requested():
                return ProbeResult(
                    "voice",
                    False,
                    "DISABLED",
                    "voice requested but sidecar health has no voice runtime status",
                )
        if self.config.reference_archive and self.config.voice_bank:
            return ProbeResult("voice", True, "configured", "reference archive + bank configured")
        if self.config.reference_archive and self.config.voice_tts:
            return ProbeResult("voice", True, "tts", "reference archive + pyttsx3 fallback")
        if self.config.voice_tts:
            return ProbeResult("voice", False, "missing_reference", "TTS enabled without reference")
        if self.config.reference_archive:
            return ProbeResult("voice", True, "observer_only", "reference archive configured")
        return ProbeResult("voice", True, "skipped", "no voice env configured")

    def _voice_requested(self) -> bool:
        return bool(
            self.config.reference_archive or self.config.voice_bank or self.config.voice_tts
        )

    def _voice_playback_requested(self) -> bool:
        return bool(self.config.voice_bank or self.config.voice_tts)

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
            proc = self._run(
                command,
                **_subprocess_kwargs(capture_output=True, text=True, timeout=8),
            )
        except Exception as exc:  # noqa: BLE001 - preflight should report, not crash
            return ProbeResult("hotspot", True, "unavailable", str(exc))
        if proc.returncode != 0:
            return ProbeResult("hotspot", True, "unavailable", _short(proc.stderr))
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ProbeResult("hotspot", True, "unavailable", _short(proc.stdout))
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
            self._popen(
                [str(exe)],
                **_subprocess_kwargs(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            )
        except Exception as exc:  # noqa: BLE001 - visible status beats hidden failure
            return ProbeResult("simhub", False, "start_failed", str(exc))
        return ProbeResult("simhub", True, "started", str(exe))

    def close(self) -> None:
        self.stop_sidecar()
        self._close_log_handles()

    def _read_health(self) -> ProbeResult:
        return self._read_health_payload()[0]

    def _read_health_payload(self) -> tuple[ProbeResult, dict[str, object] | None]:
        url = f"http://{_url_host(self._health_host())}:{self.config.port}/health"
        try:
            with self._urlopen(url, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return ProbeResult("sidecar", False, "unreachable", str(exc)), None
        if not isinstance(payload, dict):
            return (
                ProbeResult("sidecar", False, "unreachable", "health payload is not an object"),
                None,
            )
        peers = int(payload.get("connected_peers") or 0)
        screens = int(payload.get("screen_peers") or 0)
        return (
            ProbeResult("sidecar", True, "healthy", f"peers={peers} screen_peers={screens}"),
            payload,
        )

    def _health_host(self) -> str:
        bind = self.config.external_bind
        if bind and bind not in {DEFAULT_EXTERNAL_BIND, "0.0.0.0", "::"}:
            return bind
        return self.config.host

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
            base = _env_get(self._environ, env_key, case_insensitive=self._environ_upper)
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
                **_subprocess_kwargs(capture_output=True, text=True, timeout=5),
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
        "--collect-data",
        "tools.ai_sidecar",
        "--collect-data",
        "_sounddevice_data",
        "--add-data",
        f"{project_root / 'assets' / 'setups' / '_schema'}{os.pathsep}assets/setups/_schema",
        "--collect-binaries",
        "sounddevice",
        "--hidden-import",
        "tools.ai_sidecar.voice.engine",
        "--hidden-import",
        "tools.ai_sidecar.voice.playback",
        "--hidden-import",
        "numpy",
        "--hidden-import",
        "sounddevice",
        "--hidden-import",
        "pyttsx3",
        "--hidden-import",
        "pyttsx3.drivers",
        "--hidden-import",
        "pyttsx3.drivers.sapi5",
    ]
    fonts_dir = project_root / "src" / "ac_copilot_trainer" / "content" / "fonts"
    if fonts_dir.is_dir():
        # Racing Atelier design faces, loaded FR_PRIVATE by tools.rig_launcher.fonts
        # from sys._MEIPASS/fonts. Present only on packaging branches — guarded so
        # a checkout without the TTFs still builds.
        args.extend(["--add-data", f"{fonts_dir}{os.pathsep}fonts"])
    _append_optional_pyinstaller_module(args, "rtmixer")
    _append_optional_pyinstaller_module(args, "pa_ringbuffer")
    if onefile:
        args.append("--onefile")
    if windowed:
        args.append("--noconsole")
    args.append(str(entry))
    return args


def _append_optional_pyinstaller_module(args: list[str], module: str) -> None:
    if find_spec(module) is None:
        return
    args.extend(["--hidden-import", module, "--collect-binaries", module])


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


def _voice_from_health(
    voice: Mapping[str, object],
    *,
    requested: bool = False,
    playback_requested: bool = False,
) -> ProbeResult:
    configured = bool(voice.get("configured"))
    enabled = bool(voice.get("enabled"))
    state = str(voice.get("state") or "").strip().lower()
    reason = str(voice.get("disabled_reason") or "").strip()
    backend = str(voice.get("backend") or "").strip()

    if enabled:
        label = "tts" if state == "tts" else "enabled"
        detail = f"backend={backend}" if backend else ""
        return ProbeResult("voice", True, label, detail)
    if state == "observer_only":
        if playback_requested:
            return ProbeResult(
                "voice",
                False,
                "DISABLED",
                "voice playback requested but sidecar is observer-only",
            )
        return ProbeResult("voice", True, "observer_only", "reference archive configured")
    if state == "skipped" or not configured:
        if requested:
            return ProbeResult(
                "voice",
                False,
                "DISABLED",
                "voice requested but sidecar was started without voice configuration",
            )
        return ProbeResult("voice", True, "skipped", "no voice env configured")
    if state == "initializing":
        return ProbeResult("voice", False, "initializing", "sidecar voice still initializing")
    detail = reason or "voice coach is not enabled"
    if backend and reason:
        detail = f"{detail} (backend={backend})"
    return ProbeResult("voice", False, "DISABLED", detail)


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


def _configured_port(env_value: str | None, settings_value: int | None) -> int:
    if env_value is not None:
        return _coerce_port(env_value, DEFAULT_PORT)
    if settings_value is not None:
        return _coerce_port(str(settings_value), DEFAULT_PORT)
    return DEFAULT_PORT


def _configured_text(env_value: str | None, settings_value: str | None) -> str | None:
    if env_value is not None:
        return _none_if_blank(env_value)
    return _none_if_blank(settings_value)


def _configured_external_bind(
    env_value: str | None,
    settings_value: str | None,
    *,
    token: str | None,
) -> str | None:
    if env_value is not None:
        return _none_if_blank(env_value)
    if settings_value:
        return settings_value
    if token:
        return DEFAULT_EXTERNAL_BIND
    return None


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_bool_or(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return _env_bool(value)


def _none_if_blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _put_if_present(env: MutableMapping[str, str], key: str, value: str | None) -> None:
    if value:
        env[key] = value


def _env_get(
    env: Mapping[str, str],
    key: str,
    *,
    case_insensitive: Mapping[str, str],
) -> str | None:
    value = env.get(key)
    if value is not None:
        return value
    return case_insensitive.get(key.upper())


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _url_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


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
        "if ($null -eq $profile) {",
        "  $profile = [Windows.Networking.Connectivity.NetworkInformation]::"
        "GetConnectionProfiles() | Select-Object -First 1",
        "}",
        "if ($null -eq $profile) { "
        "throw 'No network connection profile found for Mobile Hotspot.' }",
        "$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]"
        "::CreateFromConnectionProfile($profile)",
        "[pscustomobject]@{",
        "  state = $mgr.TetheringOperationalState.ToString()",
        "  client_count = $mgr.ClientCount",
        "} | ConvertTo-Json -Compress",
    ]
)


def render_status_lines(status: GamePointStatus) -> list[str]:
    summary = ProbeResult("overall", status.ok, "ok" if status.ok else "needs_attention")
    rows = [
        summary,
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
