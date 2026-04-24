#!/usr/bin/env python3
"""Print a short summary of top repo-knowledge patterns for SessionStart hooks.

Exits 0 quickly when the DB is missing or empty. Intended to stay well under ~2s.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return _REPO_ROOT


def _db_path(root: Path) -> Path:
    return root / ".cache" / "repo_knowledge" / "knowledge.db"


def main() -> int:
    root = _repo_root()
    db = _db_path(root)
    if not db.is_file():
        print("(repo knowledge) No DB yet — run: make init-knowledge && make bootstrap-knowledge")
        return 0

    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"(repo knowledge) open failed: {e}", file=sys.stderr)
        return 0
    try:
        rows = conn.execute(
            """
            SELECT pattern_text, frequency
            FROM patterns
            ORDER BY frequency DESC, LENGTH(pattern_text) ASC
            LIMIT 5
            """
        ).fetchall()
    except sqlite3.Error as e:
        print(f"(repo knowledge) query failed: {e}", file=sys.stderr)
        return 0
    finally:
        conn.close()

    if not rows:
        print("(repo knowledge) DB empty — run: make bootstrap-knowledge")
        return 0

    print("--- Top repo-knowledge patterns (see .cache/repo_knowledge/knowledge.db) ---")
    for i, (text, freq) in enumerate(rows, 1):
        snippet = (text or "").replace("\n", " ").strip()
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        print(f"  {i}. [{freq}] {snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
