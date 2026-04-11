"""Async WebSocket server: versioned lap JSON from Lua + optional coaching replies (issue #45).

Run: python -m tools.ai_sidecar
Requires optional extra: pip install -e ".[coaching]"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tools.ai_sidecar.protocol import (
    EVENT_ANALYSIS_ERROR,
    EVENT_COACHING_RESPONSE,
    PROTOCOL_VERSION,
    build_ollama_followup,
    prepare_outbound_message,
)
from tools.ai_sidecar.session import LapComparisonState

logger = logging.getLogger(__name__)

# Strong refs so asyncio.Task objects are not GC'd mid-flight (Python docs).
_background_tasks: set[asyncio.Task[Any]] = set()


def _run_compare_laps(last_path: str, ref_path: str) -> None:
    """CLI harness: two lap JSON files → improvement ranking on stdout (issue #49)."""
    try:
        last = json.loads(Path(last_path).read_text(encoding="utf-8"))
        ref = json.loads(Path(ref_path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SystemExit(f"compare-laps: file not found: {e.filename!r}") from e
    except PermissionError as e:
        raise SystemExit(f"compare-laps: cannot read file: {e}") from e
    except json.JSONDecodeError as e:
        raise SystemExit(f"compare-laps: invalid JSON ({e.msg} at char {e.pos})") from e
    from tools.ai_sidecar.features import extract_corner_table
    from tools.ai_sidecar.improvement_ranking import rank_corner_improvements

    ranked = rank_corner_improvements(
        extract_corner_table(last),
        extract_corner_table(ref),
    )
    print(json.dumps(ranked, indent=2))


async def _send_ollama_followup(
    websocket: Any,
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> None:
    """Call Ollama in a background task and send a follow-up coaching_response.

    Runs AFTER the immediate rules-based response has been sent. Uses
    asyncio.to_thread because the llm_coach helpers are sync. Silently
    discards on any error (the socket may have closed in the meantime).
    """
    try:
        followup = await asyncio.to_thread(
            build_ollama_followup,
            inbound,
            improvement_ranking,
        )
    except Exception as e:
        logger.info("ollama followup raised: %s", e)
        return
    if followup is None:
        return
    await _safe_send(websocket, followup)


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
    lap_state = LapComparisonState()
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

        out = await asyncio.to_thread(
            prepare_outbound_message,
            data,
            reply_coaching=reply_coaching,
            lap_state=lap_state,
        )
        if out is not None:
            await _safe_send(websocket, out)

            # Round 8: schedule Ollama follow-up in the background so the
            # immediate response above is not blocked on LLM latency. CSP
            # receives hints+rules_debrief in <100ms, then gets the Ollama
            # debrief as a second message when it's ready (~5-15s later).
            if (
                reply_coaching
                and data.get("event") == "lap_complete"
                and isinstance(out, dict)
                and out.get("event") == EVENT_COACHING_RESPONSE
            ):
                # Reuse improvementRanking from the immediate response — calling
                # improvement_ranking_for again mutates LapComparisonState and
                # diverges on PB laps (Bugbot).
                imp_for_bg = out.get("improvementRanking") or []
                bg_task = asyncio.create_task(_send_ollama_followup(websocket, data, imp_for_bg))
                _background_tasks.add(bg_task)
                bg_task.add_done_callback(_background_tasks.discard)


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
        "--compare-laps",
        nargs=2,
        metavar=("LAST_JSON", "REF_JSON"),
        help=(
            "Print corner improvement ranking JSON from two lap_complete-style fixtures "
            "(telemetry.corners) and exit."
        ),
    )
    p.add_argument(
        "--no-reply",
        action="store_true",
        help=(
            "Log lap_complete only; do not send coaching_response. "
            "analysis_error frames may still be sent for invalid JSON or non-object payloads."
        ),
    )
    args = p.parse_args()
    if args.compare_laps:
        _run_compare_laps(args.compare_laps[0], args.compare_laps[1])
        return
    reply = not args.no_reply
    try:
        asyncio.run(_run(args.host, args.port, reply))
    except KeyboardInterrupt:
        logger.info("sidecar stopped")


if __name__ == "__main__":
    main()
