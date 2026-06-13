"""Headless WebSocket harness client for agent-driven trainer tests (issue #154 Part C).

This is the **Layer-1 (L1) tap** of the autonomous self-test harness: a headless v1
WebSocket peer that drives a running ``ai_sidecar`` the same way the in-game Lua app
does — injecting ``lap_complete`` / ``corner_query`` frames and capturing the sidecar's
``coaching_response`` / ``corner_advice`` / ``state.snapshot`` replies — so a test (or a
CLI rubric) can assert on them with **no Assetto Corsa, no Windows box, and no human**.

The sidecar's legacy coaching flow (``{"protocol":1,"event":"lap_complete"}`` ->
``coaching_response``) is per-connection and needs no second peer, so this client drives
and asserts the deterministic rules-engine surface (hints + ``improvementRanking``) on a
developer machine. The v1 ``{"v":1,"type":...}`` envelope (hello / state.subscribe) is
also spoken for the observation surface.

CLI rubric (used by ``scripts/baseline_copilot_check.sh`` / ``make ci-drive``)::

    python -m tools.ai_sidecar.harness_client --url ws://127.0.0.1:8765 --inject baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from tools.ai_sidecar.external_protocol import (
    AUTH_HEADER,
    CLIENT_HEADER,
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_KEY,
)
from tools.ai_sidecar.protocol import (
    EVENT_COACHING_RESPONSE,
    EVENT_CORNER_ADVICE,
    PROTOCOL_VERSION,
)

logger = logging.getLogger(__name__)

# Default deterministic scenario: a fast reference lap followed by a slower lap on the
# same two corners. Mirrors tests/fixtures/lap_sidecar_{ref,last}.json so the sidecar
# emits a coaching_response with NO improvementRanking for the reference lap and an
# ordered improvementRanking for the slower lap. Inlined (not loaded from tests/) so the
# CLI works from an installed package without the test tree.
BASELINE_LAP_FRAMES: tuple[dict[str, Any], ...] = (
    {
        "protocol": PROTOCOL_VERSION,
        "event": "lap_complete",
        "lap": 1,
        "lapTimeMs": 90000,
        "telemetry": {
            "corners": [
                {"id": 1, "minSpeedKmh": 55, "apexSpeedKmh": 95},
                {"id": 2, "minSpeedKmh": 60, "apexSpeedKmh": 102},
            ]
        },
    },
    {
        "protocol": PROTOCOL_VERSION,
        "event": "lap_complete",
        "lap": 2,
        "lapTimeMs": 94000,
        "telemetry": {
            "corners": [
                {"id": 1, "minSpeedKmh": 48, "apexSpeedKmh": 88},
                {"id": 2, "minSpeedKmh": 58, "apexSpeedKmh": 99},
            ]
        },
    },
)


class HarnessClient:
    """A headless WS peer that injects frames and captures the sidecar's replies.

    Use as an async context manager::

        async with HarnessClient(url, token=tok) as hc:
            await hc.hello()
            await hc.send(frame)
            resp = await hc.expect_coaching_response(lap=2)
    """

    def __init__(
        self, url: str, *, token: str | None = None, client_id: str = "ac-harness"
    ) -> None:
        self.url = url
        self.client_id = client_id
        self._headers: dict[str, str] = {CLIENT_HEADER: client_id}
        if token:
            self._headers[AUTH_HEADER] = token
        self.frames: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._ws: Any = None
        self._recv_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> HarnessClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self, *, retries: int = 1, retry_delay: float = 0.25) -> None:
        """Open the socket and start the background receive loop.

        Pass ``retries > 1`` to tolerate a refused/unreachable socket (e.g. a sidecar still
        booting): the connect is re-attempted ``retries`` times, ``retry_delay`` seconds
        apart. The default (``retries=1``) is a single attempt, suited to tests that connect
        to an already-listening sidecar; ``run_inject`` — the CLI / ``ci-drive`` path that
        races a just-spawned sidecar — passes a generous budget so the script's fixed sleep
        is only a head start, not the correctness guard.
        """
        from websockets.asyncio.client import connect as ws_connect

        last_exc: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                self._ws = await ws_connect(self.url, additional_headers=self._headers)
            except OSError as exc:  # ConnectionRefused / DNS / unreachable
                last_exc = exc
                await asyncio.sleep(retry_delay)
                continue
            self._recv_task = asyncio.create_task(self._recv_loop())
            return
        assert last_exc is not None
        raise last_exc

    async def close(self) -> None:
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("harness: non-JSON frame ignored: %s", raw[:120])
                    continue
                if isinstance(data, dict):
                    self.frames.append(data)
                    await self._queue.put(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # connection closed / reset — end the loop quietly
            logger.info("harness recv loop ended: %s", exc)

    async def send(self, frame: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("harness client is not connected")
        await self._ws.send(json.dumps(frame, separators=(",", ":")))

    async def hello(self, *, timeout: float = 5.0) -> dict[str, Any] | None:
        """Send the v1 hello and wait for the sidecar's hello_ack."""
        await self.send(
            {ENVELOPE_KEY: ENVELOPE_VERSION, TYPE_KEY: TYPE_HELLO, "client": self.client_id}
        )
        return await self.wait_for(lambda f: f.get(TYPE_KEY) == TYPE_HELLO_ACK, timeout=timeout)

    async def subscribe(self, topics: list[str], *, timeout: float = 2.0) -> None:
        await self.send(
            {ENVELOPE_KEY: ENVELOPE_VERSION, TYPE_KEY: "state.subscribe", "topics": topics}
        )

    async def wait_for(
        self, predicate: Callable[[dict[str, Any]], bool], *, timeout: float = 5.0
    ) -> dict[str, Any] | None:
        """Return the next received frame matching ``predicate``, or ``None`` on timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except TimeoutError:
                return None
            if predicate(frame):
                return frame

    async def expect_coaching_response(
        self, *, lap: int | None = None, timeout: float = 5.0
    ) -> dict[str, Any] | None:
        def _pred(f: dict[str, Any]) -> bool:
            if f.get("event") != EVENT_COACHING_RESPONSE:
                return False
            return lap is None or f.get("lap") == lap

        return await self.wait_for(_pred, timeout=timeout)

    async def expect_corner_advice(
        self, *, corner: str, timeout: float = 5.0
    ) -> dict[str, Any] | None:
        return await self.wait_for(
            lambda f: f.get("event") == EVENT_CORNER_ADVICE and f.get("corner") == corner,
            timeout=timeout,
        )


def evaluate_baseline_rubric(
    responses: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    """Pure rubric for the baseline scenario — testable without a socket.

    PASS iff: two coaching_response frames were captured; the reference lap (lap 1) has
    NO improvementRanking; the slower lap (lap 2) has a non-empty improvementRanking that
    is ordered by descending priority and whose top item is the biggest-regret corner.
    """
    detail: dict[str, Any] = {"responses": len(responses)}
    if len(responses) < 2:
        detail["reason"] = "expected 2 coaching_response frames"
        return False, detail
    ref = next((r for r in responses if r.get("lap") == 1), None)
    slow = next((r for r in responses if r.get("lap") == 2), None)
    if ref is None or slow is None:
        detail["reason"] = "missing reference (lap 1) or slower (lap 2) response"
        return False, detail
    if "improvementRanking" in ref:
        detail["reason"] = "reference lap must not carry improvementRanking"
        return False, detail
    ranking = slow.get("improvementRanking")
    if not isinstance(ranking, list) or not ranking:
        detail["reason"] = "slower lap must carry a non-empty improvementRanking"
        return False, detail
    priorities = [r.get("priority", 0.0) for r in ranking]
    if priorities != sorted(priorities, reverse=True):
        detail["reason"] = "improvementRanking not ordered by descending priority"
        return False, detail
    detail["top"] = ranking[0]
    detail["ranking_len"] = len(ranking)
    return True, detail


async def run_inject(
    url: str,
    *,
    token: str | None = None,
    scenario: str = "baseline",
    timeout: float = 8.0,
    connect_retries: int = 40,
    connect_retry_delay: float = 0.25,
) -> tuple[int, dict[str, Any]]:
    """Connect, inject ``scenario``, evaluate the rubric. Returns ``(exit_code, detail)``.

    Uses a generous connect-retry budget (default ~10s) so the CLI / ``ci-drive`` path is
    robust against a sidecar that is still booting — the fixed sleep in
    ``baseline_copilot_check.sh`` is only a head start, not the correctness guard.
    """
    if scenario != "baseline":
        return 2, {"reason": f"unknown scenario: {scenario!r}"}
    hc = HarnessClient(url, token=token)
    try:
        await hc.connect(retries=connect_retries, retry_delay=connect_retry_delay)
    except OSError as exc:
        return 1, {"reason": f"could not connect to sidecar: {exc}"}
    try:
        ack = await hc.hello(timeout=timeout)
        if ack is None:
            return 1, {"reason": "no hello_ack from sidecar"}
        responses: list[dict[str, Any]] = []
        for frame in BASELINE_LAP_FRAMES:
            await hc.send(frame)
            resp = await hc.expect_coaching_response(lap=frame["lap"], timeout=timeout)
            if resp is not None:
                responses.append(resp)
        ok, detail = evaluate_baseline_rubric(responses)
        return (0 if ok else 1), detail
    finally:
        await hc.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(
        description="Headless AC Copilot Trainer harness client (issue #154)"
    )
    p.add_argument("--url", default="ws://127.0.0.1:8765", help="sidecar WebSocket URL")
    p.add_argument("--token", default=None, help="X-AC-Copilot-Token for non-loopback binds")
    p.add_argument("--inject", default="baseline", choices=["baseline"], help="scenario to inject")
    p.add_argument("--timeout", type=float, default=8.0, help="per-step timeout seconds")
    p.add_argument(
        "--connect-retries",
        type=int,
        default=40,
        help="initial-connect attempts (~0.25s apart) to tolerate a still-booting sidecar",
    )
    args = p.parse_args(argv)
    code, detail = asyncio.run(
        run_inject(
            args.url,
            token=args.token,
            scenario=args.inject,
            timeout=args.timeout,
            connect_retries=args.connect_retries,
        )
    )
    print(json.dumps({"pass": code == 0, "detail": detail}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
