"""Ingest process miner analysis into SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult
from tools.process_miner.simple_frontmatter import parse_simple_frontmatter
from tools.process_miner.vault_audit import VaultAuditResult
from tools.repo_knowledge.schema import apply_schema
from tools.repo_knowledge.session_debrief_ingest import (
    ingest_session_debrief_records,
    load_debrief_records,
    utc_now_iso_z,
)


def ingest_decisions_from_vault(conn: sqlite3.Connection, vault_root: Path, now: str) -> None:
    """Replace vault-sourced ``decisions`` rows (``type: decision``, non-template).

    Rows with ``rationale = 'bootstrap_knowledge'`` (from ``bootstrap_knowledge.py``) are kept
    so weekly miner ingest does not wipe invariant seed data loaded in CI before the miner runs.
    """
    if not vault_root.is_dir():
        return
    conn.execute(
        "DELETE FROM decisions WHERE IFNULL(rationale, '') != ?",
        ("bootstrap_knowledge",),
    )
    for path in sorted(vault_root.rglob("*.md")):
        try:
            rel = path.relative_to(vault_root).as_posix()
        except ValueError:
            continue
        if "99_Templates/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_simple_frontmatter(text)
        if meta.get("type") != "decision":
            continue
        dec_id = meta.get("id", "")
        if dec_id in ("ADR-XXXX", ""):
            continue
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = (m.group(1).strip() if m else path.stem)[:2000]
        conn.execute(
            """
            INSERT INTO decisions (
                vault_path, decision_text, rationale, affected_paths, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (rel, title, "", meta.get("area", ""), now),
        )


def ingest_vault_audit(
    conn: sqlite3.Connection, repo: str, audit: VaultAuditResult, now: str
) -> None:
    """Append a ``vault_health`` row and replace ``vault_nodes`` snapshot for ``repo``."""
    details = json.dumps(audit.to_stats_dict(), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO vault_health (
            repo, mined_at, health_score, freshness, depth, frontmatter_validity,
            connectivity, coverage, save_rate, save_compliant, save_total, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repo,
            now,
            audit.health_score,
            audit.freshness_score,
            audit.depth_score,
            audit.frontmatter_score,
            audit.connectivity_score,
            audit.coverage_score,
            audit.save_rate,
            audit.save_compliant_prs,
            audit.save_total_prs,
            details,
        ),
    )
    conn.execute("DELETE FROM vault_nodes WHERE repo = ?", (repo,))
    for n in audit.nodes:
        conn.execute(
            """
            INSERT INTO vault_nodes (repo, path, node_type, status, last_updated, frontmatter_ok)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                repo,
                n.path,
                n.node_type,
                n.status,
                n.last_updated.isoformat() if n.last_updated else None,
                1 if n.frontmatter_ok else 0,
            ),
        )


def ingest_analysis(
    result: AnalysisResult,
    repo: str,
    db_path: Path,
    *,
    repo_root: Path | None = None,
    ingest_session_debrief: bool = False,
    debrief_max_age_days: int = 14,
    vault_audit: VaultAuditResult | None = None,
) -> tuple[int, int]:
    """Upsert patterns, files, evidence, and CI rows from an analysis result.

    Returns ``(session_debrief_applied, session_debrief_skipped_duplicate)``. Both are zero when
    ``ingest_session_debrief`` is false or ``repo_root`` is unset.
    """
    debrief_applied = 0
    debrief_skipped = 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)
        now = utc_now_iso_z()
        conn.execute(
            "INSERT INTO ingest_meta (key, value) VALUES ('last_repo', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (repo,),
        )

        for pr in result.prs:
            for comment in pr.review_comments:
                if not comment.path:
                    continue
                conn.execute(
                    """
                    INSERT INTO files (path, review_comment_count, ci_failure_count)
                    VALUES (?, 1, 0)
                    ON CONFLICT(path) DO UPDATE SET
                      review_comment_count = review_comment_count + 1
                    """,
                    (comment.path,),
                )

        for cluster in result.clusters:
            title = cluster.title[:2000]
            conn.execute(
                """
                INSERT INTO patterns (
                    pattern_text, severity, preventability, frequency, first_seen, last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_text) DO UPDATE SET
                    frequency = patterns.frequency + excluded.frequency,
                    last_seen = excluded.last_seen,
                    severity = excluded.severity,
                    preventability = excluded.preventability
                """,
                (title, cluster.severity, cluster.preventability, cluster.count, now, now),
            )
            row = conn.execute(
                "SELECT id FROM patterns WHERE pattern_text = ?",
                (title,),
            ).fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("pattern upsert did not yield a row id")
            pattern_id = int(row[0])

            file_counts: dict[str, int] = {}
            for c in cluster.comments:
                if c.path:
                    file_counts[c.path] = file_counts.get(c.path, 0) + 1

            for fp, occ in file_counts.items():
                conn.execute(
                    """
                    INSERT INTO file_patterns (file_path, pattern_id, occurrence_count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(file_path, pattern_id) DO UPDATE SET
                        occurrence_count = file_patterns.occurrence_count
                            + excluded.occurrence_count
                    """,
                    (fp, pattern_id, occ),
                )

            for c in cluster.comments:
                conn.execute(
                    """
                    INSERT INTO pattern_evidence (
                        pattern_id,
                        pr_number,
                        comment_author,
                        comment_body,
                        file_path,
                        line_number,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pattern_id,
                        c.pr_number,
                        c.author,
                        c.body[:8000],
                        c.path,
                        c.line,
                        c.created_at.isoformat() if c.created_at else now,
                    ),
                )

        for failure in result.ci_failures:
            jobs = failure.get("failed_jobs") or []
            job_name = ", ".join(str(j) for j in jobs[:5]) if jobs else "unknown"
            conn.execute(
                """
                INSERT INTO ci_failures (
                    pr_number,
                    job_name,
                    failure_category,
                    root_cause,
                    affected_files,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(failure.get("pr_number", 0)),
                    job_name,
                    "ci",
                    str(failure.get("pr_title", ""))[:2000],
                    "",
                    now,
                ),
            )

        if repo_root is not None:
            vault = repo_root / "docs" / "01_Vault"
            ingest_decisions_from_vault(conn, vault, now)

        if vault_audit is not None:
            ingest_vault_audit(conn, repo, vault_audit, now)

        if ingest_session_debrief and repo_root is not None:
            debrief_dir = repo_root / ".cache" / "session_debriefs"
            debrief_recs = load_debrief_records(debrief_dir, max_age_days=debrief_max_age_days)
            debrief_applied, debrief_skipped = ingest_session_debrief_records(
                conn, repo_root, debrief_recs, now_iso=now
            )

        conn.commit()
    finally:
        conn.close()
    return debrief_applied, debrief_skipped
