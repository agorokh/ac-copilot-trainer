"""Smoke tests for render + collect (no GitHub network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from tools.process_miner.collect import collect_pr_data
from tools.process_miner.render import render_report
from tools.process_miner.schemas import AnalysisResult


def test_render_report_writes_header(tmp_path: Path) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 8, tzinfo=UTC)
    result = AnalysisResult(
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
            "avg_comments_per_pr": 0.0,
            "ci_failure_count": 0,
        },
    )
    out = tmp_path / "r.md"
    render_report(result, "o/r", since, out, period_days=7, until=until)
    text = out.read_text(encoding="utf-8")
    assert "Process Improvement Miner Report" in text
    assert text.count("last 7 day(s)") == 1


def test_render_report_includes_bot_review_sections(tmp_path: Path) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 8, tzinfo=UTC)
    result = AnalysisResult(
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
            "avg_comments_per_pr": 0.0,
            "ci_failure_count": 0,
            "comment_author_type_breakdown": {"bot": 2, "human": 1},
            "per_bot_severity_counts": {"gemini": {"nit": 1}},
            "multi_bot_pr_count": 1,
            "bot_agreement_by_pr": [
                {
                    "pr_number": 7,
                    "distinct_bots": ["a", "b"],
                    "locations_with_multiple_bots": 1,
                    "bot_pair_co_occurrence": {"a|b": 1},
                }
            ],
        },
    )
    out = tmp_path / "bots.md"
    render_report(result, "o/r", since, out, period_days=7, until=until)
    text = out.read_text(encoding="utf-8")
    assert "Bot vs human review comments" in text
    assert "Per-bot comment severity" in text
    assert "Multi-bot agreement" in text
    assert "PRs in window with ≥2 bots" in text
    assert "Dominant author type" not in text  # no clusters in this minimal result


def test_collect_pr_data_minimal(tmp_path: Path) -> None:
    client = MagicMock()
    client.get_default_branch.return_value = "main"
    client.get_merged_prs.return_value = [
        {
            "number": 42,
            "title": "Example",
            "user": {"login": "alice", "type": "User"},
            "created_at": "2026-01-02T00:00:00Z",
            "merged_at": "2026-01-03T00:00:00Z",
            "body": "",
        }
    ]
    client.get_pr_files.return_value = []
    client.get_pr_review_comments.return_value = []
    client.get_pr_reviews.return_value = []
    client.get_pr_issue_comments.return_value = []
    client.get_pr_check_runs.return_value = {"check_runs": []}
    client.get_linked_issues.return_value = []

    since = datetime(2026, 1, 1, tzinfo=UTC)
    prs = collect_pr_data(
        client,
        "o",
        "r",
        since,
        max_prs=5,
        cache_dir=tmp_path / "cache",
        max_pages=2,
    )
    assert len(prs) == 1
    assert prs[0].number == 42
    client.get_merged_prs.assert_called_once()
    client.get_default_branch.assert_called_once_with("o", "r")
    client.get_pr_files.assert_called_once()
    client.get_pr_check_runs.assert_called_once()
    cc = client.get_pr_check_runs.call_args
    assert cc[0][0] == "o"
    assert cc[0][1] == "r"
    assert cc[0][2] == 42
    assert cc[1].get("pr_summary") is not None
