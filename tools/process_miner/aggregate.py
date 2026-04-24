"""Cross-repository aggregation for process miner (universal pattern candidates)."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.process_miner.analyze import analyze_prs
from tools.process_miner.collect import collect_pr_data
from tools.process_miner.fleet import domain_for_repo
from tools.process_miner.github_client import GitHubClient
from tools.process_miner.noise_filter import cluster_looks_like_boilerplate
from tools.process_miner.schemas import AnalysisResult, CommentCluster
from tools.process_miner.vault_audit import collect_vault_audit, vault_audit_json_for_aggregate

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
            "comment_author_type_breakdown": {},
            "per_bot_severity_counts": {},
            "multi_bot_pr_count": 0,
            "bot_agreement_by_pr": [],
            "noise_filter_post_cluster_audit": {
                "near_duplicate_merges": [],
                "dropped_title_bot_chrome": [],
            },
        },
    )


def cluster_title_to_repos(per_repo: Mapping[str, AnalysisResult]) -> dict[str, set[str]]:
    """Map normalized cluster title → repo slugs that emitted that title."""
    title_repos: dict[str, set[str]] = defaultdict(set)
    for repo_slug, result in per_repo.items():
        for cluster in result.clusters:
            key = cluster.title.strip().lower()
            if key:
                title_repos[key].add(repo_slug)
    return {k: set(v) for k, v in title_repos.items()}


def find_cross_repo_patterns(
    per_repo: Mapping[str, AnalysisResult],
    *,
    min_repos: int = 2,
) -> list[str]:
    """Return normalized cluster titles that appear in at least ``min_repos`` repositories.

    Fleet aggregation uses ``find_universal_scope_titles`` / ``find_domain_scope_titles`` instead;
    this helper remains for tests and ad-hoc scripts that only need a repo-count title list.
    """
    if min_repos < 1:
        raise ValueError("min_repos must be >= 1")
    title_repos = cluster_title_to_repos(per_repo)
    return sorted(title for title, repos in title_repos.items() if len(repos) >= min_repos)


def find_universal_scope_titles(
    title_repos: Mapping[str, set[str]],
    slug_domain: Mapping[str, str | None],
) -> set[str]:
    """S0 candidates: ≥3 repos, or ≥2 distinct *known* domains (#70)."""
    universal: set[str] = set()
    for title, repos in title_repos.items():
        if len(repos) >= 3:
            universal.add(title)
            continue
        # Unknown repos: get() is None → walrus falsy → excluded (never counts as a domain).
        doms = {d for r in repos if (d := slug_domain.get(r)) is not None and d != ""}
        if len(doms) >= 2:
            universal.add(title)
    return universal


def find_domain_scope_titles(
    title_repos: Mapping[str, set[str]],
    slug_domain: Mapping[str, str | None],
    universal: set[str],
    *,
    min_repos: int = 2,
) -> dict[str, str]:
    """S2 candidates: title hits ≥min_repos repos within the same known domain; not universal."""
    if min_repos < 1:
        raise ValueError("min_repos must be >= 1")
    out: dict[str, str] = {}
    for title, repos in title_repos.items():
        if title in universal:
            continue
        by_dom: dict[str, set[str]] = defaultdict(set)
        for r in repos:
            d = slug_domain.get(r)
            if d:
                by_dom[d].add(r)
        for dom in sorted(by_dom.keys()):
            if len(by_dom[dom]) >= min_repos:
                out[title] = dom
                break
    return out


def emit_prefilter_skip_reason(
    cl: CommentCluster,
    *,
    cross_volume_ok: bool,
    min_occurrences: int,
    min_distinct_prs: int,
) -> str | None:
    """Return emit skip bucket if ``cl`` should not write artifacts, else ``None``.

    Must stay aligned with :func:`tools.process_miner.emit.emit_learned_artifacts` counters.
    """
    if not cross_volume_ok:
        if cl.count < min_occurrences:
            return "small"
        if cl.distinct_pr_count < min_distinct_prs:
            return "pr"
    if cl.severity == "nit" and (cl.count < 5 or cl.distinct_pr_count < 3):
        return "nit"
    if cluster_looks_like_boilerplate(cl):
        return "boiler"
    return None


def cluster_passes_emit_prefilter(
    cl: CommentCluster,
    *,
    cross_volume_ok: bool,
    min_occurrences: int,
    min_distinct_prs: int,
) -> bool:
    """True if ``cl`` passes the same volume / nit / boilerplate gates as rule emission."""
    return (
        emit_prefilter_skip_reason(
            cl,
            cross_volume_ok=cross_volume_ok,
            min_occurrences=min_occurrences,
            min_distinct_prs=min_distinct_prs,
        )
        is None
    )


def _clusters_for_normalized_title(
    per_repo: Mapping[str, AnalysisResult],
    title_key: str,
) -> Iterable[tuple[str, CommentCluster]]:
    for slug, res in sorted(per_repo.items()):
        for cl in res.clusters:
            if cl.title.strip().lower() == title_key:
                yield slug, cl


def _pick_best_cluster_by_volume(
    pairs: Iterable[tuple[str, CommentCluster]],
    *,
    predicate: Callable[[CommentCluster], bool] | None = None,
) -> tuple[str, CommentCluster] | None:
    """Prefer higher ``count``, then ``distinct_pr_count``, then lexicographic ``slug``."""
    best_key: tuple[int, int, str] | None = None
    best_pair: tuple[str, CommentCluster] | None = None
    for slug, cl in pairs:
        if predicate is not None and not predicate(cl):
            continue
        key = (-cl.count, -cl.distinct_pr_count, slug)
        if best_key is None or key < best_key:
            best_key = key
            best_pair = (slug, cl)
    return best_pair


def best_cluster_for_title(
    per_repo: Mapping[str, AnalysisResult],
    title_key: str,
) -> tuple[str, CommentCluster] | None:
    """Pick the richest cluster (by comment count, then distinct PRs) for a normalized title.

    Tie-break: lexicographically smallest repo slug (iterate ``sorted(per_repo)``).
    """
    return _pick_best_cluster_by_volume(_clusters_for_normalized_title(per_repo, title_key))


def best_emittable_cluster_for_title(
    per_repo: Mapping[str, AnalysisResult],
    title_key: str,
    *,
    cross_volume_ok: bool,
    min_occurrences: int = 3,
    min_distinct_prs: int = 2,
) -> tuple[str, CommentCluster] | None:
    """Like ``best_cluster_for_title`` but only clusters that pass emit preflight (S0/S2 path)."""

    def _ok(cl: CommentCluster) -> bool:
        return cluster_passes_emit_prefilter(
            cl,
            cross_volume_ok=cross_volume_ok,
            min_occurrences=min_occurrences,
            min_distinct_prs=min_distinct_prs,
        )

    return _pick_best_cluster_by_volume(
        _clusters_for_normalized_title(per_repo, title_key),
        predicate=_ok,
    )


def aggregate_across_repos(
    repos: list[str],
    token: str | None,
    days: int = 30,
    *,
    max_prs: int = 50,
    max_pages: int = 20,
    cache_dir: str | None = None,
    audit_vault: bool = False,
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
            if audit_vault:
                bad.stats["vault_health"] = {"error": "InvalidSlug", "error_message": slug}
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
                analyzed = analyze_prs(prs)
                if audit_vault:
                    try:
                        br = client.get_default_branch(owner, name)
                        va = collect_vault_audit(
                            client,
                            owner,
                            name,
                            branch=br,
                            prs=analyzed.prs,
                            clusters=analyzed.clusters,
                        )
                        vh = vault_audit_json_for_aggregate(va)
                        analyzed.stats = {**analyzed.stats, "vault_health": vh}
                    except Exception as exc:
                        logger.warning(
                            "aggregate: vault audit failed for %s: %s",
                            slug,
                            exc,
                            exc_info=True,
                        )
                        analyzed.stats = {
                            **analyzed.stats,
                            "vault_health": {
                                "error": exc.__class__.__name__,
                                "error_message": str(exc),
                            },
                        }
                per_repo[slug] = analyzed
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
                if audit_vault:
                    empty.stats["vault_health"] = {
                        "error": exc.__class__.__name__,
                        "error_message": str(exc),
                    }
                per_repo[slug] = empty
    else:
        for slug in valid_slugs:
            er = _empty_result()
            if audit_vault:
                er.stats = {
                    **er.stats,
                    "vault_health": {"error": "NoGitHubToken"},
                }
            per_repo[slug] = er

    title_repos = cluster_title_to_repos(per_repo)
    slug_domain = {s: domain_for_repo(s) for s in per_repo}
    universal_sorted = sorted(find_universal_scope_titles(title_repos, slug_domain))
    return AggregateResult(universal=universal_sorted, per_repo=per_repo)


def default_token() -> str | None:
    """Return GitHub token from environment (optional)."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
