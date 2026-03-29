"""Query helpers for the knowledge SQLite database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.repo_knowledge.schema import apply_schema


def _like_escape(s: str) -> str:
    """Escape ``%``, ``_``, and ``\\`` for SQL ``LIKE ... ESCAPE '\\'``."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _glob_to_like(pattern: str) -> str:
    """Turn ``*`` / ``**`` into SQL wildcards; treat underscores literally."""
    p = _like_escape(pattern)
    return p.replace("**", "%").replace("*", "%")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the DB, apply schema, and return a connection.

    Caller must ``close()`` the connection (or use a context manager) when done.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    return conn


def query_file_patterns(conn: sqlite3.Connection, file_path: str) -> list[dict[str, object]]:
    """Match patterns tied to a path via exact path or bidirectional ``instr`` substring checks.

    ``instr`` avoids SQL ``LIKE`` underscore wildcards while still finding related rows when
    either the stored path or the query argument is a substring of the other.
    """
    rows = conn.execute(
        """
        SELECT
            p.pattern_text,
            p.severity,
            p.preventability,
            fp.occurrence_count,
            fp.file_path AS matched_path
        FROM file_patterns fp
        JOIN patterns p ON p.id = fp.pattern_id
        WHERE
            fp.file_path = ?
            OR (
                length(?) > 0
                AND length(fp.file_path) > 0
                AND instr(?, fp.file_path) > 0
            )
            OR (
                length(?) > 0
                AND length(fp.file_path) > 0
                AND instr(fp.file_path, ?) > 0
            )
        ORDER BY fp.occurrence_count DESC
        LIMIT 50
        """,
        (file_path, file_path, file_path, file_path, file_path),
    ).fetchall()
    return [dict(r) for r in rows]


def query_review_history(conn: sqlite3.Connection, glob_pattern: str) -> list[dict[str, object]]:
    """Match file paths with a simple glob: ``*`` / ``**`` become SQL wildcards.

    User input is escaped for literal ``%`` / ``_`` / ``\\``, then matched with
    ``LIKE ... ESCAPE '\\'`` (contrast with ``query_file_patterns``, which uses ``instr``).
    """
    like = _glob_to_like(glob_pattern)
    rows = conn.execute(
        """
        SELECT pe.pr_number, pe.comment_author, pe.comment_body, pe.file_path, pe.created_at
        FROM pattern_evidence pe
        WHERE pe.file_path LIKE ? ESCAPE '\\'
        ORDER BY pe.created_at DESC
        LIMIT 100
        """,
        (like,),
    ).fetchall()
    return [dict(r) for r in rows]


def query_ci_failures(conn: sqlite3.Connection, module: str) -> list[dict[str, object]]:
    """Match CI rows by substring on job name / category / ``affected_files``.

    Ingest often stores an empty ``affected_files`` string when the miner has no paths; the
    ``job_name`` and ``failure_category`` columns still participate in the OR clause.
    """
    like = f"%{_like_escape(module)}%"
    rows = conn.execute(
        """
        SELECT pr_number, job_name, failure_category, root_cause, affected_files, created_at
        FROM ci_failures
        WHERE affected_files LIKE ? ESCAPE '\\'
           OR job_name LIKE ? ESCAPE '\\'
           OR failure_category LIKE ? ESCAPE '\\'
        ORDER BY id DESC
        LIMIT 50
        """,
        (like, like, like),
    ).fetchall()
    return [dict(r) for r in rows]


def query_decisions(conn: sqlite3.Connection, area: str) -> list[dict[str, object]]:
    """Search rows populated by vault decision ingest in ``ingest_analysis``."""
    like = f"%{_like_escape(area)}%"
    rows = conn.execute(
        """
        SELECT vault_path, decision_text, rationale, affected_paths, created_at
        FROM decisions
        WHERE vault_path LIKE ? ESCAPE '\\'
           OR decision_text LIKE ? ESCAPE '\\'
           OR affected_paths LIKE ? ESCAPE '\\'
        ORDER BY id DESC
        LIMIT 50
        """,
        (like, like, like),
    ).fetchall()
    return [dict(r) for r in rows]


def query_similar_issues(conn: sqlite3.Connection, description: str) -> list[dict[str, object]]:
    """Naive similarity: token overlap on pattern_text and comment_body."""
    tokens = [t for t in description.lower().split() if len(t) > 3][:12]
    if not tokens:
        return []
    results: list[dict[str, object]] = []
    for tok in tokens:
        like = f"%{_like_escape(tok)}%"
        rows = conn.execute(
            """
            SELECT 'pattern' AS kind, pattern_text AS text, severity, preventability
            FROM patterns
            WHERE pattern_text LIKE ? ESCAPE '\\'
            LIMIT 10
            """,
            (like,),
        ).fetchall()
        results.extend([dict(r) for r in rows])
        rows = conn.execute(
            """
            SELECT 'evidence' AS kind, comment_body AS text, pr_number, file_path
            FROM pattern_evidence
            WHERE comment_body LIKE ? ESCAPE '\\'
            LIMIT 10
            """,
            (like,),
        ).fetchall()
        results.extend([dict(r) for r in rows])
    return results[:30]


def rows_to_json(rows: list[dict[str, object]]) -> str:
    return json.dumps(rows, indent=2, default=str)
