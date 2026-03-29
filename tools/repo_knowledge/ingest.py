"""Ingest process miner analysis into SQLite."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult
from tools.repo_knowledge.schema import apply_schema


def _parse_simple_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse leading ``---`` YAML-ish key: value lines; ignore complex YAML."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip().strip("\"'")
    return meta, body


def ingest_decisions_from_vault(conn: sqlite3.Connection, vault_root: Path, now: str) -> None:
    """Replace ``decisions`` rows from vault markdown (``type: decision``, non-template)."""
    if not vault_root.is_dir():
        return
    conn.execute("DELETE FROM decisions")
    for path in sorted(vault_root.rglob("*.md")):
        try:
            rel = path.relative_to(vault_root).as_posix()
        except ValueError:
            continue
        if "99_Templates/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = _parse_simple_frontmatter(text)
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


def ingest_analysis(
    result: AnalysisResult,
    repo: str,
    db_path: Path,
    *,
    repo_root: Path | None = None,
) -> None:
    """Upsert patterns, files, evidence, and CI rows from an analysis result."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)
        now = datetime.now(UTC).isoformat()
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
            cur = conn.execute(
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
                RETURNING id
                """,
                (title, cluster.severity, cluster.preventability, cluster.count, now, now),
            )
            row = cur.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("INSERT INTO patterns RETURNING id returned no row")
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

        conn.commit()
    finally:
        conn.close()
