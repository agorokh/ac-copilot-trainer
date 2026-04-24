"""Stable JSONL schema for ``scripts/session_debrief.py`` output.

Each line in ``.cache/session_debriefs/debrief-YYYY-MM-DD.jsonl`` is one JSON object.

``schema_version`` is bumped only when required fields or semantics change; readers must
tolerate unknown keys and missing optional fields (best-effort ingest).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

# Bump when breaking or extending required semantics for consumers.
SESSION_DEBRIEF_SCHEMA_VERSION: int = 1


class SessionDebriefHookPayload(TypedDict, total=False):
    """Subset of Stop-hook JSON passed on stdin (optional)."""

    event: str
    tool_name: str
    matcher: str


class SessionDebriefRecord(TypedDict, total=False):
    """In-memory shape of one JSONL row (all fields optional except normative writer fields)."""

    schema_version: int
    ts: str  # ISO-8601 UTC with Z suffix
    hook: SessionDebriefHookPayload
    hook_payload_hash: str
    session_debrief_ci: str
    session_debrief_mistakes: str
    session_debrief_files: list[str] | str  # JSON array in env; may be str if JSON invalid
    session_debrief_patterns: list[str] | str


def normalize_path_list(value: Any, *, repo_root: Path | None = None) -> list[str]:
    """Turn ``session_debrief_files`` env/record value into repo-relative posix paths."""
    raw: list[Any]
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = value
    else:
        return []

    out: list[str] = []
    root = repo_root.resolve() if repo_root is not None else None
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        p = Path(item.strip().replace("\\", "/"))
        if p.is_absolute():
            if root is None:
                continue
            try:
                rel = p.resolve().relative_to(root)
                out.append(rel.as_posix())
            except ValueError:
                continue
            continue
        if ".." in p.parts:
            continue
        posix = p.as_posix()
        while posix.startswith("./"):
            posix = posix[2:]
        out.append(posix)
    return list(dict.fromkeys(out))


def normalize_pattern_list(value: Any) -> list[str]:
    """Turn ``session_debrief_patterns`` into plain strings."""
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []
