"""Versioned WebSocket JSON schema for Lua app ↔ Python sidecar (issue #45).

All frames are JSON objects. ``protocol`` is required on new messages; missing
``protocol`` on ``lap_complete`` is accepted with a warning (legacy clients).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.ai_sidecar.coaching.llm_coach import (
    compose_corner_hint,
    compose_debrief,
    compose_llm_debrief_only,
    rules_fallback_debrief,
    debrief_feature_enabled,
)

if TYPE_CHECKING:
    from tools.ai_sidecar.session import LapComparisonState

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

EVENT_LAP_COMPLETE = "lap_complete"
EVENT_COACHING_RESPONSE = "coaching_response"
EVENT_ANALYSIS_ERROR = "analysis_error"
EVENT_CORNER_QUERY = "corner_query"
EVENT_CORNER_ADVICE = "corner_advice"


def prepare_outbound_message(
    inbound: dict[str, Any],
    *,
    reply_coaching: bool,
    lap_state: LapComparisonState | None = None,
) -> dict[str, Any] | None:
    """Validate ``inbound`` and build one outbound message, or ``None`` to stay silent.

    Returns:
        ``analysis_error`` for protocol violations, ``coaching_response`` when
        ``reply_coaching`` and event is ``lap_complete``, else ``None``.
    """
    proto_raw = inbound.get("protocol")
    if proto_raw is not None:
        try:
            pv = int(proto_raw)
        except (TypeError, ValueError):
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "invalid protocol field",
            }
        if pv != PROTOCOL_VERSION:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": f"unsupported protocol {proto_raw!r} (supported: {PROTOCOL_VERSION})",
            }

    event = inbound.get("event")

    if event == EVENT_CORNER_QUERY:
        # Round 10: in-race per-corner hint. Blocks on Ollama (~631ms with
        # llama3.2:3b + tiny prompt). The Lua side fires this async when it
        # detects topCornerLabel transitions to a new corner.
        corner = str(inbound.get("corner") or "").strip()
        try:
            cur_kmh = float(inbound.get("cur") or 0)
            ref_kmh = float(inbound.get("ref") or 0)
            dist_m = float(inbound.get("dist") or 0)
        except (TypeError, ValueError):
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query requires numeric cur/ref/dist",
            }
        if not corner:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query requires corner label",
            }
        hint = compose_corner_hint(
            corner=corner,
            cur_kmh=cur_kmh,
            ref_kmh=ref_kmh,
            dist_m=dist_m,
        )
        out: dict[str, Any] = {
            "protocol": PROTOCOL_VERSION,
            "event": EVENT_CORNER_ADVICE,
            "corner": corner,
            "lap": inbound.get("lap"),
        }
        if hint:
            out["text"] = hint
        return out

    if event != EVENT_LAP_COMPLETE:
        logger.debug("ignored event=%s keys=%s", event, list(inbound.keys())[:12])
        return None

    if proto_raw is None:
        logger.warning("lap_complete without protocol; assuming v%s", PROTOCOL_VERSION)

    if not reply_coaching:
        return None

    lap = inbound.get("lap")
    out: dict[str, Any] = {
        "protocol": PROTOCOL_VERSION,
        "event": EVENT_COACHING_RESPONSE,
        "lap": lap,
        "hints": [
            {
                "kind": "general",
                "text": f"Sidecar v{PROTOCOL_VERSION}: ack lap {lap!s}",
            },
        ],
    }
    imp: list[dict[str, Any]] = []
    if lap_state is not None:
        imp = lap_state.improvement_ranking_for(inbound)
        if imp:
            out["improvementRanking"] = imp

    # Round 8: DO NOT block on Ollama here. Return the rules-based debrief
    # immediately so CSP gets a fast response (<100ms) and does not close
    # the socket while we're still waiting on the LLM. The server then
    # spawns a background task that sends a follow-up coaching_response
    # with the Ollama debrief IF it completes before the socket closes.
    if debrief_feature_enabled():
        out["debrief"] = rules_fallback_debrief(inbound, imp)
    return out


def build_ollama_followup(
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a second coaching_response with the REAL Ollama debrief.

    Round 9: uses compose_llm_debrief_only which returns None on any LLM
    failure (timeout, empty response, etc.) — so we do NOT send a follow-up
    that merely duplicates the immediate rules debrief. Returns None if
    Ollama failed; the client keeps the rules response from the immediate
    message.
    """
    if not debrief_feature_enabled():
        return None
    debrief = compose_llm_debrief_only(inbound, improvement_ranking)
    if not debrief:
        return None
    return {
        "protocol": PROTOCOL_VERSION,
        "event": EVENT_COACHING_RESPONSE,
        "lap": inbound.get("lap"),
        "hints": [
            {
                "kind": "general",
                "text": "Ollama debrief",
            },
        ],
        "debrief": debrief,
        "debriefSource": "ollama",
    }
