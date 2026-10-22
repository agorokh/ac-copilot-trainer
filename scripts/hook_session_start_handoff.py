#!/usr/bin/env python3
# OWNER: @agorokh
"""SessionStart LOAD: print the newest dated handoff node(s) (governance-hub#918).

A SAVE writes one new dated node ``00_System/handoffs/YYYY-MM-DD-HHMMSSZ-<slug>.md`` and edits
no shared file (``Next Session Handoff.md``, ``Current Focus.md``, an ``_index.md``): two
handoffs that edit a shared file conflict by construction. So LOAD cannot reach a new node
through ``Next Session Handoff.md``; it reads the handoffs directory by filename instead.

Prints every node that shares the maximum ``YYYY-MM-DD-HHMMSSZ`` timestamp (a suffix after the
slug is not chronological), then the names of the next ``OLDER_LISTED`` older nodes. When no
dated node exists it falls back to ``Next Session Handoff.md``. Output is capped at
``MAX_CHARS`` so the host shows it in full; anything over the cap is cut with the path to read.
Never fails a session: any error prints one line and exits 0.

Ported from mcp-servers ``scripts/hook_session_start_handoff.py`` (gov-hub#467); the vault
system directory is an argument so a child repo passes its own project key.

Usage: hook_session_start_handoff.py [REPO_ROOT] [SYSTEM_DIR]
  REPO_ROOT   default: $CLAUDE_PROJECT_DIR, else cwd
  SYSTEM_DIR  vault system directory relative to REPO_ROOT
              (default: docs/01_Vault/AcCopilotTrainer/00_System)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MAX_CHARS = 9000
OLDER_LISTED = 4
DATED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{6}Z)-.+\.md$")
DEFAULT_SYSTEM = "docs/01_Vault/AcCopilotTrainer/00_System"
POINTER = "Next Session Handoff.md"


def dated_nodes(handoffs_dir: Path) -> dict[str, list[Path]]:
    """Dated node files grouped by their timestamp; {} when there are none."""
    if not handoffs_dir.is_dir():
        return {}
    stamped: dict[str, list[Path]] = {}
    for path in handoffs_dir.iterdir():
        m = DATED_RE.match(path.name)
        if m and path.is_file() and not path.is_symlink():
            stamped.setdefault(m.group(1), []).append(path)
    return stamped


def render(repo_root: Path, system_dir: str = DEFAULT_SYSTEM, max_chars: int = MAX_CHARS) -> str:
    system = repo_root / system_dir
    stamped = dated_nodes(system / "handoffs")
    rel = lambda p: p.relative_to(repo_root).as_posix()  # noqa: E731
    older: list[Path] = []
    if stamped:
        stamps = sorted(stamped)
        nodes = sorted(stamped[stamps[-1]], key=lambda p: p.name)
        for stamp in reversed(stamps[:-1]):
            older.extend(sorted(stamped[stamp], key=lambda p: p.name, reverse=True))
        older = older[:OLDER_LISTED]
        header = (
            f"Session handoff: newest dated node(s), {len(nodes)} file(s) "
            "(LOAD reads handoffs/ by filename, governance-hub#918):"
        )
    else:
        pointer = system / POINTER
        if not pointer.is_file():
            return "No handoff found."
        nodes = [pointer]
        header = "Session handoff: no dated node yet; showing the pointer file:"
    footer = ""
    if older:
        footer = "\nOlder dated nodes: " + ", ".join(rel(p) for p in older) + "\n"
    parts = [header]
    budget = max_chars - len(header) - len(footer)
    for node in nodes:
        body = node.read_text(encoding="utf-8", errors="replace")
        block = f"\n===== {rel(node)} =====\n{body.rstrip()}\n"
        if len(block) > budget:
            note = f"\n[... truncated at {max_chars} chars; read the rest of {rel(node)}]\n"
            keep = max(budget - len(note), 0)
            parts.append(block[:keep] + note)
            remaining = [rel(n) for n in nodes[nodes.index(node) + 1 :]]
            if remaining:
                parts.append("Also newest, not shown: " + ", ".join(remaining) + "\n")
            break
        parts.append(block)
        budget -= len(block)
    parts.append(footer)
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0] if args else os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    system_dir = args[1] if len(args) > 1 else DEFAULT_SYSTEM
    try:
        print(render(root.resolve(), system_dir))
    except Exception as exc:  # LOAD context is best-effort: never block a session start
        print(f"Session handoff unavailable ({exc.__class__.__name__}: {exc}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
