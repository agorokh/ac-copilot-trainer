"""In-session harness daemon — HTTP control channel for EPIC #154 Part F (#228).

Runs on the AC rig (Session-1 desktop) so a remote agent can start/stop AC sessions and
the sidecar without Tailscale SSH (unsupported on Windows). Composes :mod:`entry_launcher`
(detect-and-retry AC launch) and ``tools.ai_sidecar`` (WS tap) behind a small token-gated
HTTP API. Shared-memory snapshots from :mod:`shared_memory` are the on-track oracle for
``GET /status``.

Endpoints (all except ``GET /health`` require ``Authorization: Bearer <token>``):

* ``POST /session/start`` — launch AC via :class:`EntryLauncher`. ``launch_mode="cm"`` (default
  on Windows) drives the de-elevated Content Manager URL path so ``acs.exe`` starts non-elevated
  even when the daemon runs in an elevated shell; ``"acs"`` cold-launches ``acs.exe`` directly.
* ``POST /sidecar/start`` — spawn ``python -m tools.ai_sidecar --external-bind …`` (requires
  a successful session start first)
* ``GET /status`` — daemon + shared-memory oracle
* ``POST /session/stop`` — terminate sidecar and ``acs.exe``
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tools.ac_harness.entry_launcher import (
    LAUNCH_MODES,
    EntryLauncher,
    EntryLauncherConfig,
    EntryLaunchResult,
    EntryOutcome,
    make_actuator,
)
from tools.ac_harness.shared_memory import (
    DrivingEntryDetector,
    SharedMemoryReader,
    SharedMemoryUnavailable,
)

AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "


def _extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value or not header_value.startswith(BEARER_PREFIX):
        return None
    token = header_value[len(BEARER_PREFIX) :].strip()
    return token or None


def _token_ok(supplied: str | None, expected: str) -> bool:
    if supplied is None:
        return False
    if len(supplied) != len(expected):
        return False
    return secrets.compare_digest(supplied, expected)


@dataclass
class HarnessDaemonConfig:
    """Runtime configuration for :class:`HarnessDaemon`."""

    bind_host: str = "127.0.0.1"
    bind_port: int = 9876
    token: str = ""
    repo_root: Path = field(default_factory=lambda: Path.cwd())
    # Default to the de-elevated CM launch on the Windows rig (the only path that survives the
    # elevated-shell / non-elevated-Steam split); acs.exe-direct elsewhere. Kept consistent with
    # the CLI default so programmatic and CLI callers behave the same. ``cm`` mode requires a
    # ``cm_preset`` — ``make_actuator`` raises if it is missing.
    launch_mode: str = field(default_factory=lambda: "cm" if sys.platform == "win32" else "acs")
    acs_exe: Path | None = None
    race_ini: Path | None = None
    cm_exe: Path | None = None
    cm_preset: Path | None = None
    sidecar_host: str = "0.0.0.0"
    sidecar_port: int = 8765
    launcher_config: EntryLauncherConfig = field(default_factory=EntryLauncherConfig)


@dataclass
class HarnessDaemonState:
    """Mutable daemon state guarded by :attr:`lock`."""

    session_started: bool = False
    session_result: EntryLaunchResult | None = None
    sidecar_proc: subprocess.Popen[Any] | None = None
    launch_generation: int = 0
    launching: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def _default_acs_exe() -> Path:
    return Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\acs.exe")


def _default_race_ini() -> Path:
    return Path.home() / "OneDrive" / "Documents" / "Assetto Corsa" / "cfg" / "race.ini"


def read_status_oracle() -> dict[str, Any]:
    """One shared-memory poll for ``GET /status``; empty dict when AC is down."""
    try:
        reader = SharedMemoryReader()
    except SharedMemoryUnavailable:
        return {}
    try:
        graphics = reader.read_graphics()
        physics = reader.read_physics()
        detector = DrivingEntryDetector(required_live_reads=1)
        now = time.monotonic()
        detector.observe(graphics, physics, now=now)
        graphics = reader.read_graphics()
        physics = reader.read_physics()
        detector.observe(graphics, physics, now=time.monotonic())
        return {
            "graphics_status": graphics.status.name,
            "is_in_pit": graphics.is_in_pit,
            "graphics_packet_id": graphics.packet_id,
            "physics_packet_id": physics.packet_id if physics else None,
            "driving": detector.driving,
        }
    except SharedMemoryUnavailable:
        return {}
    finally:
        reader.close()


def start_sidecar_process(
    *,
    repo_root: Path,
    token: str,
    host: str,
    port: int,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> subprocess.Popen[Any]:
    """Launch the AI sidecar as a background subprocess."""
    return popen(
        [
            sys.executable,
            "-m",
            "tools.ai_sidecar",
            "--external-bind",
            host,
            "--port",
            str(port),
            "--token",
            token,
        ],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_processes(
    *,
    sidecar_proc: subprocess.Popen[Any] | None,
    process_name: str = "acs.exe",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Best-effort terminate sidecar and AC."""
    if sidecar_proc is not None and sidecar_proc.poll() is None:
        sidecar_proc.terminate()
        try:
            sidecar_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sidecar_proc.kill()
    if sys.platform == "win32":
        runner(
            ["taskkill", "/IM", process_name, "/F", "/T"],
            check=False,
            capture_output=True,
        )


class HarnessDaemon:
    """Token-gated HTTP control plane for the autonomous self-test harness."""

    def __init__(
        self,
        config: HarnessDaemonConfig,
        *,
        launcher_factory: Callable[[], EntryLauncher] | None = None,
        sidecar_starter: Callable[[], subprocess.Popen[Any]] | None = None,
    ) -> None:
        if not config.token:
            raise ValueError("HarnessDaemon requires a non-empty token")
        self.config = config
        self.state = HarnessDaemonState()
        acs = config.acs_exe or _default_acs_exe()
        race_ini = config.race_ini or _default_race_ini()

        def _default_launcher_factory() -> EntryLauncher:
            actuator = make_actuator(
                config.launch_mode,
                acs_exe=acs,
                race_ini=race_ini,
                cm_exe=config.cm_exe,
                cm_preset=config.cm_preset,
            )
            return EntryLauncher(actuator, config=config.launcher_config)

        def _default_sidecar_starter() -> subprocess.Popen[Any]:
            return start_sidecar_process(
                repo_root=config.repo_root,
                token=config.token,
                host=config.sidecar_host,
                port=config.sidecar_port,
            )

        self._launcher_factory = launcher_factory or _default_launcher_factory
        self._sidecar_starter = sidecar_starter or _default_sidecar_starter
        self._start_lock = threading.Lock()

    def start_session(self) -> EntryLaunchResult:
        """Run the entry launcher and record session state."""
        if not self._start_lock.acquire(blocking=False):
            return EntryLaunchResult(
                EntryOutcome.FAILED,
                launches=0,
                polls=0,
                last_phase=None,
                reason="session start already in progress",
            )
        try:
            with self.state.lock:
                stop_processes(sidecar_proc=self.state.sidecar_proc)
                self.state.sidecar_proc = None
                self.state.launch_generation += 1
                generation = self.state.launch_generation
                self.state.launching = True
                self.state.session_started = False
                self.state.session_result = None
            try:
                result = self._launcher_factory().run()
            finally:
                with self.state.lock:
                    self.state.launching = False
            with self.state.lock:
                if self.state.launch_generation != generation:
                    return EntryLaunchResult(
                        EntryOutcome.FAILED,
                        launches=result.launches,
                        polls=result.polls,
                        last_phase=result.last_phase,
                        reason="session start cancelled",
                    )
                self.state.session_result = result
                self.state.session_started = result.ok
            return result
        finally:
            self._start_lock.release()

    def start_sidecar(self) -> subprocess.Popen[Any]:
        """Spawn the sidecar; requires a successful prior session start."""
        with self.state.lock:
            if self.state.launching:
                raise RuntimeError("session start in progress")
            if not self.state.session_started:
                raise RuntimeError("session not started — call POST /session/start first")
            if self.state.sidecar_proc is not None and self.state.sidecar_proc.poll() is None:
                return self.state.sidecar_proc
            proc = self._sidecar_starter()
            self.state.sidecar_proc = proc
            return proc

    def stop_session(self) -> None:
        """Terminate sidecar and AC; clear session flags."""
        with self.state.lock:
            self.state.launch_generation += 1
            self.state.launching = False
            stop_processes(sidecar_proc=self.state.sidecar_proc)
            self.state.sidecar_proc = None
            self.state.session_started = False
            self.state.session_result = None

    def status_payload(self) -> dict[str, Any]:
        """JSON-serializable status for ``GET /status``."""
        with self.state.lock:
            sidecar_running = (
                self.state.sidecar_proc is not None and self.state.sidecar_proc.poll() is None
            )
            session = None
            if self.state.session_result is not None:
                session = {
                    "outcome": self.state.session_result.outcome.value,
                    "ok": self.state.session_result.ok,
                    "reason": self.state.session_result.reason,
                }
            return {
                "session_started": self.state.session_started,
                "session_launching": self.state.launching,
                "sidecar_running": sidecar_running,
                "session": session,
                "oracle": read_status_oracle(),
            }

    def build_handler(self) -> type[BaseHTTPRequestHandler]:
        daemon = self
        token = self.config.token

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - quiet
                return

            def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                supplied = _extract_bearer_token(self.headers.get(AUTH_HEADER))
                return _token_ok(supplied, token)

            def _require_auth(self) -> bool:
                if self._authorized():
                    return True
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return False

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in ("/health", "/healthz"):
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return
                if path == "/status":
                    if not self._require_auth():
                        return
                    self._send_json(HTTPStatus.OK, {"ok": True, **daemon.status_payload()})
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                if not self._require_auth():
                    return
                path = self.path.split("?", 1)[0]
                if path == "/session/start":
                    result = daemon.start_session()
                    code = HTTPStatus.OK if result.ok else HTTPStatus.CONFLICT
                    self._send_json(
                        code,
                        {
                            "ok": result.ok,
                            "outcome": result.outcome.value,
                            "reason": result.reason,
                        },
                    )
                    return
                if path == "/sidecar/start":
                    try:
                        proc = daemon.start_sidecar()
                    except RuntimeError as exc:
                        self._send_json(
                            HTTPStatus.CONFLICT,
                            {"ok": False, "error": str(exc)},
                        )
                        return
                    self._send_json(
                        HTTPStatus.OK,
                        {"ok": True, "pid": proc.pid},
                    )
                    return
                if path == "/session/stop":
                    daemon.stop_session()
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

        return _Handler

    def serve_forever(self) -> None:
        """Block until interrupted."""
        handler = self.build_handler()
        server = ThreadingHTTPServer((self.config.bind_host, self.config.bind_port), handler)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            with self.state.lock:
                managed = (
                    self.state.session_started
                    or self.state.launching
                    or (
                        self.state.sidecar_proc is not None
                        and self.state.sidecar_proc.poll() is None
                    )
                )
            if managed:
                self.stop_session()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AC Copilot Trainer harness daemon (EPIC #154 Part F)"
    )
    parser.add_argument("--bind", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=9876, help="HTTP bind port")
    parser.add_argument("--token", required=True, help="Bearer token for API auth")
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="Repo root (sidecar cwd)"
    )
    parser.add_argument(
        "--launch-mode",
        choices=LAUNCH_MODES,
        default="cm" if sys.platform == "win32" else "acs",
        help=(
            "cm = de-elevated Content Manager URL launch (default on Windows; survives the "
            "elevated-shell/non-elevated-Steam split); acs = direct acs.exe launch"
        ),
    )
    parser.add_argument("--acs-exe", type=Path, help="Path to acs.exe (--launch-mode acs)")
    parser.add_argument("--race-ini", type=Path, help="Path to race.ini (--launch-mode acs)")
    parser.add_argument("--cm-exe", type=Path, help="Path to Content Manager.exe (cm mode)")
    parser.add_argument("--cm-preset", type=Path, help="Path to a Quick Drive .cmpreset (cm mode)")
    parser.add_argument("--sidecar-bind", default="0.0.0.0", help="Sidecar external bind host")
    parser.add_argument("--sidecar-port", type=int, default=8765, help="Sidecar port")
    return parser


def _main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.launch_mode == "cm" and args.cm_preset is None:
        parser.error("--launch-mode cm requires --cm-preset (path to a Quick Drive .cmpreset)")
    config = HarnessDaemonConfig(
        bind_host=args.bind,
        bind_port=args.port,
        token=args.token,
        repo_root=args.repo_root.resolve(),
        launch_mode=args.launch_mode,
        acs_exe=args.acs_exe,
        race_ini=args.race_ini,
        cm_exe=args.cm_exe,
        cm_preset=args.cm_preset,
        sidecar_host=args.sidecar_bind,
        sidecar_port=args.sidecar_port,
    )
    HarnessDaemon(config).serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    raise SystemExit(_main())
