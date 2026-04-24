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

from tools.process_miner.aggregate import (  # noqa: E402
    aggregate_across_repos,
    cluster_title_to_repos,
    default_token,
)
from tools.process_miner.fleet import DEFAULT_FLEET_REPOS  # noqa: E402


def _fleet_vault_summary(per_repo_stats: dict) -> dict | None:
    """Roll up per-repo ``vault_health`` blobs into fleet-level metrics."""
    scores: list[int] = []
    nodes: list[int] = []
    gap_total = 0
    rankings: list[tuple[str, int]] = []
    gap_counts: dict[str, int] = {}
    for slug, stats in per_repo_stats.items():
        if not isinstance(stats, dict):
            continue
        vh = stats.get("vault_health")
        if not isinstance(vh, dict) or vh.get("error"):
            continue
        if "health_score" in vh:
            sc = int(vh["health_score"])
            scores.append(sc)
            rankings.append((slug, sc))
        if "node_count" in vh:
            nodes.append(int(vh["node_count"]))
        cg = vh.get("coverage_gaps") or []
        if isinstance(cg, list):
            gap_total += len(cg)
            for gap in cg:
                if isinstance(gap, str):
                    gap_counts[gap] = gap_counts.get(gap, 0) + 1
    if not scores:
        return None
    n = len(scores)
    rankings.sort(key=lambda item: (-item[1], item[0]))
    return {
        "repos_scored": n,
        "avg_health_score": round(sum(scores) / n, 2),
        "min_health_score": min(scores),
        "max_health_score": max(scores),
        "avg_node_count": round(sum(nodes) / len(nodes), 2) if nodes else None,
        "total_coverage_gap_hints": gap_total,
        "rankings": [{"repo": s, "health_score": sc} for s, sc in rankings],
        "coverage_gap_patterns": gap_counts,
    }


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
    if not repos and os.environ.get("MINING_USE_DEFAULT_FLEET", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        repos = list(DEFAULT_FLEET_REPOS)
        print("MINING_USE_DEFAULT_FLEET=1: using built-in agorokh fleet list (#70).")
    if not repos:
        print(
            "MINING_REPOS empty. Set comma-separated owner/repo list, or "
            "MINING_USE_DEFAULT_FLEET=1 for the template fleet (issue #70)."
        )
        return 0

    days, err = _parse_days_env()
    if err is not None or days is None:
        print(f"error: {err}", file=sys.stderr)
        return 1
    token = default_token()
    out_dir = Path(os.environ.get("MINING_OUT", "reports/cross_repo_mining"))
    out_dir.mkdir(parents=True, exist_ok=True)

    audit_vault = os.environ.get("MINING_AUDIT_VAULT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    semantic = os.environ.get("MINING_SEMANTIC_CLUSTER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if semantic:
        print("MINING_SEMANTIC_CLUSTER=1: using sentence-transformer embeddings (Part 2, #81).")

    result = aggregate_across_repos(repos, token, days=days, audit_vault=audit_vault)
    per_repo_stats = {k: v.stats for k, v in result.per_repo.items()}
    payload = {
        "universal": result.universal,
        "repos": list(result.per_repo.keys()),
        "per_repo_stats": per_repo_stats,
        "vault_audit_enabled": audit_vault,
        "semantic_clustering": semantic,
        "fleet_vault": _fleet_vault_summary(per_repo_stats),
    }
    summary_path = out_dir / "aggregate_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")
    print("Universal (S0) pattern keys:", ", ".join(result.universal) or "(none)")

    if os.environ.get("MINING_DISTILL", "").strip().lower() in ("1", "true", "yes"):
        from tools.process_miner.distill import (  # noqa: E402
            build_cluster_payloads_for_distillation,
            distill_universal_with_cache,
        )

        tr = cluster_title_to_repos(result.per_repo)
        distill_payload = build_cluster_payloads_for_distillation(
            result.universal,
            tr,
            result.per_repo,
        )
        if distill_payload:
            try:
                distill_out = distill_universal_with_cache(_REPO_ROOT, distill_payload)
                dpath = out_dir / "aggregate_distill.json"
                dpath.write_text(
                    json.dumps(distill_out, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                print(f"Wrote {dpath}")
            except Exception as exc:
                print(f"warning: MINING_DISTILL failed: {exc}", file=sys.stderr)
        else:
            print("MINING_DISTILL=1 but no universal cluster payloads; skipping distillation.")

    if os.environ.get("MINING_EMIT_LEARNED", "").strip().lower() in ("1", "true", "yes"):
        from tools.process_miner.emit import emit_cross_repo_learned  # noqa: E402

        emit_summary, n = emit_cross_repo_learned(
            result,
            _REPO_ROOT,
            agents_md_path=Path("AGENTS.md"),
        )
        print(emit_summary)
        print(
            f"emit_cross_repo: wrote {n} file(s) under "
            ".claude/rules/learned/ and .cursor/rules/learned/"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
