# ruff: noqa: I001
"""MCP stdio server for querying mined repository knowledge (SQLite)."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from mcp.server import MCPServer

# One import block (Ruff isort otherwise splits aliases across multiple statements).
from tools.repo_knowledge.query import (
    connect,
    query_ci_failures as rk_query_ci_failures,
    query_decisions as rk_query_decisions,
    query_file_patterns as rk_query_file_patterns,
    query_review_history as rk_query_review_history,
    query_similar_issues as rk_query_similar_issues,
    rows_to_json,
)

mcp = MCPServer("repo-knowledge")


def _db_path() -> Path:
    raw = os.environ.get("REPO_KNOWLEDGE_DB", ".cache/repo_knowledge/knowledge.db")
    return Path(raw).expanduser().resolve()


def _readonly() -> bool:
    """True when the wrapper serves a fallback DB (REPO_KNOWLEDGE_READONLY=1, #2096).

    In read-only mode the server never creates/migrates the DB — it opens the
    existing file with SQLite ``mode=ro`` so a worktree session can serve the main
    checkout's DB without mutating or lock-contending it.
    """
    return os.environ.get("REPO_KNOWLEDGE_READONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@mcp.tool()
def query_file_patterns(file_path: str) -> str:
    """Return pattern clusters linked to a source file path."""
    conn = connect(_db_path(), readonly=_readonly())
    try:
        return rows_to_json(rk_query_file_patterns(conn, file_path))
    finally:
        conn.close()


@mcp.tool()
def query_review_history(glob_pattern: str) -> str:
    """Return recent review-comment evidence rows matching a path glob."""
    conn = connect(_db_path(), readonly=_readonly())
    try:
        return rows_to_json(rk_query_review_history(conn, glob_pattern))
    finally:
        conn.close()


@mcp.tool()
def query_ci_failures(module: str) -> str:
    """Return CI failure rows matching a module substring (job name / affected files)."""
    conn = connect(_db_path(), readonly=_readonly())
    try:
        return rows_to_json(rk_query_ci_failures(conn, module))
    finally:
        conn.close()


@mcp.tool()
def query_decisions(area: str) -> str:
    """Return decision rows matching a vault/topic substring."""
    conn = connect(_db_path(), readonly=_readonly())
    try:
        return rows_to_json(rk_query_decisions(conn, area))
    finally:
        conn.close()


@mcp.tool()
def query_similar_issues(description: str) -> str:
    """Return loosely related patterns/evidence rows for a natural-language description."""
    conn = connect(_db_path(), readonly=_readonly())
    try:
        return rows_to_json(rk_query_similar_issues(conn, description))
    finally:
        conn.close()


def main() -> None:
    p = _db_path()
    if _readonly():
        if not p.exists():
            # The wrapper sets REPO_KNOWLEDGE_READONLY only after verifying the file
            # exists; a missing DB here is a race or a manual flag — fail startup,
            # never run a zombie whose every query errors (#2096, PR #2097 review).
            print(
                f"repo-knowledge: read-only DB missing at {p}; refusing to start.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Defense-in-depth mirror of the wrapper preflight (a manual REPO_KNOWLEDGE_READONLY
        # bypasses the wrapper): the DB must actually OPEN read-only and carry a schema,
        # else startup fails here instead of at the first query (PR #2097 cursor review).
        try:
            conn = connect(p, readonly=True)
            try:
                tables = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            tables = 0
        if tables < 1:
            print(
                f"repo-knowledge: read-only DB at {p} is not openable or has no schema; "
                "refusing to start.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Server-side signal (wrapper stderr is often hidden by MCP hosts): every
        # read-only session starts with this line in the host's server log (#2096).
        print(
            f"repo-knowledge: serving read-only DB at {p} "
            "(worktree fallback; as fresh as its last index run)",
            file=sys.stderr,
        )
    else:
        if not p.exists():
            print(
                f"repo-knowledge: no DB at {p}; it will be created on first query.",
                file=sys.stderr,
            )
        conn = connect(p)
        conn.close()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
