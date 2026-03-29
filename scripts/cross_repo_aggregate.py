#!/usr/bin/env python3
"""Run cross-repo process miner aggregation (scheduled / workflow_dispatch)."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Repo root on PYTHONPATH when run as `python scripts/cross_repo_aggregate.py`
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.process_miner.aggregate import aggregate_across_repos, default_token  # noqa: E402


def _parse_days_env() -> tuple[int | None, str | None]:
    raw = os.environ.get("MINING_DAYS", "30").strip()
    try:
        d = float(raw)
    except ValueError:
        return None, f"MINING_DAYS must be a number, got {raw!r}"
    if not math.isfinite(d):
        return None, f"MINING_DAYS must be a finite number, got {raw!r}"
    if d < 0:
        return None, f"MINING_DAYS must be >= 0, got {raw!r}"
    try:
        return int(d), None
    except (ValueError, OverflowError):
        return None, f"MINING_DAYS out of range, got {raw!r}"


def main() -> int:
    raw = os.environ.get("MINING_REPOS", "").strip()
    repos = [r.strip() for r in raw.split(",") if r.strip()]
    if not repos:
        print("MINING_REPOS empty; set comma-separated owner/repo list (or repo variable).")
        return 0

    days, err = _parse_days_env()
    if err is not None or days is None:
        print(f"error: {err}", file=sys.stderr)
        return 1
    token = default_token()
    out_dir = Path(os.environ.get("MINING_OUT", "reports/cross_repo_mining"))
    out_dir.mkdir(parents=True, exist_ok=True)

    result = aggregate_across_repos(repos, token, days=days)
    payload = {
        "universal": result.universal,
        "repos": list(result.per_repo.keys()),
        "per_repo_stats": {k: v.stats for k, v in result.per_repo.items()},
    }
    summary_path = out_dir / "aggregate_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")
    print("Universal pattern keys (>=2 repos):", ", ".join(result.universal) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
