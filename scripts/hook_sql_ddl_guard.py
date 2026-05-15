#!/usr/bin/env python3
"""PreToolUse:Edit|Write flow-control hook. Deterministic SQL DDL guard.

Replaces the historical ``type: "prompt"`` SQL DDL hook (issue #107). LLM
classifiers stalled child-repo sessions (40+ consecutive brown-out loops in
production) whenever the routing classifier flaked; deterministic regex is
fail-open and never blocks on classifier outage.

Behavior:
  * **Opt-in.** When ``CLAUDE_SQL_DDL_GUARD`` is unset or ``0`` the hook still
    reads stdin to completion (so large payloads never wedge the parent pipe)
    and then exits 0. The template default is "guard available, not enforced"
    so non-SQL child repos pay only the stdin drain cost, not regex work.
  * When opt-in is on, the hook scans **added content** on Edit/Write tool
    calls for DDL keywords. A hit produces ``exit 2`` (Claude Code blocks the
    call) with a stderr reason.
  * Migration-shaped paths (``migrations/``, ``db/migrations/``, ``schema/``,
    ``*_migration*``), tests (``tests/``, ``test_*``), and docs (``*.md``,
    ``docs/``) are allowed even when the content contains DDL — those are the
    legitimate write paths for schema work.

Fail-open contract:
  * Malformed JSON → exit 0.
  * Missing fields → exit 0.
  * Unknown tool name → exit 0.
  * Any unexpected exception → exit 0 (never wedge the agent).
"""

from __future__ import annotations

import json
import os
import re
import sys

# DDL verbs that mutate schema. Word-boundary match against added content.
_DDL_RE = re.compile(
    r"\b(?:CREATE(?:\s+(?:TEMP(?:ORARY)?|EXTERNAL|OR\s+REPLACE))*\s+TABLE"
    r"|ALTER\s+TABLE"
    r"|DROP\s+TABLE"
    r"|ADD\s+COLUMN"
    r"|DROP\s+COLUMN"
    r"|RENAME\s+COLUMN"
    r"|RENAME\s+TABLE"
    r"|TRUNCATE(?:\s+TABLE)?"
    r"|CREATE(?:\s+UNIQUE)?\s+INDEX"
    r"|DROP\s+INDEX"
    r"|CREATE(?:\s+OR\s+REPLACE)?\s+VIEW"
    r"|DROP\s+VIEW"
    r"|CREATE\s+(?:SCHEMA|DATABASE)"
    r"|DROP\s+(?:SCHEMA|DATABASE))\b",
    re.IGNORECASE,
)

# Paths where DDL is expected and allowed without prompting.
_ALLOW_PATH_RE = re.compile(
    r"(?:^|/)(?:migrations?|db/migrations?|schema|alembic|liquibase|flyway|"
    r"tests?|spec|__tests__|docs?)/"
    r"|(?:^|/)test_"
    r"|_migration"
    r"|\.md$"
    r"|\.rst$",
    re.IGNORECASE,
)


def _added_content(tool_input: dict) -> str:
    """Return the text that this tool call would add to the file.

    Handles Write (`content`), Edit (`new_string`), and MultiEdit (`edits[*].new_string`).
    """
    parts: list[str] = []
    val = tool_input.get("content")
    if isinstance(val, str):
        parts.append(val)
    val = tool_input.get("new_string")
    if isinstance(val, str):
        parts.append(val)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict):
                ns = e.get("new_string")
                if isinstance(ns, str):
                    parts.append(ns)
    return "\n".join(parts)


def _guard_enabled() -> bool:
    """``CLAUDE_SQL_DDL_GUARD`` must be explicitly truthy to engage the block."""
    val = os.environ.get("CLAUDE_SQL_DDL_GUARD", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _main() -> int:
    # Drain stdin first so the default (guard off) path never leaves the parent
    # blocked on a large hook payload.
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 — fail-open contract
        return 0

    if not _guard_enabled():
        return 0
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001 — fail-open contract
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    # Normalize backslashes so Windows-style paths also match the allow regex.
    norm_path = file_path.replace("\\", "/")
    if _ALLOW_PATH_RE.search(norm_path):
        return 0

    added = _added_content(tool_input)
    if not added:
        return 0

    m = _DDL_RE.search(added)
    if not m:
        return 0

    sys.stderr.write(
        f"BLOCK: SQL DDL ({m.group(0).strip()}) detected in {file_path!r}; "
        "place DDL under migrations/ or db/migrations/ (or a tests/ fixture). "
        "Set CLAUDE_SQL_DDL_GUARD=0 to disable this guard.\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(_main())
    except Exception:  # noqa: BLE001 — last-resort fail-open
        sys.exit(0)
