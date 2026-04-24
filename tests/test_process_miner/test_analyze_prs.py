"""``analyze_prs`` integration (requires ``[mining]``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tools.process_miner.analyze import analyze_prs
from tools.process_miner.schemas import PRData, ReviewComment

pytest.importorskip("sklearn")


def test_analyze_prs_empty() -> None:
    result = analyze_prs([])
    assert result.stats["pr_count"] == 0
    assert result.clusters == []
    audit = result.stats["noise_filter_post_cluster_audit"]
    assert audit["near_duplicate_merges"] == []
    assert audit["dropped_title_bot_chrome"] == []


def test_analyze_prs_includes_bot_metadata_stats() -> None:
    pr = PRData(
        number=99,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="security issue with injection risk in this handler",
                author="coderabbitai",
                author_type="bot",
                bot_name="coderabbit",
                path="src/x.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="consider adding a type hint here for clarity",
                author="gemini-code-assist",
                author_type="bot",
                bot_name="gemini",
                path="src/x.py",
                line=2,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    result = analyze_prs([pr])
    assert result.stats["comment_author_type_breakdown"]["bot"] == 2
    assert result.stats["multi_bot_pr_count"] == 1
    assert len(result.stats["bot_agreement_by_pr"]) == 1
    sev = result.stats["per_bot_severity_counts"]
    assert isinstance(sev, dict)
    assert "coderabbit" in sev and "gemini" in sev
    row = result.stats["bot_agreement_by_pr"][0]
    assert isinstance(row, dict)
    assert row["pr_number"] == 99
    assert row["locations_with_multiple_bots"] == 0
    assert row["inline_or_thread_locations"] == 2
    pairs = row.get("bot_pair_co_occurrence") or {}
    assert isinstance(pairs, dict)
    assert pairs == {}


def test_analyze_prs_per_bot_severity_and_agreement_pair_same_line() -> None:
    pr = PRData(
        number=100,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="SQL injection risk in this query path",
                author="coderabbitai",
                author_type="bot",
                bot_name="coderabbit",
                path="src/x.py",
                line=5,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="optional rename for clarity",
                author="gemini-code-assist",
                author_type="bot",
                bot_name="gemini",
                path="src/x.py",
                line=5,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    result = analyze_prs([pr])
    sev = result.stats["per_bot_severity_counts"]
    assert isinstance(sev, dict)
    assert sev["coderabbit"].get("security", 0) >= 1
    assert sev["gemini"].get("nit", 0) >= 1
    row = result.stats["bot_agreement_by_pr"][0]
    assert row["pr_number"] == 100
    assert row["distinct_bots"] == ["coderabbit", "gemini"]
    assert row["inline_or_thread_locations"] == 1
    assert row["locations_with_multiple_bots"] == 1
    pairs = row["bot_pair_co_occurrence"]
    assert pairs.get("coderabbit|gemini") == 1


def test_analyze_prs_single_pr_counts_comments() -> None:
    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="long enough comment body about types and hints",
                author="r",
                created_at=datetime.now(UTC),
                path="src/x.py",
                line=1,
                is_inline=True,
            )
        ],
        issue_comments=[
            ReviewComment(
                id="2",
                body="another long enough comment about types and hints",
                author="r",
                created_at=datetime.now(UTC),
                is_inline=False,
            )
        ],
    )
    result = analyze_prs([pr])
    assert result.stats["pr_count"] == 1
    assert result.stats["total_comments"] == 2


def test_analyze_prs_default_clustering_forms_cluster() -> None:
    body = (
        "Please ensure every public function in this module has explicit type annotations "
        "so consumers can rely on static analysis."
    )
    pr = PRData(
        number=2,
        title="t2",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id=str(i),
                body=body,
                author="r",
                created_at=datetime.now(UTC),
                path="src/x.py",
                line=i,
                is_inline=True,
            )
            for i in range(3)
        ],
        issue_comments=[],
    )
    result = analyze_prs([pr])
    assert result.clusters
    assert max(c.count for c in result.clusters) >= 3
    for c in result.clusters:
        if c.dominant_author_type != "bot":
            assert c.dominant_bot_name is None
