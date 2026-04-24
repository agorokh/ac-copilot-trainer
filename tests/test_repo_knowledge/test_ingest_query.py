"""SQLite ingest + query smoke tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment
from tools.process_miner.vault_audit import VaultAuditResult, VaultNode
from tools.repo_knowledge.ingest import ingest_analysis
from tools.repo_knowledge.query import (
    connect,
    query_ci_failures,
    query_decisions,
    query_file_patterns,
    query_review_history,
    query_similar_issues,
)
from tools.repo_knowledge.schema import apply_schema


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


def test_ingest_vault_audit_writes_health_and_replaces_nodes(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    res = _minimal_result()
    audit = VaultAuditResult(
        repo="o/r",
        vault_exists=True,
        tree_truncated=False,
        nodes=[
            VaultNode(
                path="docs/01_Vault/x.md",
                node_type="note",
                status="active",
                last_updated=datetime(2026, 1, 1, tzinfo=UTC),
                relates_to=[],
                frontmatter_ok=True,
            )
        ],
        health_score=55,
        freshness_score=0.5,
        depth_score=0.5,
        frontmatter_score=0.5,
        connectivity_score=0.5,
        coverage_score=0.5,
        coverage_gaps=[],
        broken_links=[],
        broken_links_total=0,
        save_compliant_prs=1,
        save_total_prs=2,
        save_rate=0.5,
        handoff_last_updated=None,
        last_pr_merged_at=None,
    )
    ingest_analysis(res, "o/r", db, vault_audit=audit)
    conn = connect(db)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM vault_health WHERE repo = ?", ("o/r",)).fetchone()[0]
            == 1
        )
        rows = conn.execute(
            "SELECT path, node_type FROM vault_nodes WHERE repo = ? ORDER BY path",
            ("o/r",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "docs/01_Vault/x.md"
        assert rows[0][1] == "note"
    finally:
        conn.close()

    audit2 = VaultAuditResult(
        repo="o/r",
        vault_exists=True,
        tree_truncated=False,
        nodes=[
            VaultNode(
                path="docs/01_Vault/y.md",
                node_type="decision",
                status="active",
                last_updated=None,
                relates_to=[],
                frontmatter_ok=True,
            ),
            VaultNode(
                path="docs/01_Vault/z.md",
                node_type="note",
                status="draft",
                last_updated=None,
                relates_to=[],
                frontmatter_ok=False,
            ),
        ],
        health_score=60,
        freshness_score=0.6,
        depth_score=0.6,
        frontmatter_score=0.6,
        connectivity_score=0.6,
        coverage_score=0.6,
        coverage_gaps=[],
        broken_links=[],
        broken_links_total=0,
        save_compliant_prs=0,
        save_total_prs=1,
        save_rate=0.0,
        handoff_last_updated=None,
        last_pr_merged_at=None,
    )
    ingest_analysis(res, "o/r", db, vault_audit=audit2)
    conn = connect(db)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM vault_health WHERE repo = ?", ("o/r",)).fetchone()[0]
            == 2
        )
        paths = [
            r[0]
            for r in conn.execute(
                "SELECT path FROM vault_nodes WHERE repo = ? ORDER BY path",
                ("o/r",),
            ).fetchall()
        ]
        assert paths == ["docs/01_Vault/y.md", "docs/01_Vault/z.md"]
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


def test_ingest_vault_preserves_bootstrap_decisions(tmp_path: Path) -> None:
    """Miner vault sync must not DELETE rows seeded by bootstrap_knowledge (rationale tag)."""
    db = tmp_path / "k.db"
    conn = sqlite3.connect(db)
    try:
        apply_schema(conn)
        conn.execute(
            """
            INSERT INTO decisions (
                vault_path, decision_text, rationale, affected_paths, created_at
            )
            VALUES (
                'docs/01_Vault/AcCopilotTrainer/00_System/invariants/x.md',
                'inv rule',
                'bootstrap_knowledge',
                NULL,
                '2020-01-01'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

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
    ingest_analysis(_minimal_result(), "o/r", db, repo_root=tmp_path)
    conn = connect(db)
    try:
        n_boot = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE rationale = 'bootstrap_knowledge'"
        ).fetchone()[0]
        assert n_boot == 1
        rows = query_decisions(conn, "pytest")
        assert len(rows) == 1
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
