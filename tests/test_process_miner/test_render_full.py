"""Broader ``render_report`` coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.render import render_report
from tools.process_miner.schemas import (
    AnalysisResult,
    CIStatus,
    CommentCluster,
    PRData,
    PRFile,
    ReviewComment,
)


def test_render_report_includes_optional_sections(tmp_path: Path) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 8, tzinfo=UTC)

    pr = PRData(
        number=1,
        title="PR",
        author="a",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        merged_at=datetime(2026, 1, 3, tzinfo=UTC),
        body="",
        files=[PRFile(path="src/x.py", additions=1, deletions=0)],
        review_comments=[
            ReviewComment(
                id="1",
                body="note",
                author="r",
                created_at=datetime.now(UTC),
                path="src/x.py",
                line=1,
                is_inline=True,
            )
        ],
        issue_comments=[],
        ci_status=CIStatus(
            conclusion="failure",
            status="completed",
            jobs=[{"name": "ci", "conclusion": "failure"}],
        ),
    )

    cluster = CommentCluster(
        cluster_id=0,
        title="alpha / beta",
        count=2,
        comments=pr.review_comments * 2,
        affected_files=["src/x.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=["note"],
    )

    result = AnalysisResult(
        prs=[pr],
        clusters=[cluster],
        ci_failures=[{"pr_number": 1, "pr_title": "PR", "failed_jobs": ["ci"]}],
        churned_files=[{"path": "src/x.py", "comment_count": 1}],
        stats={
            "pr_count": 1,
            "total_comments": 1,
            "total_files": 1,
            "total_additions": 1,
            "total_deletions": 0,
            "avg_comments_per_pr": 1.0,
            "ci_failure_count": 1,
            "comment_author_type_breakdown": {"human": 1},
            "per_bot_severity_counts": {"gemini": {"nit": 1}},
            "multi_bot_pr_count": 1,
            "bot_agreement_by_pr": [
                {
                    "pr_number": 1,
                    "distinct_bots": ["a", "b"],
                    "locations_with_multiple_bots": 1,
                    "bot_pair_co_occurrence": {"a|b": 2},
                }
            ],
        },
    )

    out = tmp_path / "full.md"
    render_report(result, "o/r", since, out, period_days=7, until=until)
    text = out.read_text(encoding="utf-8")
    assert "Recurring CI Failures" in text
    assert "Most Churned Files" in text
    assert "Appendix: All Comment Clusters" in text
    assert "review and issue thread comments" in text
    assert "excludes the PR body" in text
    assert "agreement locations" in text
    assert "**PR #1**" in text
    assert "bots: a, b" in text


def test_render_report_shows_cluster_dominant_bot_when_bot_dominated(tmp_path: Path) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 8, tzinfo=UTC)
    body = (
        "Please ensure every public function in this module has explicit type annotations "
        "so consumers can rely on static analysis."
    )
    bot_comments = [
        ReviewComment(
            id=str(i),
            body=body,
            author="gemini-code-assist",
            author_type="bot",
            bot_name="gemini",
            created_at=datetime.now(UTC),
            path="src/x.py",
            line=i,
            is_inline=True,
        )
        for i in range(3)
    ]
    cluster = CommentCluster(
        cluster_id=0,
        title="types / annotations",
        count=3,
        comments=bot_comments,
        affected_files=["src/x.py"],
        severity="maintainability",
        preventability="guideline",
        representative_examples=[body[:200]],
        dominant_author_type="bot",
        dominant_bot_name="gemini",
    )
    result = AnalysisResult(
        prs=[],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={
            "pr_count": 0,
            "total_comments": 0,
            "total_files": 0,
            "total_additions": 0,
            "total_deletions": 0,
            "avg_comments_per_pr": 0.0,
            "ci_failure_count": 0,
        },
    )
    out = tmp_path / "dom.md"
    render_report(result, "o/r", since, out, period_days=7, until=until)
    text = out.read_text(encoding="utf-8")
    assert "- **Dominant author type:** bot" in text
    assert "- **Dominant bot:** gemini" in text
