"""Tests for the EPIC #154 Part G autonomous self-test runner (#235)."""

from __future__ import annotations

import asyncio

import pytest

from tools.ac_harness import self_test
from tools.ac_harness.self_test import (
    SelfTestConfig,
    SelfTestReport,
    _main,
    run_self_test,
)

PASS_FRAMES = [
    {"type": "state.snapshot", "topic": t}
    for t in ("connection", "tire_temps", "coaching.snapshot")
]
FAIL_FRAMES = [{"type": "state.snapshot", "topic": "connection"}]  # missing two continuous topics


class FakeHttp:
    """Records (method, url) calls; returns a canned response by URL substring."""

    def __init__(self, responses: dict[str, tuple[int, dict]]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, *, token, timeout=30.0):
        self.calls.append((method, url))
        for key, resp in self.responses.items():
            if key in url:
                return resp
        return (404, {"ok": False, "error": "not found"})

    def hit(self, fragment: str) -> bool:
        return any(fragment in url for _, url in self.calls)


def _tap(frames=None, exc=None):
    async def _inner(url, *, seconds=20.0, wait_for_lap=False):
        if exc is not None:
            raise exc
        return list(frames or [])

    return _inner


def _cfg(**kw) -> SelfTestConfig:
    return SelfTestConfig(token="t", **kw)


def _ok_session():
    return {
        "/session/start": (200, {"ok": True, "outcome": "driving", "reason": "sustained"}),
        "/sidecar/start": (200, {"ok": True, "pid": 1}),
        "/session/stop": (200, {"ok": True}),
    }


def test_self_test_pass():
    http = FakeHttp(_ok_session())
    report = asyncio.run(run_self_test(_cfg(), http=http, tap=_tap(PASS_FRAMES)))
    assert report.ok is True
    assert report.stage == "pipeline"
    assert report.sequence_ok is True
    assert report.session_outcome == "driving"
    assert report.counts.get("coaching.snapshot") == 1
    assert http.hit("/session/stop")


def test_self_test_pipeline_fail():
    http = FakeHttp(_ok_session())
    report = asyncio.run(run_self_test(_cfg(), http=http, tap=_tap(FAIL_FRAMES)))
    assert report.ok is False
    assert report.stage == "pipeline"
    assert report.sequence_ok is False
    assert http.hit("/session/stop")


def test_self_test_session_start_fails_skips_sidecar():
    http = FakeHttp(
        {"/session/start": (409, {"ok": False, "outcome": "failed", "reason": "no drive"})}
    )
    report = asyncio.run(run_self_test(_cfg(), http=http, tap=_tap(PASS_FRAMES)))
    assert report.ok is False
    assert report.stage == "session_start"
    assert report.session_reason == "no drive"
    assert not http.hit("/sidecar/start")


def test_self_test_sidecar_fail_stops_session():
    resp = _ok_session()
    resp["/sidecar/start"] = (409, {"ok": False, "error": "no loopback Lua peer"})
    http = FakeHttp(resp)
    report = asyncio.run(run_self_test(_cfg(), http=http, tap=_tap(PASS_FRAMES)))
    assert report.ok is False
    assert report.stage == "sidecar_start"
    assert report.error == "no loopback Lua peer"
    assert http.hit("/session/stop")


def test_self_test_tap_raises_stops_session():
    http = FakeHttp(_ok_session())
    report = asyncio.run(
        run_self_test(_cfg(), http=http, tap=_tap(exc=RuntimeError("hello handshake timed out")))
    )
    assert report.ok is False
    assert report.stage == "pipeline_tap"
    assert "hello handshake timed out" in (report.error or "")
    assert http.hit("/session/stop")


def test_self_test_keep_skips_stop():
    http = FakeHttp(_ok_session())
    report = asyncio.run(run_self_test(_cfg(keep=True), http=http, tap=_tap(PASS_FRAMES)))
    assert report.ok is True
    assert not http.hit("/session/stop")


def test_report_summary_renders_pass_and_fail():
    ok = SelfTestReport(ok=True, stage="pipeline", session_outcome="driving", sequence_ok=True)
    assert "PASS" in ok.summary()
    bad = SelfTestReport(ok=False, stage="session_start", error="no drive")
    assert "FAIL" in bad.summary()
    assert "no drive" in bad.summary()


def test_main_requires_token():
    with pytest.raises(SystemExit):
        _main([])


@pytest.mark.parametrize(("ok", "code"), [(True, 0), (False, 1)])
def test_main_exit_code(monkeypatch, ok: bool, code: int):
    async def fake_run(config, **kwargs):
        return SelfTestReport(ok=ok, stage="pipeline", sequence_ok=ok)

    monkeypatch.setattr(self_test, "run_self_test", fake_run)
    assert _main(["--token", "t"]) == code
