"""Between-lap improvement selector — exactly one next-lap ``corner_advice`` (#675 Part 2).

Chooses the single highest-value corner from the Coach v2 ledger (or a ranked improvement
list), optionally asks Ollama for a short phrase, and **fail-closes** on hallucinated corner
identity / empty text before anything is spoken.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from tools.ai_sidecar.coaching.llm_coach import call_ollama_generate, debrief_feature_enabled
from tools.ai_sidecar.coaching_diagnosis import PHRASE, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger, Status
from tools.ai_sidecar.track_reference import CornerReference

_log = logging.getLogger("ai_sidecar.coaching.between_lap")

_CORNER_LABEL_MAX = 64


def _corner_in_refs(corner: int, refs: Sequence[CornerReference]) -> bool:
    return any(r.index == corner for r in refs)


def _rules_phrase(root: RootError | None, corner: int) -> str:
    if root is not None and root != RootError.NONE and root in PHRASE:
        return f"NEXT LAP T{corner}: {PHRASE[root]}"
    return f"NEXT LAP: FOCUS T{corner}"


def select_focus_corner(
    ledger: CoachingLedger | None,
    improvement_ranking: Sequence[Mapping[str, Any]] | None = None,
    *,
    valid_corners: Sequence[int] | None = None,
) -> int | None:
    """Pick exactly one corner index, or ``None`` when nothing is coachable."""
    allowed = set(valid_corners) if valid_corners is not None else None

    if ledger is not None:
        focus = ledger.focus_corner()
        if focus is not None and (allowed is None or focus in allowed):
            return focus
        # Scan the declared corner set for any live root ranked by time lost.
        scan = allowed if allowed is not None else set()
        candidates = []
        for idx in scan:
            st = ledger.state(idx)
            if (
                st is not None
                and st.root != RootError.NONE
                and st.status
                in (Status.ARMED, Status.PRIMED, Status.DETECTING, Status.HEALING)
            ):
                candidates.append(st)
        if candidates:
            return max(candidates, key=lambda s: s.time_lost_s).corner

    for row in improvement_ranking or ():
        if not isinstance(row, Mapping):
            continue
        raw = row.get("corner")
        try:
            corner = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if allowed is not None and corner not in allowed:
            continue
        return corner
    return None


def validate_corner_advice(
    *,
    corner: int | None,
    text: str | None,
    refs: Sequence[CornerReference],
) -> dict[str, Any] | None:
    """Fail-closed validator: known corner identity + non-empty text, or ``None``."""
    if corner is None or not isinstance(corner, int) or isinstance(corner, bool):
        return None
    if corner < 0 or not _corner_in_refs(corner, refs):
        _log.info("between-lap advice rejected: unknown corner=%s", corner)
        return None
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.strip().split())
    if len(cleaned) < 4 or len(cleaned.split()) < 2:
        _log.info("between-lap advice rejected: empty/short text for corner=%s", corner)
        return None
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    label = f"T{corner}"
    if len(label) > _CORNER_LABEL_MAX:
        return None
    return {"corner": corner, "corner_label": label, "text": cleaned}


def compose_between_lap_advice(
    *,
    corner: int,
    root: RootError | None,
    refs: Sequence[CornerReference],
    use_ollama: bool = True,
) -> dict[str, Any] | None:
    """Build one validated between-lap advice payload (Ollama optional, rules fallback)."""
    if not _corner_in_refs(corner, refs):
        return None
    text: str | None = None
    if use_ollama and debrief_feature_enabled():
        root_s = str(root) if root and root != RootError.NONE else "general"
        phrase = PHRASE.get(root, "improve the corner") if root else "improve the corner"
        prompt = (
            "You coach Assetto Corsa. Reply with ONE short next-lap focus command.\n"
            "RULES: Max 10 words. UPPERCASE. Name the corner as "
            f"T{corner}. Use verbs BRAKE/LIFT/CARRY/TURN/HOLD only.\n"
            f"Focus root={root_s}; suggested={phrase}\n"
            f"NOW: next-lap focus for T{corner} ->"
        )
        raw = call_ollama_generate(
            prompt,
            temperature=0.2,
            num_predict=24,
            timeout_sec=10.0,
        )
        if raw:
            for line in raw.strip().splitlines():
                candidate = line.strip().strip("\"'")
                for pre in ("Action:", "Reply:", "Command:", "ANSWER:", "->", "=>"):
                    if candidate.upper().startswith(pre.upper()):
                        candidate = candidate[len(pre) :].strip()
                if "." in candidate:
                    candidate = candidate.split(".", 1)[0].strip() + "."
                words = [w for w in candidate.split() if w]
                if len(words) >= 2 and len(candidate) >= 4:
                    text = candidate.upper()[:120]
                    break
    if not text:
        text = _rules_phrase(root, corner)
    return validate_corner_advice(corner=corner, text=text, refs=refs)


def select_between_lap_advice(
    *,
    refs: Sequence[CornerReference],
    ledger: CoachingLedger | None = None,
    improvement_ranking: Sequence[Mapping[str, Any]] | None = None,
    use_ollama: bool = True,
) -> dict[str, Any] | None:
    """Select and validate exactly one next-lap improvement point for ``corner_advice``."""
    valid = [r.index for r in refs]
    corner = select_focus_corner(ledger, improvement_ranking, valid_corners=valid)
    if corner is None:
        return None
    root: RootError | None = None
    if ledger is not None:
        st = ledger.state(corner)
        if st is not None and st.root != RootError.NONE:
            root = st.root
    return compose_between_lap_advice(
        corner=corner, root=root, refs=refs, use_ollama=use_ollama
    )
