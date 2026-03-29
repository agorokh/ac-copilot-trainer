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
        },
    )

    out = tmp_path / "full.md"
    render_report(result, "o/r", since, out, period_days=7, until=until)
    text = out.read_text(encoding="utf-8")
    assert "Recurring CI Failures" in text
    assert "Most Churned Files" in text
    assert "Appendix: All Comment Clusters" in text
