"""L1 sidecar WS-tap harness client tests (issue #154 Part C).

Drives a real in-process ``ai_sidecar`` over a loopback WebSocket with the headless
``HarnessClient`` and asserts the deterministic coaching surface — the agent's no-human
self-test of the sidecar contract. Plain ``asyncio.run`` (repo has no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.server import serve as ws_serve  # noqa: E402

from tools.ai_sidecar.harness_client import (  # noqa: E402
    BASELINE_LAP_FRAMES,
    HarnessClient,
    evaluate_baseline_rubric,
    main,
    run_inject,
)
from tools.ai_sidecar.protocol import prepare_outbound_message  # noqa: E402
from tools.ai_sidecar.server import _external_peers, _handler, make_token_check  # noqa: E402
from tools.ai_sidecar.session import LapComparisonState  # noqa: E402

_GOLDEN = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "golden"
    / "coaching_response_ref_then_slower.json"
)


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@asynccontextmanager
async def _running_sidecar(token: str | None = None) -> AsyncIterator[int]:
    port = _free_port()
    process_request = make_token_check(token)
    _external_peers.clear()
    try:
        async with ws_serve(
            lambda ws: _handler(ws, reply_coaching=True),
            "127.0.0.1",
            port,
            process_request=process_request,
        ):
            yield port
    finally:
        _external_peers.clear()


def _ws_url(port: int) -> str:
    return f"ws://127.0.0.1:{port}/"


def test_hello_handshake() -> None:
    async def _run() -> dict[str, Any] | None:
        async with _running_sidecar() as port:
            async with HarnessClient(_ws_url(port)) as hc:
                return await hc.hello(timeout=2.0)

    ack = asyncio.run(_run())
    assert ack is not None
    assert ack["type"] == "hello_ack"
    assert "config.set" in ack["capabilities"]


def test_baseline_scenario_matches_golden(disable_ollama: None) -> None:
    """The slower lap's coaching_response on the wire must equal the committed golden
    AND the in-process deterministic generator — wire == golden == pure function."""

    async def _run() -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []
        async with _running_sidecar() as port:
            async with HarnessClient(_ws_url(port)) as hc:
                assert await hc.hello(timeout=2.0) is not None
                for frame in BASELINE_LAP_FRAMES:
                    await hc.send(frame)
                    resp = await hc.expect_coaching_response(lap=frame["lap"], timeout=3.0)
                    assert resp is not None, f"no coaching_response for lap {frame['lap']}"
                    captured.append(resp)
        return captured

    captured = asyncio.run(_run())
    assert len(captured) == 2
    first, second = captured

    # Reference lap: ack only, no ranking yet.
    assert "improvementRanking" not in first

    # Cross-check the in-process deterministic generator (ref primes state, then slower).
    state = LapComparisonState()
    prepare_outbound_message(BASELINE_LAP_FRAMES[0], reply_coaching=True, lap_state=state)
    expected = prepare_outbound_message(
        BASELINE_LAP_FRAMES[1], reply_coaching=True, lap_state=state
    )

    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert expected == golden, "committed golden drifted from prepare_outbound_message"
    assert second == golden, "wire coaching_response drifted from golden"

    # Spot-check the ordering contract: biggest-regret corner first.
    ranking = second["improvementRanking"]
    assert ranking[0]["corner"] == 1
    assert ranking[0]["metric"] == "min_speed_kmh"
    assert [r["priority"] for r in ranking] == sorted(
        (r["priority"] for r in ranking), reverse=True
    )


def test_run_inject_baseline_passes(disable_ollama: None) -> None:
    async def _run() -> tuple[int, dict[str, Any]]:
        async with _running_sidecar() as port:
            return await run_inject(_ws_url(port), scenario="baseline", timeout=3.0)

    code, detail = asyncio.run(_run())
    assert code == 0, detail
    assert detail["responses"] == 2
    assert detail["ranking_len"] >= 1


def test_run_inject_unknown_scenario_returns_2() -> None:
    code, detail = asyncio.run(run_inject("ws://127.0.0.1:1/", scenario="nope"))
    assert code == 2
    assert "unknown scenario" in detail["reason"]


def test_run_inject_connect_failure_returns_1() -> None:
    """A still-dead sidecar exhausts the retry budget and reports a clean failure (Cursor)."""
    code, detail = asyncio.run(
        run_inject("ws://127.0.0.1:1/", connect_retries=2, connect_retry_delay=0.01)
    )
    assert code == 1
    assert "could not connect" in detail["reason"]


def test_main_baseline_exit_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _fake_inject(*_a: Any, **_k: Any) -> tuple[int, dict[str, Any]]:
        return 0, {"responses": 2, "ranking_len": 4}

    monkeypatch.setattr("tools.ai_sidecar.harness_client.run_inject", _fake_inject)
    rc = main(["--url", "ws://127.0.0.1:9/", "--inject", "baseline"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True


def test_evaluate_baseline_rubric_pass() -> None:
    responses = [
        {"event": "coaching_response", "lap": 1, "hints": []},
        {
            "event": "coaching_response",
            "lap": 2,
            "improvementRanking": [
                {"corner": 1, "metric": "min_speed_kmh", "priority": 0.12},
                {"corner": 2, "metric": "apex_speed_kmh", "priority": 0.03},
            ],
        },
    ]
    ok, detail = evaluate_baseline_rubric(responses)
    assert ok, detail
    assert detail["top"]["corner"] == 1


def test_evaluate_baseline_rubric_failures() -> None:
    # Too few responses.
    ok, _ = evaluate_baseline_rubric([{"event": "coaching_response", "lap": 1}])
    assert not ok
    # Missing lap 2.
    ok, _ = evaluate_baseline_rubric(
        [{"lap": 1}, {"lap": 1, "improvementRanking": [{"priority": 1}]}]
    )
    assert not ok
    # Reference lap wrongly carries a ranking.
    ok, _ = evaluate_baseline_rubric(
        [
            {"lap": 1, "improvementRanking": [{"priority": 1}]},
            {"lap": 2, "improvementRanking": [{"priority": 1}]},
        ]
    )
    assert not ok
    # Slower lap has empty ranking.
    ok, _ = evaluate_baseline_rubric([{"lap": 1}, {"lap": 2, "improvementRanking": []}])
    assert not ok
    # Ranking not ordered by descending priority.
    ok, _ = evaluate_baseline_rubric(
        [{"lap": 1}, {"lap": 2, "improvementRanking": [{"priority": 0.1}, {"priority": 0.9}]}]
    )
    assert not ok
    # Non-empty + sorted but the WRONG corner/metric ranked first must fail (Codex): a
    # single {corner: 99} item would otherwise pass and hide a ranking regression.
    ok, _ = evaluate_baseline_rubric(
        [
            {"lap": 1},
            {
                "lap": 2,
                "improvementRanking": [{"corner": 99, "metric": "min_speed_kmh", "priority": 0.9}],
            },
        ]
    )
    assert not ok


def test_wait_for_preserves_out_of_order_frames() -> None:
    """A frame that arrives before the one we're waiting for is buffered, not discarded."""

    async def _run() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        hc = HarnessClient("ws://127.0.0.1:1/")
        await hc._queue.put({"event": "B", "n": 1})  # arrives first
        await hc._queue.put({"event": "A", "n": 2})  # arrives second
        # Ask for A first: B must be buffered so the later wait still finds it.
        a = await hc.wait_for(lambda f: f.get("event") == "A", timeout=1.0)
        b = await hc.wait_for(lambda f: f.get("event") == "B", timeout=1.0)
        return a, b

    a, b = asyncio.run(_run())
    assert a is not None and a["n"] == 2
    assert b is not None and b["n"] == 1


def test_harness_send_without_connect_raises() -> None:
    async def _run() -> None:
        hc = HarnessClient("ws://127.0.0.1:1/")
        with pytest.raises(RuntimeError, match="not connected"):
            await hc.send({"v": 1, "type": "hello", "client": "x"})

    asyncio.run(_run())


def test_connect_retries_then_raises_on_dead_port() -> None:
    async def _run() -> None:
        hc = HarnessClient("ws://127.0.0.1:1/")
        with pytest.raises(OSError):
            await hc.connect(retries=2, retry_delay=0.01)

    asyncio.run(_run())
