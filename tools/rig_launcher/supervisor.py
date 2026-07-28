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
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from importlib.util import find_spec
from pathlib import Path, PureWindowsPath
from typing import Any

from tools.rig_launcher.build_info import BuildInfo, resolve_build_info, write_runtime_hook

DEFAULT_PORT = 8765
DEFAULT_EXTERNAL_BIND = "0.0.0.0"
APP_FOLDER_NAME = "AC Copilot Trainer"
GAME_POINT_FOLDER_NAME = "GamePoint"

#: Arm sources for the voice phrase bank (issue #672 Part B). ``env`` wins over ``settings``
#: in :meth:`GamePointConfig.from_env`, including the set-but-blank case that *clears* a
#: settings-configured bank — the state an operator most needs to be able to see.
VOICE_BANK_SOURCE_ENV = "env"
VOICE_BANK_SOURCE_SETTINGS = "settings"
VOICE_BANK_SOURCE_UNSET = "unset"

#: Voice-row state emitted when the sidecar's resolved playback endpoint is the same one
#: Assetto Corsa / FMOD plays through (issue #672 Part A). Warn-only by construction: the
#: ``ProbeResult`` stays ``ok=True``, so it can never block ``start_sidecar``.
VOICE_STATE_SHARED_ENDPOINT = "shared_endpoint"

#: States of the discrete ``voice_endpoint`` check row persisted to ``status.json``. All four
#: are ``ok=True``; they exist so an inert check ("we never declared AC's endpoint") is never
#: mistaken for a clean bill of health ("we checked and they differ").
_ENDPOINT_STATE_SHARED = "shared"
_ENDPOINT_STATE_DISTINCT = "distinct"
_ENDPOINT_STATE_UNDECLARED = "undeclared"
_ENDPOINT_STATE_UNKNOWN = "unknown"

#: PortAudio's MME host API truncates device names to 31 characters (``MAXPNAMELEN`` is 32
#: including the NUL), so the sidecar can report a strict prefix of the full Windows endpoint
#: name. Prefix matching exists *only* to absorb that truncation, so it is accepted only when
#: the shorter name is long enough to actually BE a truncation artifact. A loose floor is not
#: safe here: a generic 8-character ``Speakers`` would prefix-match ``Speakers (USB Sound
#: Device)`` and raise a false collision, telling the operator to reroute already-isolated
#: voice audio — the exact cry-wolf failure this check exists to avoid (PR #707 review).
_MME_NAME_MAX_LEN = 31
_WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


class _CaseInsensitiveEnv(Mapping[str, str]):
    """Mapping view that preserves original keys but reads env names like Windows."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._data = dict(env)
        self._keys = {key.upper(): key for key in self._data}

    def __getitem__(self, key: str) -> str:
        if key in self._data:
            return self._data[key]
        return self._data[self._keys[key.upper()]]

    def __iter__(self) -> Iterable[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: str | None = None) -> str | None:
        if key in self._data:
            return self._data[key]
        original = self._keys.get(key.upper())
        if original is None:
            return default
        return self._data[original]


def _env_view(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return _CaseInsensitiveEnv(env if env is not None else os.environ)


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
    # Preserve an absolute Windows drive/UNC path when tests or configuration are inspected from
    # a non-Windows host; on the rig, Path already recognizes the same value as absolute.
    if not path.is_absolute() and PureWindowsPath(text).is_absolute():
        return str(PureWindowsPath(text))
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

    @property
    def resilient_log_path(self) -> Path:
        return self.logs_dir / "resilient-launch.log"


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
    #: COM port for the USB-serial rig-screen transport (issue #463). When set, the
    #: sidecar serves the screen over USB CDC — no Windows Mobile Hotspot needed.
    serial_port: str | None = None
    reference_archive: str | None = None
    alien_line: str | None = None
    voice_bank: str | None = None
    voice_tts: bool = False
    #: Where the resolved ``voice_bank`` came from — ``"env"`` (``AC_COPILOT_VOICE_BANK``
    #: was present, including set-but-blank, which *clears* the settings value), ``"settings"``
    #: (settings.json supplied it), or ``"unset"`` (neither). Issue #672 Part B: the effective
    #: value was already visible but its *source* was not, so a bank parked or force-armed via
    #: the environment could not be diagnosed from the Voice row or status.json.
    voice_bank_source: str = VOICE_BANK_SOURCE_UNSET
    #: Name of the output endpoint Assetto Corsa / FMOD plays through (issue #672 Part A).
    #: Declared by the operator because the launcher cannot read AC's device; the voice
    #: endpoint probe warns (never blocks) when the sidecar resolves voice onto the same one.
    ac_audio_device: str | None = None
    setup_store: str | None = None
    simhub_exe: str | None = None
    start_simhub: bool = False
    resilient_car: str | None = None
    resilient_track: str | None = None
    resilient_layout: str | None = None
    resilient_cm_exe: str | None = None
    #: Manage the tablet dashboard's ``adb reverse`` USB tunnel (issue #567). Opt-in
    #: (house pattern, cf. ``start_simhub``): off by default so CI / non-rig hosts never
    #: shell out to adb; the rig sets ``AC_COPILOT_MANAGE_TABLET_TUNNEL=1``.
    manage_tablet_tunnel: bool = False
    #: Tablet-tunnel adb overrides, routed through the config SSOT rather than read ad-hoc
    #: (#568 review): explicit ``adb`` path, and the device serial to disambiguate when more
    #: than one authorized device is attached.
    adb_path: str | None = None
    adb_serial: str | None = None
    #: Test/embedding override for the machine-wide rig ownership file. Production uses the
    #: Harness LocalAppData path from ``default_rig_session_lock_path``.
    rig_lock_path: Path | None = None
    paths: LauncherPaths | None = None

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        paths: LauncherPaths | None = None,
    ) -> GamePointConfig:
        env_map = _env_view(env)
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
        manage_tablet_tunnel = _env_bool_or(
            env_map.get("AC_COPILOT_MANAGE_TABLET_TUNNEL"),
            default=False,
        )
        return cls(
            adb_path=_none_if_blank(env_map.get("AC_COPILOT_ADB")),
            adb_serial=_none_if_blank(env_map.get("AC_COPILOT_ADB_SERIAL")),
            port=port,
            external_bind=external_bind,
            token=token,
            serial_port=_none_if_blank(env_map.get("AC_COPILOT_SIDECAR_SERIAL_PORT")),
            reference_archive=_configured_text(
                env_map.get("AC_COPILOT_REFERENCE_ARCHIVE"),
                settings.reference_archive,
            ),
            alien_line=_configured_text(
                env_map.get("AC_COPILOT_ALIEN_LINE"),
                settings.alien_line,
            ),
            voice_bank=_configured_text(env_map.get("AC_COPILOT_VOICE_BANK"), settings.voice_bank),
            voice_bank_source=_configured_source(
                env_map.get("AC_COPILOT_VOICE_BANK"),
                settings.voice_bank,
            ),
            voice_tts=voice_tts,
            ac_audio_device=_configured_text(
                env_map.get("AC_COPILOT_AC_AUDIO_DEVICE"),
                settings.ac_audio_device,
            ),
            setup_store=_configured_text(
                env_map.get("AC_COPILOT_SETUP_STORE"),
                settings.setup_store,
            ),
            simhub_exe=_configured_text(env_map.get("AC_COPILOT_SIMHUB_EXE"), settings.simhub_exe),
            start_simhub=start_simhub,
            resilient_car=_configured_text(
                env_map.get("AC_COPILOT_RESILIENT_CAR"),
                settings.resilient_car,
            ),
            resilient_track=_configured_text(
                env_map.get("AC_COPILOT_RESILIENT_TRACK"),
                settings.resilient_track,
            ),
            resilient_layout=_configured_text(
                env_map.get("AC_COPILOT_RESILIENT_LAYOUT"),
                settings.resilient_layout,
            ),
            resilient_cm_exe=_configured_text(
                env_map.get("AC_COPILOT_RESILIENT_CM_EXE"),
                settings.resilient_cm_exe,
            ),
            manage_tablet_tunnel=manage_tablet_tunnel,
            paths=resolved_paths,
        )


@dataclass(frozen=True)
class GamePointStatus:
    """Snapshot rendered by the GUI and persisted to status.json."""

    generated_at: float
    sidecar: ProbeResult
    screen: ProbeResult
    voice: ProbeResult
    simhub: ProbeResult
    log_path: str
    status_path: str
    #: Tablet dashboard ``adb reverse`` USB tunnel keeper (issue #567). Defaulted so
    #: direct constructions (and pre-#567 callers) stay valid; ``poll_status`` fills it.
    tablet: ProbeResult = field(default_factory=lambda: ProbeResult("tablet", True, "unmanaged"))
    resilient: ProbeResult = field(
        default_factory=lambda: ProbeResult("ac_session", True, "unconfigured")
    )
    checks: tuple[ProbeResult, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        rows = (
            self.sidecar,
            self.screen,
            self.voice,
            self.simhub,
            self.tablet,
            self.resilient,
            *self.checks,
        )
        return all(row.ok for row in rows if row.state not in {"skipped", "absent"})

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "sidecar": self.sidecar.to_dict(),
            "screen": self.screen.to_dict(),
            "voice": self.voice.to_dict(),
            "simhub": self.simhub.to_dict(),
            "tablet": self.tablet.to_dict(),
            "resilient": self.resilient.to_dict(),
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
        self._environ = _env_view(environ)
        self._popen = popen
        self._run = run
        self._urlopen = urlopen
        self._python = python_executable or sys.executable
        self._frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._sidecar_process: Any | None = None
        self._resilient_process: Any | None = None
        self._resilient_log_handle: Any | None = None
        self._log_handles: list[Any] = []
        # The GUI polls on a worker thread while START / toggle run on the Tk main thread, so the
        # sidecar process handle + log handles are touched from two threads. Serialize those
        # mutations/reads with an RLock (re-entrant: close()→stop_sidecar() nests). The lock is
        # held only around the quick handle bookkeeping — never around the slow adb/HTTP probes —
        # so it cannot re-introduce the UI freeze the worker thread was added to avoid (#568).
        self._proc_lock = threading.RLock()

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
        if self.config.serial_port:
            args.extend(["--serial-port", self.config.serial_port])
        if self.config.setup_store:
            setup_store = _resolve_launcher_path(
                self.config.setup_store,
                base=self._launcher_path_base(),
            )
            if setup_store:
                args.extend(["--setup-store", setup_store])
        return args

    def resilient_command(self) -> list[str]:
        """Build the canonical operator-session command for source or frozen launchers."""
        if self._frozen:
            args = [self._python, "--resilient-launch-child"]
        else:
            args = [self._python, "-m", "tools.ac_harness.resilient_launch"]
        if self.config.resilient_car:
            args.extend(["--car", self.config.resilient_car])
        if self.config.resilient_track:
            args.extend(["--track", self.config.resilient_track])
        if self.config.resilient_layout:
            args.extend(["--layout", self.config.resilient_layout])
        if self.config.resilient_cm_exe:
            cm_exe = _resolve_launcher_path(
                self.config.resilient_cm_exe,
                base=self._launcher_path_base(),
            )
            if cm_exe is None:
                raise ValueError(
                    "resilient_cm_exe must be absolute or stay within the Game Point folder"
                )
            args.extend(["--cm-exe", cm_exe])
        if self.config.rig_lock_path is not None:
            args.extend(["--rig-lock-path", str(self.config.rig_lock_path)])
        args.extend(["--rig-release-path", str(self._rig_release_path())])
        # Game Point polls the authoritative lock byte for status. Give a real launcher enough
        # grace to outwait that microsecond probe rather than false-failing on a zero-timeout race.
        args.extend(["--rig-lock-timeout", "1.0"])
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
            "AC_COPILOT_ALIEN_LINE",
            _resolve_launcher_path(self.config.alien_line, base=base),
        )
        if self.config.alien_line:
            # An alien frontier is a Coach v2 feature; make the launcher setting operational rather
            # than silently leaving the legacy observer active behind an undocumented prerequisite.
            env["AC_COPILOT_COACH_V2"] = "1"
        _put_if_present(
            env,
            "AC_COPILOT_VOICE_BANK",
            _resolve_launcher_path(self.config.voice_bank, base=base),
        )
        if self.config.voice_tts:
            env["AC_COPILOT_VOICE_TTS"] = "1"
        return env

    def simhub_environment(self) -> dict[str, str]:
        """Expose the launcher's resolved sidecar endpoint to the SimHub plugin."""

        env = dict(self._environ)
        env["AC_COPILOT_SIDECAR_PORT"] = str(self.config.port)
        _put_if_present(
            env,
            "AC_COPILOT_SIDECAR_EXTERNAL_BIND",
            self.config.external_bind,
        )
        _put_if_present(env, "AC_COPILOT_SIDECAR_TOKEN", self.config.token)
        return env

    def preflight(
        self,
        health_payload: Mapping[str, object] | None = None,
    ) -> tuple[ProbeResult, ...]:
        """Return the preflight check rows persisted to ``status.json``.

        ``health_payload`` is optional so the pre-start call in :meth:`start_sidecar` (where
        no sidecar is up yet) keeps working; it only sharpens the ``voice_endpoint`` row,
        which needs the sidecar's live device name.
        """
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

        # Issue #672 Part A. Always ok=True, so `start_sidecar`'s blocking scan
        # (`[c for c in self.preflight() if not c.ok]`) can never trip on it.
        checks.append(self._voice_endpoint_verdict(health_payload))
        return tuple(checks)

    def _close_log_handles(self) -> None:
        for handle in self._log_handles:
            try:
                handle.close()
            except OSError:
                pass
        self._log_handles.clear()

    def start_sidecar(self) -> ProbeResult:
        # start_sidecar is only ever called from the main thread (GUI button / CLI), never from
        # the poll worker — so the lock only needs to guard the quick handle bookkeeping against
        # the worker's concurrent _sidecar_process_status() READ. Crucially it is NOT held across
        # the slow _read_health() adoption probe below (network I/O), so a START can't stall a
        # concurrent status poll for the probe's timeout (#568 self-hosted reviewer).
        blocking = [check for check in self.preflight() if not check.ok]
        if blocking:
            detail = "; ".join(check.detail or check.name for check in blocking)
            return ProbeResult("sidecar", False, "blocked", detail)
        with self._proc_lock:
            if self._sidecar_process is not None and self._sidecar_process.poll() is None:
                return ProbeResult("sidecar", True, "running", f"pid={self._sidecar_process.pid}")
            if self._sidecar_process is not None and self._sidecar_process.poll() is not None:
                self._sidecar_process = None
            # Close handles left by a prior supervised spawn before EITHER adopting or spawning,
            # so the adopt early-return below cannot leak a held-open sidecar.log handle (Qodo,
            # PR #387).
            self._close_log_handles()
        # A sidecar from a previous launcher run (or a boot autostart) may already own the port.
        # Spawning a second one would crash the child with WinError 10048 (address already in
        # use) and pop an unhandled-exception dialog. Adopt the healthy instance. Probe OUTSIDE
        # the lock — start_sidecar is main-thread-serial, so no concurrent start races this gap.
        existing = self._read_health()
        if existing.ok:
            return ProbeResult(
                "sidecar",
                True,
                "running",
                f"adopted existing sidecar on port {self.config.port}",
            )
        with self._proc_lock:
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

    def start_resilient_session(self) -> ProbeResult:
        """Start one detached resilient AC session from the canonical Game Point surface."""
        missing = [
            name
            for name, value in (
                ("resilient_car", self.config.resilient_car),
                ("resilient_track", self.config.resilient_track),
            )
            if not value
        ]
        if missing:
            return ProbeResult(
                "ac_session",
                False,
                "unconfigured",
                f"set {', '.join(missing)} in settings.json or the matching environment variables",
            )
        if (
            self.config.resilient_cm_exe
            and _resolve_launcher_path(
                self.config.resilient_cm_exe,
                base=self._launcher_path_base(),
            )
            is None
        ):
            return ProbeResult(
                "ac_session",
                False,
                "unconfigured",
                "resilient_cm_exe must be absolute or stay within the Game Point folder",
            )
        with self._proc_lock:
            if self._resilient_process is not None and self._resilient_process.poll() is None:
                local_pid = self._resilient_process.pid
            else:
                local_pid = None
        if local_pid is not None:
            owner = self._rig_session_owner()
            if owner is not None:
                return self._rig_owner_status(owner)
            return ProbeResult(
                "ac_session",
                False,
                "stabilizing",
                f"pid={local_pid}; waiting for stable handoff",
            )
        owner = self._rig_session_owner()
        if owner is not None:
            return self._rig_owner_status(owner)
        with self._proc_lock:
            if self._resilient_process is not None and self._resilient_process.poll() is None:
                return ProbeResult(
                    "ac_session",
                    False,
                    "stabilizing",
                    f"pid={self._resilient_process.pid}; waiting for stable handoff",
                )
            if self._resilient_log_handle is not None:
                try:
                    self._resilient_log_handle.close()
                except OSError:
                    pass
                self._resilient_log_handle = None
            try:
                try:
                    self._rig_release_path().unlink()
                except FileNotFoundError:
                    pass
                self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
                log = self.paths.resilient_log_path.open("a", encoding="utf-8")
                self._resilient_log_handle = log
                self._resilient_process = self._popen(
                    self.resilient_command(),
                    **_subprocess_kwargs(
                        cwd=self._sidecar_working_directory(),
                        env=dict(self._environ),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    ),
                )
            except (OSError, FileNotFoundError) as exc:
                self._resilient_process = None
                if self._resilient_log_handle is not None:
                    try:
                        self._resilient_log_handle.close()
                    except OSError:
                        pass
                    self._resilient_log_handle = None
                return ProbeResult("ac_session", False, "start_failed", str(exc))
            return ProbeResult(
                "ac_session",
                False,
                "starting",
                f"pid={self._resilient_process.pid}; log={self.paths.resilient_log_path}",
            )

    def release_resilient_session(self) -> ProbeResult:
        """Signal the no-console resilient child to release machine-wide ownership.

        The child may outlive Game Point, so this uses a shared sentinel next to the authoritative
        lock rather than a transient process handle. AC itself is deliberately left running.
        """
        with self._proc_lock:
            local_running = (
                self._resilient_process is not None and self._resilient_process.poll() is None
            )
        owner = self._rig_session_owner()
        if not local_running and owner is None:
            return ProbeResult("ac_session", True, "idle", "no resilient session owns the rig")
        known_kind = (
            owner.get("session_kind")
            if owner is not None and owner.get("cwd") != "unknown"
            else None
        )
        if not local_running and known_kind not in {None, "resilient_launch"}:
            return ProbeResult(
                "ac_session",
                False,
                "release_unsupported",
                "rig owner is not a Stable AC session and does not honor Release AC",
            )
        release_path = self._rig_release_path()
        try:
            release_path.parent.mkdir(parents=True, exist_ok=True)
            release_path.touch()
        except OSError as exc:
            return ProbeResult("ac_session", False, "release_failed", str(exc))
        return ProbeResult(
            "ac_session",
            True,
            "release_requested",
            f"ownership release requested; AC left live; signal={release_path}",
        )

    def _resilient_process_status(self) -> ProbeResult:
        with self._proc_lock:
            process = self._resilient_process
            rc = process.poll() if process is not None else None
            pid = process.pid if process is not None else None
        if process is not None and rc is None:
            owner = self._rig_session_owner()
            if owner is not None:
                return self._rig_owner_status(owner)
            return ProbeResult(
                "ac_session",
                False,
                "stabilizing",
                f"pid={pid}; waiting for stable handoff",
            )
        # Lock-file I/O can block on Windows sharing violations. Keep it outside _proc_lock,
        # which also serializes START/stop mutations on the Tk thread.
        owner = self._rig_session_owner()
        if owner is not None:
            return self._rig_owner_status(owner)
        if process is None:
            if not self.config.resilient_car or not self.config.resilient_track:
                return ProbeResult(
                    "ac_session",
                    True,
                    "unconfigured",
                    "set resilient_car and resilient_track in settings",
                )
            if (
                self.config.resilient_cm_exe
                and _resolve_launcher_path(
                    self.config.resilient_cm_exe,
                    base=self._launcher_path_base(),
                )
                is None
            ):
                return ProbeResult(
                    "ac_session",
                    False,
                    "unconfigured",
                    "resilient_cm_exe must be absolute or stay within the Game Point folder",
                )
            return ProbeResult(
                "ac_session",
                True,
                "idle",
                "press STABLE AC to start a driver session",
            )
        return ProbeResult(
            "ac_session",
            rc == 0,
            "exited",
            f"exit={rc}; log={self.paths.resilient_log_path}",
        )

    @staticmethod
    def _rig_owner_status(owner: Mapping[str, Any]) -> ProbeResult:
        if owner.get("cwd") == "unknown":
            return ProbeResult(
                "ac_session",
                False,
                "unknown",
                "rig lock status unavailable; refusing Stable AC until the lock can be probed",
            )
        session_kind = owner.get("session_kind")
        if session_kind not in (None, "", "resilient_launch"):
            return ProbeResult(
                "ac_session",
                False,
                "busy_other_session",
                f"rig owned by session_kind={session_kind}; Stable AC was not started",
            )
        phase = str(owner.get("phase") or "").strip().lower()
        detail = " ".join(
            f"{key}={owner[key]}"
            for key in ("pid", "car", "track", "started_at", "phase")
            if owner.get(key) not in (None, "")
        )
        if phase == "wedged":
            # #630 Part A — the launcher proved a stable session, handed it over, and then watched
            # its render packet pin while physics kept advancing (#627 §2). That is a frozen
            # session needing a relaunch, NOT a startup still in progress, so it must not fall
            # through to "stabilizing" and be presented as an in-progress start.
            return ProbeResult(
                "ac_session",
                False,
                "wedged",
                "resilient session WEDGED after handoff (render frozen); press RELEASE AC, "
                "wait for the rig to report idle, then STABLE AC"
                + (f": {detail}" if detail else ""),
            )
        if phase != "stable":
            return ProbeResult(
                "ac_session",
                False,
                "stabilizing",
                "resilient owner has not completed stability proof"
                + (f": {detail}" if detail else ""),
            )
        return ProbeResult(
            "ac_session",
            True,
            "running",
            f"stable session{(': ' + detail) if detail else ''}",
        )

    def _rig_session_owner(self) -> dict[str, Any] | None:
        """Read machine-wide ownership so restarted Game Point instances adopt status truth."""
        if self.config.rig_lock_path is None and sys.platform != "win32":
            return None
        from tools.ac_harness.rig_lock import read_rig_session_owner

        return read_rig_session_owner(self._rig_lock_path())

    def _rig_lock_path(self) -> Path:
        from tools.ac_harness.rig_lock import default_rig_session_lock_path

        return self.config.rig_lock_path or default_rig_session_lock_path(
            local_app_data=self._environ.get("LOCALAPPDATA")
        )

    def _rig_release_path(self) -> Path:
        return self._rig_lock_path().parent / "rig-session.release"

    def stop_sidecar(self, *, timeout: float = 5.0) -> ProbeResult:
        with self._proc_lock:
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

    def poll_status(self, *, start_simhub: bool | None = None) -> GamePointStatus:
        """Snapshot every probe and persist status.json.

        ``start_simhub`` gates the SimHub *launch* side effect: ``None`` (default) honors the
        configured auto-start (preserves the one-shot START/toggle behavior), while an explicit
        ``False`` makes the poll **read-only** — the continuous GUI tick passes ``False`` so a
        closed/crashed SimHub is not relaunched on every 5 s interval (#568 review).
        """
        start_sim = self.config.start_simhub if start_simhub is None else start_simhub
        sidecar = self._sidecar_process_status()
        health, health_payload = self._read_health_payload()
        # Health first: the `voice_endpoint` check (#672 Part A) needs the sidecar's live
        # device name, which only the health payload carries.
        checks = self.preflight(health_payload)
        if health.ok:
            sidecar = health
        screen = _screen_from_health(health)
        status = GamePointStatus(
            generated_at=time.time(),
            sidecar=sidecar,
            screen=screen,
            voice=self.probe_voice(health_payload),
            simhub=self.probe_simhub(start=start_sim),
            tablet=self.probe_tablet(health_payload),
            resilient=self._resilient_process_status(),
            log_path=str(self.paths.sidecar_log_path),
            status_path=str(self.paths.status_path),
            checks=checks,
        )
        self.write_status(status)
        return status

    def probe_tablet(self, health_payload: Mapping[str, object] | None = None) -> ProbeResult:
        """Keep the tablet dashboard's ``adb reverse`` USB tunnel alive (issue #567).

        Opt-in via ``manage_tablet_tunnel`` (off → ``unmanaged``, no adb calls, so CI and
        non-rig hosts are untouched). When on, (re)asserts the tunnel idempotently and, once
        it is up, upgrades the row to ``dash-connected`` if the sidecar's ``/health`` reports
        a browser peer — i.e. a real dashboard, not just a live pipe.
        """
        if not self.config.manage_tablet_tunnel:
            return ProbeResult(
                "tablet",
                True,
                "unmanaged",
                "adb tunnel keeper off (set AC_COPILOT_MANAGE_TABLET_TUNNEL=1)",
            )
        # `adb reverse` forwards the tablet's localhost:<port> to the PC's LOOPBACK:<port>
        # (Android's documented contract). A concrete non-loopback external bind (e.g.
        # 192.168.x.x) leaves nothing on PC loopback, so the tunnel would read `tunnel-up`
        # yet the dashboard can't connect. Loopback and wildcard (0.0.0.0/::, which includes
        # loopback) are fine; a concrete IP is a misconfiguration — fail loud (#568 review).
        bind = self.config.external_bind
        if bind and bind not in {DEFAULT_EXTERNAL_BIND, "0.0.0.0", "::"} and not _is_loopback(bind):
            return ProbeResult(
                "tablet",
                False,
                "bind-unreachable",
                f"sidecar bound to {bind}, but adb reverse targets PC loopback — "
                "bind to 127.0.0.1 or 0.0.0.0 for the managed tablet tunnel",
            )
        from tools.rig_launcher.tablet_tunnel import ensure_tablet_reverse

        result = ensure_tablet_reverse(
            self._run,
            self.config.port,
            env=self._environ,
            adb=self.config.adb_path,
            serial=self.config.adb_serial,
        )
        # The stale-sidecar / dash-connected refinements only apply when the sidecar actually
        # answered /health (a Mapping). If health_payload is None the sidecar is simply DOWN —
        # not stale — and its own row already surfaces that; the tunnel itself is up, so don't
        # false-flag `stale-sidecar` off a probe against a dead port (#568 self-hosted reviewer).
        if result.state == "tunnel-up" and isinstance(health_payload, Mapping):
            # The tunnel being up doesn't prove the DASHBOARD loads: a stale sidecar 426s the
            # route (not compiled in), and a build with the handler but a missing bundled HTML
            # asset 404s it — the /health `endpoints` advertisement (a static list) can't
            # distinguish either. So confirm against REALITY with a direct loopback, token-aware
            # GET /tablet/dash == 200 before accepting the tunnel as usable (#568 review). The
            # probe only runs when the sidecar answered /health (payload present); a stopped
            # sidecar is handled by its own row, not flagged here.
            if self._probe_endpoint_status("/tablet/dash") != 200:
                return ProbeResult(
                    "tablet",
                    False,
                    "stale-sidecar",
                    "sidecar does not serve /tablet/dash (stale build or missing asset) — "
                    "rebuild the launcher",
                )
            try:
                browser_peers = int(health_payload.get("browser_peers") or 0)
            except (TypeError, ValueError):
                browser_peers = 0
            if browser_peers > 0:
                return ProbeResult(
                    "tablet", True, "dash-connected", f"browser_peers={browser_peers}"
                )
        return ProbeResult("tablet", result.ok, result.state, result.detail)

    def self_test_endpoints(self, *, wait_timeout: float = 10.0) -> tuple[ProbeResult, ...]:
        """Release-gate smoke: the running build MUST serve the tablet routes with 200.

        A packaged binary that predates ``/tablet/dash`` or ``/tablet/voice`` answers those
        paths with ``426 Upgrade Required`` (the bare WS handler), so a stale ``dist/`` EXE
        ships the dashboard broken. This probe turns that silent failure into a non-zero
        launcher self-test (issue #567). Waits up to ``wait_timeout`` for ``/health`` first
        so it can gate a freshly started sidecar.
        """
        self._wait_for_health(timeout=wait_timeout)
        results: list[ProbeResult] = []
        for path in ("/tablet/dash", "/tablet/voice"):
            code = self._probe_endpoint_status(path)
            name = f"endpoint {path}"
            if code == 200:
                results.append(ProbeResult(name, True, "serving"))
            elif code is None:
                results.append(ProbeResult(name, False, "unreachable", "sidecar did not answer"))
            else:
                results.append(
                    ProbeResult(
                        name,
                        False,
                        "stale_build",
                        f"HTTP {code} — this build predates the route (expected 200)",
                    )
                )
        return tuple(results)

    def _wait_for_health(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self._read_health().ok:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

    def _probe_endpoint_status(self, path: str) -> int | None:
        url = f"http://{_url_host(self._health_host())}:{self.config.port}{path}"
        # server.make_process_request token-gates /tablet/* for NON-loopback peers, so on a
        # concrete-IP external bind + token the bare probe would 401 and misreport `stale_build`.
        # Carry the token when configured (the sidecar ignores it for loopback peers). The header
        # name mirrors external_protocol.AUTH_HEADER; kept literal so the launcher stays decoupled.
        target: str | urllib.request.Request = url
        if self.config.token:
            target = urllib.request.Request(url, headers={"X-AC-Copilot-Token": self.config.token})
        try:
            with self._urlopen(target, timeout=2.0) as response:
                code = getattr(response, "status", None)
                if code is None:
                    code = getattr(response, "code", 200)
                return int(code)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (OSError, urllib.error.URLError, TimeoutError):
            return None

    def write_status(self, status: GamePointStatus) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.status_path.write_text(
            json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def probe_voice(self, health_payload: Mapping[str, object] | None = None) -> ProbeResult:
        return self._with_voice_bank_source(
            self._flag_shared_endpoint(self._probe_voice_base(health_payload), health_payload)
        )

    def _probe_voice_base(self, health_payload: Mapping[str, object] | None) -> ProbeResult:
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

    def _with_voice_bank_source(self, result: ProbeResult) -> ProbeResult:
        """Append the phrase-bank arm source to the Voice row detail (issue #672 Part B).

        The *effective* bank was already folded into the config, but its **source** was not
        visible anywhere — so a bank force-armed from the environment, or parked by a
        set-but-blank ``AC_COPILOT_VOICE_BANK`` that cleared a settings value, could not be
        diagnosed from the Voice row or ``status.json``. ``unset`` adds no noise.
        """
        source = self.config.voice_bank_source
        if source == VOICE_BANK_SOURCE_UNSET:
            return result
        armed = "armed" if self.config.voice_bank else "cleared"
        note = f"bank {armed} via {source}"
        detail = f"{result.detail}; {note}" if result.detail else note
        return replace(result, detail=detail)

    def _flag_shared_endpoint(
        self,
        result: ProbeResult,
        health_payload: Mapping[str, object] | None,
    ) -> ProbeResult:
        """Warn on the Voice row when voice landed on Assetto Corsa's own endpoint (#672 Part A).

        Warn-only by construction: ``ok`` is preserved (never demoted), so this can neither
        block ``start_sidecar`` nor flip the aggregate ``GamePointStatus.ok``. The row is still
        *visible* because :data:`VOICE_STATE_SHARED_ENDPOINT` is a themed warn state — the
        launcher renders ``checks`` nowhere, so a discrete check row alone would be invisible.
        """
        if not result.ok:
            # An already-failing Voice row carries a more urgent message; do not overwrite it.
            return result
        verdict = self._voice_endpoint_verdict(health_payload)
        if verdict.state != _ENDPOINT_STATE_SHARED:
            return result
        detail = f"{result.detail}; {verdict.detail}" if result.detail else verdict.detail
        return replace(result, state=VOICE_STATE_SHARED_ENDPOINT, detail=detail)

    def _voice_endpoint_verdict(
        self,
        health_payload: Mapping[str, object] | None,
    ) -> ProbeResult:
        """Compare the sidecar's resolved voice endpoint against AC's declared endpoint.

        Always ``ok=True`` — every outcome, including a detected collision, is advisory
        (issue #672: the check must never block ``start_sidecar``, because today's rig runs
        deliberately pinned to the shared endpoint). The four states separate "no collision"
        from the two distinct flavours of "cannot tell", so an inert check never reads as a
        clean bill of health.
        """
        ac_device = self.config.ac_audio_device
        if not ac_device:
            return ProbeResult(
                "voice_endpoint",
                True,
                _ENDPOINT_STATE_UNDECLARED,
                "set AC_COPILOT_AC_AUDIO_DEVICE (or settings ac_audio_device) to AC's output "
                "endpoint to check the own-headset invariant",
            )
        voice_device = _health_voice_device(health_payload)
        if not voice_device:
            return ProbeResult(
                "voice_endpoint",
                True,
                _ENDPOINT_STATE_UNKNOWN,
                f"AC endpoint declared ({ac_device}) but the sidecar reports no active voice "
                "output device",
            )
        if endpoints_collide(voice_device, ac_device):
            return ProbeResult(
                "voice_endpoint",
                True,
                _ENDPOINT_STATE_SHARED,
                _shared_endpoint_remediation(voice_device),
            )
        return ProbeResult(
            "voice_endpoint",
            True,
            _ENDPOINT_STATE_DISTINCT,
            f"voice on {voice_device}; AC on {ac_device}",
        )

    def _voice_requested(self) -> bool:
        return bool(
            self.config.reference_archive or self.config.voice_bank or self.config.voice_tts
        )

    def _voice_playback_requested(self) -> bool:
        return bool(self.config.voice_bank or self.config.voice_tts)

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
                **_subprocess_kwargs(
                    env=self.simhub_environment(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - visible status beats hidden failure
            return ProbeResult("simhub", False, "start_failed", str(exc))
        return ProbeResult("simhub", True, "started", str(exe))

    def set_start_simhub(self, enabled: bool) -> bool:
        """Persist the SimHub auto-start preference and apply it to the live config.

        Backs the launcher's SimHub auto-start toggle. Persists to the per-user
        settings.json so the choice survives restarts, and updates the in-memory
        config so the next :meth:`poll_status` honors it immediately (starting or
        adopting SimHub when enabled). Returns the applied value. Persistence is
        best-effort: a settings-write failure still applies the runtime change so
        the UI toggle stays responsive.
        """
        from tools.rig_launcher.settings import update_settings

        self.config = replace(self.config, start_simhub=bool(enabled))
        try:
            update_settings(self.paths, start_simhub=bool(enabled))
        except (OSError, ValueError) as exc:
            # Best-effort persistence: the runtime change already applied, so keep the UI
            # responsive — but surface the failure (not silently) so a console/dev run
            # shows why the preference won't survive a restart. A malformed existing
            # settings.json (ValueError) is deliberately preserved, not overwritten.
            print(
                f"WARNING: could not persist start_simhub to settings.json: {exc}",
                file=sys.stderr,
            )
        return self.config.start_simhub

    def close(self) -> None:
        with self._proc_lock:
            self.stop_sidecar()
            self._close_log_handles()
            # The resilient child owns the machine-wide rig lock and the live AC session.
            # Closing Game Point must not kill that operator session; only release our log handle.
            if self._resilient_log_handle is not None:
                try:
                    self._resilient_log_handle.close()
                except OSError:
                    pass
                self._resilient_log_handle = None

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
        # Read the handle under the lock so a concurrent start/stop on the Tk thread can't
        # swap it out between the None-check and the .poll()/.pid reads (#568 review).
        with self._proc_lock:
            proc = self._sidecar_process
            if proc is None:
                return ProbeResult("sidecar", False, "stopped")
            code = proc.poll()
            if code is None:
                return ProbeResult("sidecar", True, "running", f"pid={proc.pid}")
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
                **_subprocess_kwargs(capture_output=True, text=True, timeout=5),
            )
        except Exception:  # noqa: BLE001 - inability to query means "not known running"
            return False
        return proc.returncode == 0 and "SimHubWPF.exe" in proc.stdout


def default_paths(env: Mapping[str, str] | None = None) -> LauncherPaths:
    env_map = _env_view(env)
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
    build_info: BuildInfo | None = None,
    hook_dir: Path | None = None,
) -> list[str]:
    """PyInstaller argv for the Game Point EXE.

    Bakes the build identity in via a generated ``--runtime-hook`` (issue #569) so the
    frozen sidecar reports a real ``build_commit`` / ``build_time`` on ``/health`` instead
    of ``"unknown"``. Doing it here rather than in the callers keeps the two entrypoints
    (``build.py`` and ``app.main --build-exe``) from drifting. ``build_info`` / ``hook_dir``
    are injected by tests so this stays free of git and of the real ``build/`` tree.
    """
    entry = project_root / "tools" / "rig_launcher" / "__main__.py"
    info = resolve_build_info(project_root) if build_info is None else build_info
    # Default under project_root/build/ — already gitignored, and NOT inside the directory
    # `--clean` wipes, despite `build/` also being the --workpath we pass. PyInstaller appends
    # the spec name to workpath (`build_main.build`: `workpath = os.path.join(workpath,
    # CONF['specnm'])`) BEFORE the `--clean` pass deletes it, so `--clean` empties
    # `build/AC-Copilot-Game-Point/`, not `build/`. The hook is a sibling of that dir and
    # survives — verified against a real frozen EXE reporting its baked commit on /health.
    # (Were this ever to change, Analysis would fail loudly on a missing runtime hook rather
    # than silently ship an unbaked EXE.)
    runtime_hook = write_runtime_hook(hook_dir or (project_root / "build"), info)
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
        # Issue #463: the sidecar imports pyserial lazily (serial_transport.open_serial),
        # so PyInstaller's static analysis misses it — the frozen --serial-port sidecar
        # would ModuleNotFoundError without these. serial.tools.list_ports + the win32
        # backend are pulled transitively by `serial`, but name them for robustness.
        "--hidden-import",
        "serial",
        "--hidden-import",
        "serial.tools.list_ports",
        # The packaged launcher dispatches this operator-facing AC workflow through a child
        # mode. Its rig imports are deliberately lazy so pure logic tests run off-Windows,
        # therefore name the complete frozen child surface explicitly.
        "--hidden-import",
        "tools.ac_harness.resilient_launch",
        "--hidden-import",
        "tools.ac_harness.entry_launcher",
        "--hidden-import",
        "tools.ac_harness.custom_ai",
        "--hidden-import",
        "tools.ac_harness.preset_utils",
        "--hidden-import",
        "tools.ac_harness.rig_lock",
        "--hidden-import",
        "tools.ac_harness.shared_memory",
        "--hidden-import",
        "tools.ac_harness.window_utils",
        "--runtime-hook",
        str(runtime_hook),
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
        parts = [f"backend={backend}"] if backend else []
        device = str(voice.get("device_name") or "").strip()
        host_api = str(voice.get("host_api") or "").strip()
        bank_channels = voice.get("bank_channels")
        max_channels = voice.get("max_output_channels")
        stream_channels = voice.get("stream_channels")
        channel_map = voice.get("channel_map")
        if device:
            device_part = f"device={device}"
            if host_api:
                device_part += f" ({host_api})"
            parts.append(device_part)
        if bank_channels is not None and stream_channels is not None:
            layout = f"layout={bank_channels}ch bank -> {stream_channels}ch stream"
            if max_channels is not None:
                layout += f"/{max_channels}ch max"
            if isinstance(channel_map, list) and channel_map:
                layout += f" map={channel_map}"
            parts.append(layout)
        detail = "; ".join(parts)
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


def _configured_source(env_value: str | None, settings_value: str | None) -> str:
    """Report which layer decided a :func:`_configured_text` value (issue #672 Part B).

    Mirrors ``_configured_text``'s precedence exactly, including the case that motivated
    the issue: an env var that is **present but blank** wins and clears a settings-supplied
    value, so the source is ``env`` even though the resolved value is ``None``.
    """
    if env_value is not None:
        return VOICE_BANK_SOURCE_ENV
    if _none_if_blank(settings_value) is not None:
        return VOICE_BANK_SOURCE_SETTINGS
    return VOICE_BANK_SOURCE_UNSET


def _health_voice_device(health_payload: Mapping[str, object] | None) -> str:
    """Read the sidecar's *live* voice output device from ``/health``.

    Reuses the health-reported device (``tools/ai_sidecar/voice/playback.OutputLayout``)
    rather than re-enumerating PortAudio in the launcher: the launcher process must not
    open the audio subsystem it exists to keep uncontended. Returns ``""`` unless voice is
    actually ``enabled`` — a device name from a non-running stream is not evidence that
    anything is holding the endpoint.
    """
    if health_payload is None:
        return ""
    voice = health_payload.get("voice")
    if not isinstance(voice, Mapping) or not voice.get("enabled"):
        return ""
    return str(voice.get("device_name") or "").strip()


def _normalize_endpoint_name(name: str | None) -> str:
    """Casefold and drop **all** whitespace so two spellings of one endpoint compare equal.

    Whitespace is removed outright rather than collapsed, because PortAudio reports the same
    Windows endpoint differently per host API. Measured on the rig for one physical device:

    * MME             ``'5.1 Speakers (USB Sound Device '``          (truncated to 31 chars)
    * DirectSound     ``'5.1 Speakers (USB Sound Device        )'``  (internal padding)
    * WASAPI          ``'5.1 Speakers (USB Sound Device        )'``

    An operator naturally declares the name Windows shows them — ``5.1 Speakers (USB Sound
    Device)`` — which under whitespace-collapsing would *not* match the padded WASAPI form,
    producing a false all-clear. That is strictly worse than crying wolf, so the padding is
    discarded rather than normalized to one space.
    """
    if not name:
        return ""
    return "".join(str(name).split()).casefold()


def endpoints_collide(voice_device: str | None, ac_device: str | None) -> bool:
    """Return True when two device names denote the same Windows output endpoint.

    Two ways to match, and only two:

    1. **Equality** after :func:`_normalize_endpoint_name` — always valid evidence.
    2. **Prefix**, but only when the shorter side is plausibly an *MME truncation artifact*:
       its **raw** length must reach :data:`_MME_NAME_MAX_LEN`. Measured raw and un-stripped,
       because truncation is a property of the original string — the rig's MME name
       ``'5.1 Speakers (USB Sound Device '`` is exactly 31 characters *including* the trailing
       space that stripping would remove.

    Deliberately **not** a bare substring test, and deliberately not a short prefix floor:
    a generic ``Speakers`` must not manufacture a collision with ``Speakers (USB Sound
    Device)``, because a check that cries wolf trains the operator to ignore it (the #575
    lesson, and PR #707 review).
    """
    left_raw = voice_device or ""
    right_raw = ac_device or ""
    left = _normalize_endpoint_name(left_raw)
    right = _normalize_endpoint_name(right_raw)
    # Both sides are already casefolded and whitespace-free here.
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) <= len(right):
        shorter, longer, shorter_raw = left, right, left_raw
    else:
        shorter, longer, shorter_raw = right, left, right_raw
    return len(str(shorter_raw)) >= _MME_NAME_MAX_LEN and longer.startswith(shorter)


def _shared_endpoint_remediation(device: str) -> str:
    """Operator-facing fix text, mirroring ``playback.OutputLayoutError``'s phrasing."""
    return (
        f"voice shares Assetto Corsa's audio endpoint ({device}) — FMOD/WASAPI contention "
        "risk; point AC_COPILOT_VOICE_DEVICE (and AC_COPILOT_VOICE_HOST_API) at the "
        "dedicated headset endpoint"
    )


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


def render_status_lines(status: GamePointStatus) -> list[str]:
    summary = ProbeResult("overall", status.ok, "ok" if status.ok else "needs_attention")
    rows = [
        summary,
        status.sidecar,
        status.screen,
        status.voice,
        status.simhub,
        status.tablet,
        status.resilient,
        *status.checks,
    ]
    return [f"{row.name}: {row.state}{(' - ' + row.detail) if row.detail else ''}" for row in rows]


def command_without_secrets(command: Iterable[str]) -> str:
    """Render a command for logs/status. Tokens are env-only, so this is safe."""
    return " ".join(str(part) for part in command)
