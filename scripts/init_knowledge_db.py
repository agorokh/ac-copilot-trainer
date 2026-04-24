#!/usr/bin/env python3
"""Create the local repo-knowledge SQLite database (idempotent).

After a fresh clone, `.cache/repo_knowledge/knowledge.db` does not exist; the MCP
server then has nothing useful to query. Running this script (or ``make
init-knowledge``) applies the canonical schema via ``apply_schema``.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Repo root on sys.path when run as `python scripts/init_knowledge_db.py` (Makefile).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _repo_root() -> Path:
    return _REPO_ROOT


def _db_path(root: Path) -> Path:
    return root / ".cache" / "repo_knowledge" / "knowledge.db"


def main(*, root: Path | None = None) -> int:
    repo = root if root is not None else _repo_root()
    db_path = _db_path(repo)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from tools.repo_knowledge.schema import apply_schema

    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
