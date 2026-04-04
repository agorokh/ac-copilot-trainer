"""Async WebSocket server: versioned lap JSON from Lua + optional coaching replies (issue #45).

Run: python -m tools.ai_sidecar
Requires optional extra: pip install -e ".[coaching]"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from tools.ai_sidecar.protocol import (
    EVENT_ANALYSIS_ERROR,
    PROTOCOL_VERSION,
    prepare_outbound_message,
)

logger = logging.getLogger(__name__)


async def _safe_send(websocket: Any, payload: dict[str, Any]) -> None:
    try:
        await websocket.send(json.dumps(payload, separators=(",", ":")))
    except Exception:
        logger.exception("websocket send failed")


async def _handler(websocket: Any, reply_coaching: bool) -> None:
    peer = getattr(websocket, "remote_address", None)
    logger.info(
        "sidecar client connected protocol=%s peer=%s",
        PROTOCOL_VERSION,
        peer,
    )
    async for message in websocket:
        if not isinstance(message, str):
            logger.warning("non-text frame ignored type=%s", type(message).__name__)
            continue
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("invalid json (first 200 chars): %s", message[:200])
            await _safe_send(
                websocket,
                {
                    "protocol": PROTOCOL_VERSION,
                    "event": EVENT_ANALYSIS_ERROR,
                    "message": "invalid json",
                },
            )
            continue
        if not isinstance(data, dict):
            logger.warning("json root must be object, got %s", type(data).__name__)
            await _safe_send(
                websocket,
                {
                    "protocol": PROTOCOL_VERSION,
                    "event": EVENT_ANALYSIS_ERROR,
                    "message": "root must be a JSON object",
                },
            )
            continue

        if data.get("event") == "lap_complete":
            hints = data.get("coachingHints") or []
            logger.info(
                "lap_complete lap=%s lapTimeMs=%s hints=%s",
                data.get("lap"),
                data.get("lapTimeMs"),
                hints,
            )

        out = prepare_outbound_message(data, reply_coaching=reply_coaching)
        if out is not None:
            await _safe_send(websocket, out)


async def _run(host: str, port: int, reply_coaching: bool) -> None:
    try:
        import websockets
    except ImportError as e:
        raise SystemExit('websockets is required. Install: pip install -e ".[coaching]"') from e

    async with websockets.serve(
        lambda ws: _handler(ws, reply_coaching),
        host,
        port,
    ):
        logger.info(
            "AI sidecar listening host=%s port=%s protocol=%s reply_coaching=%s",
            host,
            port,
            PROTOCOL_VERSION,
            reply_coaching,
        )
        await asyncio.Future()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="AC Copilot Trainer AI sidecar (WebSocket)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--no-reply",
        action="store_true",
        help="Log lap_complete only; do not send coaching_response (half-duplex / passive mode).",
    )
    args = p.parse_args()
    reply = not args.no_reply
    try:
        asyncio.run(_run(args.host, args.port, reply))
    except KeyboardInterrupt:
        logger.info("sidecar stopped")


if __name__ == "__main__":
    main()
