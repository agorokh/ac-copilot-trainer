"""Tests for report hook appendix."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.process_miner.emit import append_hook_suggestions_to_report
from tools.process_miner.schemas import AnalysisResult, CommentCluster, ReviewComment


def test_append_hook_suggestions_appends_section(tmp_path) -> None:
    c = CommentCluster(
        cluster_id=0,
        title="format / import",
        count=3,
        comments=[
            ReviewComment(
                id="1",
                body="run ruff format",
                author="r",
                created_at=datetime.now(UTC),
                path="src/a.py",
                line=1,
                pr_number=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="fix import order",
                author="r",
                created_at=datetime.now(UTC),
                path="src/b.py",
                line=2,
                pr_number=2,
                is_inline=True,
            ),
            ReviewComment(
                id="3",
                body="apply ruff fix",
                author="r",
                created_at=datetime.now(UTC),
                path="src/c.py",
                line=3,
                pr_number=3,
                is_inline=True,
            ),
        ],
        affected_files=["src/a.py"],
        severity="maintainability",
        preventability="automation",
        representative_examples=["run ruff format"],
        distinct_pr_count=3,
    )
    result = AnalysisResult(
        prs=[],
        clusters=[c],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    report = tmp_path / "out.md"
    report.write_text("# report\n", encoding="utf-8")
    append_hook_suggestions_to_report(result, report)
    text = report.read_text(encoding="utf-8")
    assert "Hook suggestions" in text
    _, section = text.split("Hook suggestions", maxsplit=1)
    assert section.strip()


def test_append_hook_suggestions_skips_single_pr_cluster(tmp_path) -> None:
    cluster = CommentCluster(
        cluster_id=0,
        title="format / import",
        count=3,
        comments=[
            ReviewComment(
                id="1",
                body="run ruff format",
                author="r",
                created_at=datetime.now(UTC),
                path="src/a.py",
                line=1,
                pr_number=99,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="fix import order",
                author="r",
                created_at=datetime.now(UTC),
                path="src/b.py",
                line=2,
                pr_number=99,
                is_inline=True,
            ),
            ReviewComment(
                id="3",
                body="apply ruff fix",
                author="r",
                created_at=datetime.now(UTC),
                path="src/c.py",
                line=3,
                pr_number=99,
                is_inline=True,
            ),
        ],
        affected_files=["src/a.py"],
        severity="maintainability",
        preventability="automation",
        representative_examples=["run ruff format"],
        distinct_pr_count=1,
    )
    result = AnalysisResult(
        prs=[],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    report = tmp_path / "out.md"
    report.write_text("# report\n", encoding="utf-8")
    append_hook_suggestions_to_report(result, report)
    assert report.read_text(encoding="utf-8") == "# report\n"
