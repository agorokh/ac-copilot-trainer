"""SQLite ingest + query smoke tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment
from tools.repo_knowledge.ingest import ingest_analysis
from tools.repo_knowledge.query import (
    connect,
    query_ci_failures,
    query_decisions,
    query_file_patterns,
    query_review_history,
    query_similar_issues,
)


def _minimal_result() -> AnalysisResult:
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
                body="add types please",
                author="r",
                created_at=datetime.now(UTC),
                path="src/x.py",
                line=1,
                pr_number=1,
                is_inline=True,
            )
        ],
        issue_comments=[],
    )
    cluster = CommentCluster(
        cluster_id=0,
        title="types / hints",
        count=3,
        comments=pr.review_comments * 3,
        affected_files=["src/x.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=["add types please"],
    )
    return AnalysisResult(
        prs=[pr],
        clusters=[cluster],
        ci_failures=[{"pr_number": 1, "pr_title": "t", "failed_jobs": ["ci-fast"]}],
        churned_files=[{"path": "src/x.py", "comment_count": 3}],
        stats={"pr_count": 1},
    )


def test_ingest_twice_merges_pattern_row(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    res = _minimal_result()
    ingest_analysis(res, "o/r", db)
    ingest_analysis(res, "o/r", db)
    conn = connect(db)
    try:
        n_patterns, total_freq = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(frequency), 0) FROM patterns"
        ).fetchone()
        assert n_patterns == 1
        assert total_freq == 6
    finally:
        conn.close()


def test_connect_initializes_schema_without_ingest(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    conn = connect(db)
    try:
        assert query_decisions(conn, "any") == []
    finally:
        conn.close()


def test_ingest_and_query_file_patterns(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    ingest_analysis(_minimal_result(), "o/r", db)
    conn = connect(db)
    try:
        rows = query_file_patterns(conn, "src/x.py")
        assert rows
        assert "pattern_text" in rows[0]
    finally:
        conn.close()


def test_query_helpers_after_ingest(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    ingest_analysis(_minimal_result(), "o/r", db)
    conn = connect(db)
    try:
        assert query_review_history(conn, "src/*.py")
        assert query_ci_failures(conn, "ci")
        assert query_decisions(conn, "__no_decision_match__") == []
    finally:
        conn.close()


def test_query_ci_failures_escapes_like_metacharacters(tmp_path: Path) -> None:
    """Underscores in the needle must be literal, not LIKE single-char wildcards."""
    db = tmp_path / "k.db"
    conn = connect(db)
    try:
        conn.execute(
            """
            INSERT INTO ci_failures (
                pr_number, job_name, failure_category, root_cause, affected_files, created_at
            )
            VALUES (1, 'ci-fast', 'x', '', '', '2020-01-01')
            """
        )
        conn.commit()
        assert query_ci_failures(conn, "ci_fast") == []
        conn.execute(
            """
            INSERT INTO ci_failures (
                pr_number, job_name, failure_category, root_cause, affected_files, created_at
            )
            VALUES (2, 'ci_fast', 'x', '', '', '2020-01-02')
            """
        )
        conn.commit()
        rows = query_ci_failures(conn, "ci_fast")
        assert len(rows) == 1
        assert rows[0]["job_name"] == "ci_fast"
    finally:
        conn.close()


def test_ingest_syncs_decisions_from_vault(tmp_path: Path) -> None:
    vault = tmp_path / "docs" / "01_Vault" / "Decisions"
    vault.mkdir(parents=True)
    (vault / "adr-001.md").write_text(
        """---
type: decision
status: active
id: ADR-001
area: testing
---

# Use pytest for unit tests

Body here.
""",
        encoding="utf-8",
    )
    db = tmp_path / "k.db"
    ingest_analysis(_minimal_result(), "o/r", db, repo_root=tmp_path)
    conn = connect(db)
    try:
        rows = query_decisions(conn, "pytest")
        assert len(rows) == 1
        assert rows[0]["vault_path"].endswith("adr-001.md")
    finally:
        conn.close()


def test_query_similar_issues_handles_tokens(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    ingest_analysis(_minimal_result(), "o/r", db)
    conn = connect(db)
    try:
        rows = query_similar_issues(conn, "types hints")
        assert isinstance(rows, list)
        assert rows
        kinds = {r.get("kind") for r in rows}
        assert "pattern" in kinds or "evidence" in kinds
        assert any("type" in str(r.get("text", "")).lower() for r in rows)
    finally:
        conn.close()
