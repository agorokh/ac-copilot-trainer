"""Versioned WebSocket JSON schema for Lua app ↔ Python sidecar (issue #45).

All frames are JSON objects. ``protocol`` is required on new messages; missing
``protocol`` on ``lap_complete`` is accepted with a warning (legacy clients).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.ai_sidecar.coaching.llm_coach import (
    compose_corner_hint,
    compose_llm_debrief_only,
    debrief_feature_enabled,
    rules_fallback_debrief,
)
from tools.ai_sidecar.features import _as_float

if TYPE_CHECKING:
    from tools.ai_sidecar.session import LapComparisonState

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

EVENT_LAP_COMPLETE = "lap_complete"
EVENT_COACHING_RESPONSE = "coaching_response"
EVENT_ANALYSIS_ERROR = "analysis_error"
EVENT_CORNER_QUERY = "corner_query"
EVENT_CORNER_ADVICE = "corner_advice"

#: A lap archive is at most a few MB; refuse to load anything larger from an archivePath.
_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
_MAX_HISTORY_ARCHIVES = 8


def _load_safe_archive_path(raw_path: Any) -> dict[str, Any] | None:
    """Load a lap-archive dict from a path, or None — with traversal-safe validation.

    NORMALIZES the path first (``Path.resolve`` collapses ``..`` / symlinks) and only then checks it
    is a ``.../journal/laps/lap_*.json`` path, so a traversal like
    ``/x/journal/laps/../../etc/lap_evil.json`` is rejected on its resolved form. Size + existence
    guarded. Never raises.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    # Defer the import so protocol.py stays importable without the coaching extra installed.
    from tools.ai_sidecar.setup_optimizer import is_supported_lap_archive_path

    try:
        resolved = Path(raw_path).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if not is_supported_lap_archive_path(str(resolved)):
        logger.debug("brain: archivePath rejected (not a journal/laps/lap_*.json): %r", raw_path)
        return None
    try:
        if not resolved.is_file() or resolved.stat().st_size > _MAX_ARCHIVE_BYTES:
            return None
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("brain: could not load archivePath %r: %s", raw_path, exc)
        return None
    return data if isinstance(data, dict) else None


def _load_safe_archive_paths(raw_paths: Any) -> list[dict[str, Any]]:
    """Load a bounded list of safe lap archives, skipping invalid entries."""
    if not isinstance(raw_paths, list):
        return []
    out: list[dict[str, Any]] = []
    for raw_path in raw_paths[:_MAX_HISTORY_ARCHIVES]:
        archive = _load_safe_archive_path(raw_path)
        if archive is not None:
            out.append(archive)
    return out


def _resolve_lap_archive(inbound: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a full lap-archive dict (with a trace) for the brain, or None.

    Prefers an inline ``trace`` on the message; else loads a safe ``archivePath``. Never raises.
    """
    trace = inbound.get("trace")
    if isinstance(trace, dict) and isinstance(trace.get("samples"), list) and trace["samples"]:
        return inbound
    return _load_safe_archive_path(inbound.get("archivePath"))


def build_brain_followup(inbound: dict[str, Any]) -> dict[str, Any] | None:
    """Build a follow-up coaching_response from the full setup-vs-technique attribution brain.

    Non-blocking follow-up (mirrors :func:`build_ollama_followup`): runs AFTER the immediate
    rules-based ack, so it never blocks the <100ms path and tolerates the async archive write.
    Resolves the lap archive (inline trace or safe ``archivePath``), runs the brain, and returns a
    coaching_response carrying the rich text debrief + a machine-readable ``cornerAnalysis``.
    Returns None on any failure or when no usable trace exists (the client keeps the rules debrief).
    """
    if not debrief_feature_enabled():
        return None
    archive = _resolve_lap_archive(inbound)
    if archive is None:
        return None
    # Normalize the lap counter: a lap_complete frame carries it as a top-level int (`lap: 9`), but
    # the archive/tyre model expects `lap.lap_n`. Without this, tyres_from_lap_archive sees no lap
    # number, so late-lap below-window tyres read as "warming" instead of persistent off-window
    # (codex #291). Shallow-copy so we never mutate the caller's inbound dict.
    lap_num = inbound.get("lap")
    if (
        isinstance(lap_num, int)
        and not isinstance(lap_num, bool)
        and not isinstance(archive.get("lap"), dict)
    ):
        archive = {**archive, "lap": {"lap_n": lap_num}}
    # optional per-car lateral grip ceiling (g) lets the brain separate grip-limited from technique
    grip_ceiling_g = _as_float(inbound.get("gripCeilingG"))
    # optional reference lap (e.g. the driver's best): unlocks the delta-based rules (time lost per
    # corner, "carried too little apex speed"). Without it the brain still emits grip/balance/exit/
    # braking attributions, just no time-loss deltas.
    reference = _load_safe_archive_path(inbound.get("referenceArchivePath"))
    # optional recent same-session laps: unlocks per-corner consistency metrics. Paths are bounded
    # and validated exactly like archivePath/referenceArchivePath.
    history = _load_safe_archive_paths(inbound.get("historyArchivePaths"))
    try:
        from tools.ai_sidecar.coach_report import build_structured_debrief

        structured = build_structured_debrief(
            archive,
            reference_archive=reference,
            history_archives=history,
            grip_ceiling_g=grip_ceiling_g,
        )
    except Exception as exc:  # the brain must never break the coaching socket
        logger.info("brain debrief raised: %s", exc)
        return None
    if not structured or not structured.get("corners"):
        return None
    response: dict[str, Any] = {
        "protocol": PROTOCOL_VERSION,
        "event": EVENT_COACHING_RESPONSE,
        "lap": inbound.get("lap"),
        "hints": [{"kind": "general", "text": "Setup-vs-technique debrief"}],
        "debrief": structured["text"],
        "debriefSource": "brain",
        "cornerAnalysis": structured["corners"],
        "balance": structured["balance"],
    }
    # Forward the machine-readable understanding blocks when the archive carried the data, so live
    # clients (and the coach-handoff path) get tyres/conditions/reference, not just prose.
    if structured.get("tyres") is not None:
        response["tyres"] = structured["tyres"]
    if structured.get("conditions") is not None:
        response["conditions"] = structured["conditions"]
    if structured.get("corner_reference") is not None:
        response["cornerReference"] = structured["corner_reference"]
    if structured.get("trail_braking") is not None:
        response["trailBraking"] = structured["trail_braking"]
    if structured.get("sector_deltas") is not None:
        response["sectorDeltas"] = structured["sector_deltas"]
    if structured.get("superlap") is not None:
        response["superLap"] = structured["superlap"]
    return response


_CORNER_LABEL_MAX_LEN = 64
_CORNER_MAX_SPEED_ABS_KMH = 450.0
_CORNER_MAX_DIST_M = 100_000.0


def prepare_outbound_message(
    inbound: dict[str, Any],
    *,
    reply_coaching: bool,
    lap_state: LapComparisonState | None = None,
) -> dict[str, Any] | None:
    """Validate ``inbound`` and build one outbound message, or ``None`` to stay silent.

    Returns:
        ``analysis_error`` for protocol violations, ``coaching_response`` when
        ``reply_coaching`` and event is ``lap_complete``, ``corner_advice`` when
        a corner hint is available, else ``None`` (including silent ``corner_query``).
    """
    proto_raw = inbound.get("protocol")
    if proto_raw is not None:
        if isinstance(proto_raw, bool):
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "invalid protocol field",
            }
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

    if event == EVENT_CORNER_QUERY and not reply_coaching:
        return None

    if event == EVENT_CORNER_QUERY:
        if proto_raw is None:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query requires protocol field",
            }
        # Round 10: in-race per-corner hint. Blocks on Ollama (~631ms with
        # llama3.2:3b + tiny prompt). The Lua side fires this async when it
        # detects topCornerLabel transitions to a new corner.
        corner = str(inbound.get("corner") or "").strip()
        for req in ("cur", "ref", "dist"):
            if req not in inbound:
                return {
                    "protocol": PROTOCOL_VERSION,
                    "event": EVENT_ANALYSIS_ERROR,
                    "message": "corner_query requires cur, ref, and dist fields",
                }

        def _corner_scalar(raw: Any) -> float:
            parsed = _as_float(raw)
            if parsed is None:
                raise ValueError
            return parsed

        try:
            cur_kmh = _corner_scalar(inbound["cur"])
            ref_kmh = _corner_scalar(inbound["ref"])
            dist_m = _corner_scalar(inbound["dist"])
        except ValueError:
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
        if len(corner) > _CORNER_LABEL_MAX_LEN:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query corner label too long",
            }
        if abs(cur_kmh) > _CORNER_MAX_SPEED_ABS_KMH or abs(ref_kmh) > _CORNER_MAX_SPEED_ABS_KMH:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query cur/ref out of range",
            }
        if dist_m < 0 or dist_m > _CORNER_MAX_DIST_M:
            return {
                "protocol": PROTOCOL_VERSION,
                "event": EVENT_ANALYSIS_ERROR,
                "message": "corner_query dist out of range",
            }
        hint = compose_corner_hint(
            corner=corner,
            cur_kmh=cur_kmh,
            ref_kmh=ref_kmh,
            dist_m=dist_m,
        )
        if not hint:
            return None
        return {
            "protocol": PROTOCOL_VERSION,
            "event": EVENT_CORNER_ADVICE,
            "corner": corner,
            "lap": inbound.get("lap"),
            "text": hint,
        }

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
