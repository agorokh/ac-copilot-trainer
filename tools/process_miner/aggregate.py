"""Cross-repository aggregation for process miner (universal pattern candidates)."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.process_miner.analyze import analyze_prs
from tools.process_miner.collect import collect_pr_data
from tools.process_miner.github_client import GitHubClient
from tools.process_miner.schemas import AnalysisResult

logger = logging.getLogger(__name__)


def _valid_repo_slug(slug: str) -> bool:
    parts = slug.split("/")
    if len(parts) != 2:
        return False
    owner, name = parts
    return bool(owner.strip() and name.strip())


@dataclass
class AggregateResult:
    """Per-repo analysis plus cross-repo pattern keys."""

    universal: list[str] = field(default_factory=list)
    per_repo: dict[str, AnalysisResult] = field(default_factory=dict)


def _empty_result() -> AnalysisResult:
    return AnalysisResult(
        prs=[],
        clusters=[],
        ci_failures=[],
        churned_files=[],
        stats={
            "pr_count": 0,
            "total_comments": 0,
            "total_files": 0,
            "total_additions": 0,
            "total_deletions": 0,
            "avg_comments_per_pr": 0,
            "ci_failure_count": 0,
        },
    )


def find_cross_repo_patterns(
    per_repo: Mapping[str, AnalysisResult],
    *,
    min_repos: int = 2,
) -> list[str]:
    """Return normalized cluster titles that appear in at least ``min_repos`` repositories."""
    if min_repos < 1:
        raise ValueError("min_repos must be >= 1")
    title_repos: dict[str, set[str]] = defaultdict(set)
    for repo_slug, result in per_repo.items():
        for cluster in result.clusters:
            key = cluster.title.strip().lower()
            if key:
                title_repos[key].add(repo_slug)
    return sorted(title for title, repos in title_repos.items() if len(repos) >= min_repos)


def aggregate_across_repos(
    repos: list[str],
    token: str | None,
    days: int = 30,
    *,
    max_prs: int = 50,
    max_pages: int = 20,
    cache_dir: str | None = None,
) -> AggregateResult:
    """Collect + analyze each repo, then derive cross-repo pattern keys.

    When ``token`` is missing, each repo gets an empty :class:`AnalysisResult` (stdlib-only
    offline path for CI smoke tests).
    """
    if days < 0:
        raise ValueError("days must be >= 0")

    per_repo: dict[str, AnalysisResult] = {}
    since = datetime.now(UTC) - timedelta(days=days)

    valid_slugs: list[str] = []
    for slug in repos:
        if not _valid_repo_slug(slug):
            logger.warning("aggregate: invalid repo slug %r (expected owner/repo)", slug)
            bad = _empty_result()
            bad.stats = {
                **bad.stats,
                "error": "InvalidSlug",
                "error_message": slug,
            }
            per_repo[slug] = bad
        else:
            valid_slugs.append(slug)

    if token:
        client = GitHubClient(token=token)
        cdir = Path(cache_dir) if cache_dir else Path(".cache/process_miner_aggregate")

        for slug in valid_slugs:
            owner, name = slug.split("/", 1)
            try:
                prs = collect_pr_data(
                    client,
                    owner,
                    name,
                    since,
                    max_prs=max_prs,
                    cache_dir=cdir,
                    max_pages=max_pages,
                )
                per_repo[slug] = analyze_prs(prs)
            except Exception as exc:
                logger.warning(
                    "aggregate: failed to collect/analyze %s",
                    slug,
                    exc_info=True,
                )
                empty = _empty_result()
                empty.stats = {
                    **empty.stats,
                    "error": exc.__class__.__name__,
                    "error_message": str(exc),
                }
                per_repo[slug] = empty
    else:
        for slug in valid_slugs:
            per_repo[slug] = _empty_result()

    universal = find_cross_repo_patterns(per_repo, min_repos=2)
    return AggregateResult(universal=universal, per_repo=per_repo)


def default_token() -> str | None:
    """Return GitHub token from environment (optional)."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
