"""Versioned WebSocket JSON schema for Lua app ↔ Python sidecar (issue #45).

All frames are JSON objects. ``protocol`` is required on new messages; missing
``protocol`` on ``lap_complete`` is accepted with a warning (legacy clients).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.ai_sidecar.session import LapComparisonState

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

EVENT_LAP_COMPLETE = "lap_complete"
EVENT_COACHING_RESPONSE = "coaching_response"
EVENT_ANALYSIS_ERROR = "analysis_error"


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
    if lap_state is not None:
        imp = lap_state.improvement_ranking_for(inbound)
        if imp:
            out["improvementRanking"] = imp
    return out
