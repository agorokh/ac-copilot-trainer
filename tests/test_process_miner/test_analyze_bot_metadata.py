"""Bot metadata helpers in ``analyze`` (no sklearn dependency)."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.process_miner.analyze import (
    _dominant_cluster_author_type,
    _dominant_cluster_bot_name,
    bot_agreement_summary_for_pr,
)
from tools.process_miner.schemas import PRData, ReviewComment


def test_dominant_cluster_bot_name_uses_bot_subset_only() -> None:
    """Majority is computed among bot comments; humans do not inflate the denominator."""
    comments = [
        ReviewComment(
            id="1",
            body="x",
            author="u1",
            author_type="bot",
            bot_name="alpha",
            created_at=datetime.now(UTC),
            path="f.py",
            line=1,
            is_inline=True,
        ),
        ReviewComment(
            id="2",
            body="y",
            author="u2",
            author_type="bot",
            bot_name="alpha",
            created_at=datetime.now(UTC),
            path="f.py",
            line=2,
            is_inline=True,
        ),
        ReviewComment(
            id="3",
            body="z",
            author="u3",
            author_type="bot",
            bot_name="beta",
            created_at=datetime.now(UTC),
            path="f.py",
            line=3,
            is_inline=True,
        ),
        ReviewComment(
            id="4",
            body="human",
            author="h",
            author_type="human",
            created_at=datetime.now(UTC),
            is_inline=False,
        ),
    ]
    # Among 3 bots: alpha=2 > 3/2 → dominant alpha. (Old logic used len(comments)=4 → no dominant.)
    assert _dominant_cluster_bot_name(comments) == "alpha"


def test_dominant_cluster_author_type_unknown_only() -> None:
    comments = [
        ReviewComment(
            id="1",
            body="a",
            author="?",
            author_type="unknown",
            created_at=datetime.now(UTC),
            is_inline=False,
        ),
        ReviewComment(
            id="2",
            body="b",
            author="?",
            author_type="unknown",
            created_at=datetime.now(UTC),
            is_inline=False,
        ),
    ]
    assert _dominant_cluster_author_type(comments) == "unknown"


def test_bot_agreement_distinct_lines_no_pair_co_occurrence() -> None:
    """Two bots on different lines: still multi-bot PR, but no location shares both."""
    pr = PRData(
        number=7,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="f.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="f.py",
                line=2,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    summary = bot_agreement_summary_for_pr(pr)
    assert summary is not None
    assert summary["locations_with_multiple_bots"] == 0
    assert summary["bot_pair_co_occurrence"] == {}
