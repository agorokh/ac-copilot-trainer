#!/usr/bin/env python3
"""Merge ``.cache/session_debriefs/*.jsonl`` into the repo knowledge SQLite DB.

No GitHub token required. Safe when debrief files are missing (no-op).

See ``tools.process_miner.session_debrief_schema`` for the JSONL schema.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.repo_knowledge.session_debrief_ingest import (  # noqa: E402
    ingest_session_debriefs_from_disk,
)


def _positive_int_days(raw: str) -> int:
    v = int(raw)
    if v < 1:
        msg = "must be a positive integer"
        raise argparse.ArgumentTypeError(msg)
    return v


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".cache/repo_knowledge/knowledge.db"),
        help="SQLite path (default: .cache/repo_knowledge/knowledge.db)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing .cache/session_debriefs/ (default: cwd)",
    )
    parser.add_argument(
        "--days",
        type=_positive_int_days,
        default=14,
        help="Ingest records with ts within this many days (default: 14, minimum 1)",
    )
    args = parser.parse_args()
    applied, skipped = ingest_session_debriefs_from_disk(
        args.db.resolve(),
        args.repo_root.resolve(),
        max_age_days=args.days,
    )
    print(f"session_debrief_ingest: applied={applied} skipped_duplicate={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
