"""Async WebSocket receiver for lap_complete JSON from the Lua app (logs events; no echo).

Run: python -m tools.ai_sidecar
Requires optional extra: pip install -e ".[coaching]"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _handler(websocket: Any) -> None:
    async for message in websocket:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("non-json message: %s", message[:200] if message else "")
            continue
        event = data.get("event")
        if event == "lap_complete":
            lap = data.get("lap")
            hints = data.get("coachingHints") or []
            logger.info("lap_complete lap=%s hints=%s", lap, hints)
        else:
            logger.debug("event=%s keys=%s", event, list(data.keys())[:10])


async def _run(host: str, port: int) -> None:
    try:
        import websockets
    except ImportError as e:
        raise SystemExit('websockets is required. Install: pip install -e ".[coaching]"') from e

    async with websockets.serve(_handler, host, port):
        logger.info("AI sidecar listening on ws://%s:%s", host, port)
        await asyncio.Future()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="AC Copilot Trainer AI sidecar (WebSocket)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    try:
        asyncio.run(_run(args.host, args.port))
    except KeyboardInterrupt:
        logger.info("sidecar stopped")


if __name__ == "__main__":
    main()
