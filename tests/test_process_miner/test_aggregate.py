"""Tests for cross-repo process miner aggregation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from tools.process_miner.aggregate import (
    aggregate_across_repos,
    best_cluster_for_title,
    best_emittable_cluster_for_title,
    find_cross_repo_patterns,
    find_domain_scope_titles,
    find_universal_scope_titles,
)
from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment


def _cluster(title: str) -> CommentCluster:
    return CommentCluster(
        cluster_id=0,
        title=title,
        count=2,
        comments=[],
        affected_files=["a.py"],
        severity="nit",
        preventability="guideline",
        representative_examples=[],
    )


def test_find_cross_repo_patterns_min_repos() -> None:
    r1 = AnalysisResult([], [_cluster("Lint noise")], [], [], {})
    r2 = AnalysisResult([], [_cluster("lint noise")], [], [], {})
    keys = find_cross_repo_patterns({"org/a": r1, "org/b": r2}, min_repos=2)
    assert keys == ["lint noise"]


def test_find_cross_repo_patterns_single_repo_ignored() -> None:
    r1 = AnalysisResult([], [_cluster("Only here")], [], [], {})
    keys = find_cross_repo_patterns({"org/a": r1}, min_repos=2)
    assert keys == []


def test_find_universal_scope_two_domains() -> None:
    title_repos = {
        "shared pattern": {"agorokh/template-repo", "agorokh/case_operations"},
    }
    slug_domain = {
        "agorokh/template-repo": "infra",
        "agorokh/case_operations": "legal",
    }
    assert find_universal_scope_titles(title_repos, slug_domain) == {"shared pattern"}


def test_find_universal_scope_three_repos() -> None:
    title_repos = {
        "wide": {"agorokh/a", "agorokh/b", "agorokh/c"},
    }
    slug_domain = {s: "infra" for s in title_repos["wide"]}
    assert find_universal_scope_titles(title_repos, slug_domain) == {"wide"}


def test_best_cluster_for_title_prefers_higher_distinct_pr_count() -> None:
    """Same comment count: more distinct PRs wins before repo slug tie-break."""
    c_low = CommentCluster(
        cluster_id=0,
        title="breadth",
        count=5,
        comments=[],
        affected_files=["a.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[],
        distinct_pr_count=1,
    )
    c_high = CommentCluster(
        cluster_id=1,
        title="breadth",
        count=5,
        comments=[],
        affected_files=["b.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[],
        distinct_pr_count=3,
    )
    per_repo = {
        "org/aaa": AnalysisResult([], [c_low], [], [], {}),
        "org/bbb": AnalysisResult([], [c_high], [], [], {}),
    }
    slug, cl = best_cluster_for_title(per_repo, "breadth")
    assert cl.distinct_pr_count == 3
    assert cl.affected_files == ["b.py"]
    assert slug == "org/bbb"


def test_best_cluster_for_title_tie_breaks_by_repo_slug_order() -> None:
    """Equal cluster counts and distinct PRs: lexicographically first repo slug wins."""
    c_a = CommentCluster(
        cluster_id=0,
        title="shared tie",
        count=4,
        comments=[],
        affected_files=["a.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[],
        distinct_pr_count=2,
    )
    c_z = CommentCluster(
        cluster_id=1,
        title="shared tie",
        count=4,
        comments=[],
        affected_files=["z.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[],
        distinct_pr_count=2,
    )
    per_repo = {
        "org/zzz": AnalysisResult([], [c_z], [], [], {}),
        "org/aaa": AnalysisResult([], [c_a], [], [], {}),
    }
    slug, cl = best_cluster_for_title(per_repo, "shared tie")
    assert slug == "org/aaa"
    assert cl.affected_files == ["a.py"]


def test_find_universal_scope_omits_unknown_domain_for_breadth() -> None:
    """Two repos with only one known domain must not become S0 via a None domain entry."""
    title_repos = {
        "pair": {"agorokh/template-repo", "unknown/orphan-repo"},
    }
    slug_domain = {
        "agorokh/template-repo": "infra",
        "unknown/orphan-repo": None,
    }
    assert find_universal_scope_titles(title_repos, slug_domain) == set()


def test_best_emittable_skips_clusters_failing_emit_prefilter() -> None:
    """Nit bar and volume gates exclude clusters before tie-break (cross_volume_ok=False)."""
    human = ReviewComment(
        id="1",
        body="Concrete review text so the cluster is not treated as empty boilerplate.",
        author="reviewer",
        author_type="human",
    )
    c_nit = CommentCluster(
        cluster_id=0,
        title="pick me",
        count=10,
        comments=[human],
        affected_files=["a.py"],
        severity="nit",
        preventability="guideline",
        representative_examples=[human.body],
        distinct_pr_count=2,
    )
    c_ok = CommentCluster(
        cluster_id=1,
        title="pick me",
        count=3,
        comments=[human],
        affected_files=["b.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[human.body],
        distinct_pr_count=2,
    )
    per_repo = {
        "org/heavy": AnalysisResult([], [c_nit], [], [], {}),
        "org/light": AnalysisResult([], [c_ok], [], [], {}),
    }
    picked = best_emittable_cluster_for_title(
        per_repo,
        "pick me",
        cross_volume_ok=False,
        min_occurrences=3,
        min_distinct_prs=2,
    )
    assert picked is not None
    slug, cl = picked
    assert slug == "org/light"
    assert cl.severity == "maintainability"


def test_find_domain_scope_titles_rejects_non_positive_min_repos() -> None:
    with pytest.raises(ValueError, match="min_repos must be >= 1"):
        find_domain_scope_titles({}, {}, set(), min_repos=0)


def test_find_domain_scope_titles_same_domain_pair() -> None:
    title_repos = {
        "legal only": {"agorokh/case_operations", "agorokh/court-fillings-processing"},
    }
    slug_domain = {
        "agorokh/case_operations": "legal",
        "agorokh/court-fillings-processing": "legal",
    }
    universal: set[str] = set()
    dom = find_domain_scope_titles(title_repos, slug_domain, universal, min_repos=2)
    assert dom == {"legal only": "legal"}


def test_find_cross_repo_patterns_rejects_non_positive_min_repos() -> None:
    r1 = AnalysisResult([], [_cluster("x")], [], [], {})
    with pytest.raises(ValueError, match="min_repos must be >= 1"):
        find_cross_repo_patterns({"org/a": r1}, min_repos=0)


def test_aggregate_across_repos_without_token() -> None:
    result = aggregate_across_repos(["org/repo"], None, days=1)
    assert result.per_repo["org/repo"].stats["pr_count"] == 0
    assert result.universal == []


def test_aggregate_across_repos_marks_invalid_slugs_without_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    result = aggregate_across_repos(["org/", "repo-only"], None, days=1)
    assert result.per_repo["org/"].stats["error"] == "InvalidSlug"
    assert result.per_repo["repo-only"].stats["error"] == "InvalidSlug"
    assert any("invalid repo slug" in r.getMessage() for r in caplog.records)


def test_aggregate_across_repos_marks_invalid_slugs_with_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    result = aggregate_across_repos(["org/", "repo-only"], "fake-token", days=1)
    assert result.per_repo["org/"].stats["error"] == "InvalidSlug"
    assert result.per_repo["repo-only"].stats["error"] == "InvalidSlug"
    assert any("invalid repo slug" in r.getMessage() for r in caplog.records)


def test_aggregate_across_repos_rejects_negative_days() -> None:
    with pytest.raises(ValueError, match="days must be >= 0"):
        aggregate_across_repos(["org/repo"], None, days=-1)


def test_aggregate_across_repos_logs_collect_failure(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    with patch(
        "tools.process_miner.aggregate.collect_pr_data",
        side_effect=RuntimeError("github down"),
    ):
        result = aggregate_across_repos(["org/r"], "fake-token", days=1)
    assert result.per_repo["org/r"].stats["pr_count"] == 0
    assert result.per_repo["org/r"].stats["error"] == "RuntimeError"
    assert "github down" in result.per_repo["org/r"].stats["error_message"]
    assert any("failed to collect" in r.getMessage() for r in caplog.records)


def test_aggregate_audit_vault_no_token_sets_vault_health() -> None:
    result = aggregate_across_repos(["org/repo"], None, days=1, audit_vault=True)
    vh = result.per_repo["org/repo"].stats.get("vault_health")
    assert vh == {"error": "NoGitHubToken"}


def test_aggregate_audit_vault_invalid_slug_sets_vault_health() -> None:
    result = aggregate_across_repos(["bad"], "fake-token", days=1, audit_vault=True)
    assert result.per_repo["bad"].stats["vault_health"] == {
        "error": "InvalidSlug",
        "error_message": "bad",
    }


def test_aggregate_audit_vault_collect_failure_sets_vault_health(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    with patch(
        "tools.process_miner.aggregate.collect_pr_data",
        side_effect=RuntimeError("github down"),
    ):
        result = aggregate_across_repos(["org/r"], "fake-token", days=1, audit_vault=True)
    assert result.per_repo["org/r"].stats["vault_health"] == {
        "error": "RuntimeError",
        "error_message": "github down",
    }


def test_aggregate_audit_vault_inner_failure_normalizes_vault_health_error() -> None:
    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        merged_at=None,
        body="",
    )
    mock_client = MagicMock()
    mock_client.get_default_branch.return_value = "main"
    with (
        patch("tools.process_miner.aggregate.GitHubClient", return_value=mock_client),
        patch("tools.process_miner.aggregate.collect_pr_data", return_value=[pr]),
        patch(
            "tools.process_miner.aggregate.collect_vault_audit",
            side_effect=ValueError("vault boom"),
        ),
    ):
        result = aggregate_across_repos(["org/r"], "fake-token", days=1, audit_vault=True)
    assert result.per_repo["org/r"].stats["vault_health"] == {
        "error": "ValueError",
        "error_message": "vault boom",
    }
