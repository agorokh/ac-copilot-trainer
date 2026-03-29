"""Tests for cross-repo process miner aggregation."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from tools.process_miner.aggregate import (
    aggregate_across_repos,
    find_cross_repo_patterns,
)
from tools.process_miner.schemas import AnalysisResult, CommentCluster


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
