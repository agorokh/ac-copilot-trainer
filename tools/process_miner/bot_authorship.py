"""Bot login normalization and review-body structure parsing (#56)."""

from __future__ import annotations

import json
import os
import re
import warnings
from typing import Any

from tools.process_miner.schemas import PRData

_MERGED_ALIASES_ENV_SNAPSHOT: str | None = None
_MERGED_ALIASES_RESULT: dict[str, str] | None = None


def clear_merged_bot_aliases_cache() -> None:
    """Drop cached ``PROCESS_MINER_BOT_ALIASES_JSON`` merge (for tests)."""
    global _MERGED_ALIASES_ENV_SNAPSHOT, _MERGED_ALIASES_RESULT
    _MERGED_ALIASES_ENV_SNAPSHOT = None
    _MERGED_ALIASES_RESULT = None


# Lowercase GitHub login -> stable short name for training / reports.
BOT_LOGIN_ALIASES: dict[str, str] = {
    "coderabbitai": "coderabbit",
    "coderabbitai[bot]": "coderabbit",
    "gemini-code-assist": "gemini",
    "gemini-code-assist[bot]": "gemini",
    "copilot-pull-request-reviewer": "copilot",
    "copilot-pull-request-reviewer[bot]": "copilot",
    "copilot": "copilot",
    "sourcery-ai": "sourcery",
    "sourcery-ai[bot]": "sourcery",
    "qodo-merge-pro": "qodo",
    "qodo-merge-pro[bot]": "qodo",
    "qodo-merge": "qodo",
    "qodo-merge[bot]": "qodo",
    "cursor": "bugbot",
    "cursor[bot]": "bugbot",
    "github-actions[bot]": "github_actions",
    "github-actions": "github_actions",
}

# Max chars kept per ``##`` section body and for multi-bot JSONL ``bot_comments.body`` (#56).
BOT_REVIEW_TEXT_CLIP_CHARS = 4000


def normalize_bot_canonical_name(raw: str) -> str:
    """Stable short id for training/stats (matches unknown ``Bot`` login slugging)."""
    k = raw.lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", k).strip("_") or k


def _merged_bot_login_aliases() -> dict[str, str]:
    """Defaults plus optional ``PROCESS_MINER_BOT_ALIASES_JSON`` (object of login→short name)."""
    global _MERGED_ALIASES_ENV_SNAPSHOT, _MERGED_ALIASES_RESULT
    raw = (os.environ.get("PROCESS_MINER_BOT_ALIASES_JSON") or "").strip()
    if _MERGED_ALIASES_RESULT is not None and _MERGED_ALIASES_ENV_SNAPSHOT == raw:
        return dict(_MERGED_ALIASES_RESULT)

    out = dict(BOT_LOGIN_ALIASES)
    if not raw:
        _MERGED_ALIASES_ENV_SNAPSHOT = raw
        _MERGED_ALIASES_RESULT = out
        return dict(out)
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError:
        warnings.warn(
            "PROCESS_MINER_BOT_ALIASES_JSON is not valid JSON; using default bot aliases only",
            UserWarning,
            stacklevel=2,
        )
        _MERGED_ALIASES_ENV_SNAPSHOT = raw
        _MERGED_ALIASES_RESULT = dict(BOT_LOGIN_ALIASES)
        return dict(_MERGED_ALIASES_RESULT)
    if not isinstance(extra, dict):
        warnings.warn(
            "PROCESS_MINER_BOT_ALIASES_JSON must be a JSON object; using default bot aliases only",
            UserWarning,
            stacklevel=2,
        )
        _MERGED_ALIASES_ENV_SNAPSHOT = raw
        _MERGED_ALIASES_RESULT = dict(BOT_LOGIN_ALIASES)
        return dict(_MERGED_ALIASES_RESULT)
    skipped_keys: list[object] = []
    for k, v in extra.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            out[k.lower().strip()] = normalize_bot_canonical_name(v)
        else:
            skipped_keys.append(k)
    if skipped_keys:
        sample = skipped_keys[:5]
        warnings.warn(
            "PROCESS_MINER_BOT_ALIASES_JSON ignored "
            f"{len(skipped_keys)} invalid entr(y/ies); key sample: {sample!r}",
            UserWarning,
            stacklevel=2,
        )
    _MERGED_ALIASES_ENV_SNAPSHOT = raw
    _MERGED_ALIASES_RESULT = out
    return dict(out)


def distinct_bot_names_for_pr(pr: PRData) -> set[str]:
    """Normalized bot ids with ≥1 comment on this PR (review + issue comments)."""
    return {
        c.bot_name
        for c in pr.review_comments + pr.issue_comments
        if c.author_type == "bot" and c.bot_name
    }


def bot_agreement_location_key(*, path: str | None, line: int | None, comment_id: str) -> str:
    """Stable key for bot co-occurrence: inline file+line, else path+comment id, else comment id.

    Non-file keys use the ``thread:`` prefix as a label only; the suffix is still ``comment_id``
    (we do not model GitHub review thread ids on ``ReviewComment``).

    Avoids collapsing distinct comments when ``path`` is set but ``line`` is missing, and
    avoids stringifying ``None`` as the literal ``\"None\"``.
    """
    if path and line is not None:
        return f"inline:{path}:{int(line)}"
    if path:
        return f"file:{path}:id:{comment_id}"
    return f"thread:{comment_id}"


def infer_author_from_user(user: dict[str, Any] | None) -> tuple[str, str, str | None]:
    """Derive (login, author_type, bot_name) from a GitHub API ``user`` object.

    ``author_type`` is ``\"bot\"``, ``\"human\"``, or ``\"unknown\"`` (missing user).
    Known bot logins in the alias map are treated as bots even when ``type`` is ``User``.
    ``bot_name`` is a normalized id for bots; ``None`` for humans/unknown.
    """
    if not user:
        return "unknown", "unknown", None
    login = str(user.get("login") or "unknown")
    gh_type = str(user.get("type") or "User")
    key = login.lower()
    aliases = _merged_bot_login_aliases()
    mapped = aliases.get(key)
    if gh_type == "Bot":
        bot_name = mapped
        if bot_name is None:
            bot_name = re.sub(r"[^a-z0-9]+", "_", key).strip("_") or key
        return login, "bot", bot_name
    if mapped is not None:
        return login, "bot", mapped
    return login, "human", None


def parse_review_structure(
    body: str, author_type: str, _bot_name: str | None
) -> dict[str, str] | None:
    """Extract ``##`` markdown sections from bot review bodies when present.

    Fenced code blocks are removed before matching headers so ``##`` inside code is ignored;
    section text is taken from that scrubbed view (Tier 1: code in sections may be omitted).
    """
    if author_type != "bot" or not (body or "").strip():
        return None
    # Avoid false ``##`` hits inside fenced code (shell comments, C preprocessor, etc.).
    scan_body = re.sub(r"```[\s\S]*?```", "", body)
    sections: dict[str, str] = {}
    header = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(header.finditer(scan_body))
    if not matches:
        return None
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(scan_body)
        chunk = scan_body[start:end].strip()
        if chunk:
            sections[title] = chunk[:BOT_REVIEW_TEXT_CLIP_CHARS]
    return sections or None
