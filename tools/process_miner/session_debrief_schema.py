"""Stable JSONL schema for ``scripts/session_debrief.py`` output.

Each line in ``.cache/session_debriefs/debrief-YYYY-MM-DD.jsonl`` is one JSON object.

``schema_version`` is bumped only when required fields or semantics change; readers must
tolerate unknown keys and missing optional fields (best-effort ingest).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
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


def _is_absolute_any_platform(s: str) -> bool:
    """Whether ``s`` is absolute under POSIX *or* Windows path semantics.

    ``Path.is_absolute()`` is host-specific: on Windows
    ``WindowsPath('/etc/passwd').is_absolute()`` is ``False`` (no drive letter),
    so a host-native check lets POSIX-style absolute paths slip through the
    absolute-path / traversal guard. Testing both pure flavours catches a leading
    ``/`` or ``\\``, drive letters (``C:/...``), and UNC prefixes
    (``//server/share``) regardless of the host OS.
    """
    return PurePosixPath(s).is_absolute() or PureWindowsPath(s).is_absolute()


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
        # Normalize separators first so the absolute-path check below sees a
        # single, OS-independent form (e.g. ``\\server\share`` -> ``//server/share``).
        normalized = item.strip().replace("\\", "/")
        if _is_absolute_any_platform(normalized):
            # Only a *host-absolute* path can be meaningfully resolved and
            # relativized against ``root``. A path that is absolute on the OTHER
            # OS flavour (``C:/x`` on POSIX, ``/etc/x`` on Windows) is NOT
            # host-absolute, so ``Path(normalized).resolve()`` would anchor it to
            # the CWD and ``relative_to(root)`` could *admit* it as a contained
            # relative path when the CWD lies under ``root``. Skip those outright
            # (gemini-code-assist HIGH, PR #303/#304).
            if root is None or not Path(normalized).is_absolute():
                continue
            try:
                rel = Path(normalized).resolve().relative_to(root)
                out.append(rel.as_posix())
            except ValueError:
                continue
            continue
        p = Path(normalized)
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
