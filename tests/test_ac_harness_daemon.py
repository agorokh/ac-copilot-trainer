"""Tests for EPIC #154 Part F harness daemon (#228)."""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import ThreadingHTTPServer

import pytest

from tools.ac_harness.daemon import (
    HarnessDaemon,
    HarnessDaemonConfig,
    _extract_bearer_token,
    _token_ok,
    read_status_oracle,
    start_sidecar_process,
    stop_processes,
)
from tools.ac_harness.entry_launcher import (
    EntryLaunchResult,
    EntryOutcome,
    EntryPhase,
)


@dataclass
class FakePopen:
    pid: int = 4242
    returncode: int | None = None
    terminated: bool = False
    killed: bool = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1


def test_extract_bearer_token() -> None:
    assert _extract_bearer_token("Bearer secret") == "secret"
    assert _extract_bearer_token("Basic x") is None
    assert _extract_bearer_token(None) is None


def test_token_ok_uses_compare_digest() -> None:
    assert _token_ok("abc", "abc") is True
    assert _token_ok("abc", "abd") is False
    assert _token_ok(None, "abc") is False


def test_read_status_oracle_empty_when_unavailable(monkeypatch) -> None:
    from tools.ac_harness import daemon as daemon_mod

    def _boom():
        raise daemon_mod.SharedMemoryUnavailable("no ac")

    monkeypatch.setattr(daemon_mod, "SharedMemoryReader", _boom)
    assert read_status_oracle() == {}


def test_start_sidecar_process_invokes_module(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakePopen()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    proc = start_sidecar_process(
        repo_root=tmp_path,
        token="tok",
        host="0.0.0.0",
        port=8765,
        popen=fake_popen,
    )
    assert proc.pid == 4242
    assert "-m" in calls[0]
    assert "tools.ai_sidecar" in calls[0]
    assert "--token" in calls[0]
    assert calls[0][calls[0].index("--token") + 1] == "tok"


def test_stop_processes_terminates_sidecar_and_acs() -> None:
    proc = FakePopen()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    stop_processes(sidecar_proc=proc, runner=fake_run)
    assert proc.terminated is True
    assert calls == [["taskkill", "/F", "/IM", "acs.exe"]]


def test_harness_daemon_requires_token() -> None:
    with pytest.raises(ValueError, match="token"):
        HarnessDaemon(HarnessDaemonConfig(token=""))


def test_session_start_records_success() -> None:
    result = EntryLaunchResult(
        EntryOutcome.DRIVING,
        launches=1,
        polls=10,
        last_phase=EntryPhase.DRIVING,
    )
    daemon = HarnessDaemon(
        HarnessDaemonConfig(token="secret"),
        launcher_factory=lambda: type("L", (), {"run": staticmethod(lambda: result)})(),
    )
    got = daemon.start_session()
    assert got.ok
    assert daemon.state.session_started is True


def test_sidecar_start_rejects_without_session() -> None:
    daemon = HarnessDaemon(HarnessDaemonConfig(token="secret"))
    with pytest.raises(RuntimeError, match="session not started"):
        daemon.start_sidecar()


def test_sidecar_start_after_session() -> None:
    result = EntryLaunchResult(
        EntryOutcome.DRIVING,
        launches=1,
        polls=1,
        last_phase=EntryPhase.DRIVING,
    )
    fake = FakePopen()
    daemon = HarnessDaemon(
        HarnessDaemonConfig(token="secret"),
        launcher_factory=lambda: type("L", (), {"run": staticmethod(lambda: result)})(),
        sidecar_starter=lambda: fake,
    )
    daemon.start_session()
    proc = daemon.start_sidecar()
    assert proc is fake


def _request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
) -> tuple[int, dict]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


@pytest.fixture
def live_daemon():
    daemon = HarnessDaemon(
        HarnessDaemonConfig(bind_host="127.0.0.1", bind_port=0, token="rig-test-token"),
        launcher_factory=lambda: type(
            "L",
            (),
            {
                "run": staticmethod(
                    lambda: EntryLaunchResult(
                        EntryOutcome.DRIVING,
                        launches=1,
                        polls=1,
                        last_phase=EntryPhase.DRIVING,
                    )
                )
            },
        )(),
        sidecar_starter=lambda: FakePopen(pid=9999),
    )
    handler = daemon.build_handler()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, port, daemon
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_health_unauthenticated(live_daemon) -> None:
    host, port, _ = live_daemon
    status, body = _request(host, port, "GET", "/health")
    assert status == 200
    assert body["ok"] is True


def test_http_status_requires_token(live_daemon) -> None:
    host, port, _ = live_daemon
    status, body = _request(host, port, "GET", "/status")
    assert status == 401
    assert body["ok"] is False


def test_http_session_sidecar_flow(live_daemon) -> None:
    host, port, daemon = live_daemon
    token = "rig-test-token"

    status, body = _request(host, port, "POST", "/session/start", token=token)
    assert status == 200
    assert body["ok"] is True

    status, body = _request(host, port, "POST", "/sidecar/start", token=token)
    assert status == 200
    assert body["pid"] == 9999

    status, body = _request(host, port, "GET", "/status", token=token)
    assert status == 200
    assert body["session_started"] is True
    assert body["sidecar_running"] is True

    status, body = _request(host, port, "POST", "/session/stop", token=token)
    assert status == 200
    assert daemon.state.session_started is False


def test_http_sidecar_before_session_conflict(live_daemon) -> None:
    host, port, _ = live_daemon
    status, body = _request(host, port, "POST", "/sidecar/start", token="rig-test-token")
    assert status == 409
    assert "session not started" in body["error"]
