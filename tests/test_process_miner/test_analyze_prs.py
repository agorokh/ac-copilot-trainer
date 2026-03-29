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
