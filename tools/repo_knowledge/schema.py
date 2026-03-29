"""SQLite schema for repo knowledge graph.

DDL is idempotent: ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` so
``apply_schema`` can run on every connection (including empty DBs before first ingest).
"""

from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    review_comment_count INTEGER NOT NULL DEFAULT 0,
    ci_failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_text TEXT NOT NULL UNIQUE,
    severity TEXT,
    preventability TEXT,
    frequency INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS file_patterns (
    file_path TEXT NOT NULL,
    pattern_id INTEGER NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (file_path, pattern_id),
    FOREIGN KEY (pattern_id) REFERENCES patterns(id)
);

CREATE TABLE IF NOT EXISTS pattern_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id INTEGER NOT NULL,
    pr_number INTEGER,
    comment_author TEXT,
    comment_body TEXT,
    file_path TEXT,
    line_number INTEGER,
    created_at TEXT,
    FOREIGN KEY (pattern_id) REFERENCES patterns(id)
);

CREATE TABLE IF NOT EXISTS ci_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER,
    job_name TEXT,
    failure_category TEXT,
    root_cause TEXT,
    affected_files TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_path TEXT,
    decision_text TEXT,
    rationale TEXT,
    affected_paths TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ingest_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_patterns_file ON file_patterns(file_path);
CREATE INDEX IF NOT EXISTS idx_evidence_pattern ON pattern_evidence(pattern_id);
CREATE INDEX IF NOT EXISTS idx_patterns_text ON patterns(pattern_text);
"""


def apply_schema(conn) -> None:
    """Execute DDL on an open sqlite3 connection."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
