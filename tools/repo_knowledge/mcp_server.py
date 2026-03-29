# ruff: noqa: I001
"""MCP stdio server for querying mined repository knowledge (SQLite)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

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

mcp = FastMCP("repo-knowledge")


def _db_path() -> Path:
    raw = os.environ.get("REPO_KNOWLEDGE_DB", ".cache/repo_knowledge/knowledge.db")
    return Path(raw).expanduser().resolve()


@mcp.tool()
def query_file_patterns(file_path: str) -> str:
    """Return pattern clusters linked to a source file path."""
    conn = connect(_db_path())
    try:
        return rows_to_json(rk_query_file_patterns(conn, file_path))
    finally:
        conn.close()


@mcp.tool()
def query_review_history(glob_pattern: str) -> str:
    """Return recent review-comment evidence rows matching a path glob."""
    conn = connect(_db_path())
    try:
        return rows_to_json(rk_query_review_history(conn, glob_pattern))
    finally:
        conn.close()


@mcp.tool()
def query_ci_failures(module: str) -> str:
    """Return CI failure rows matching a module substring (job name / affected files)."""
    conn = connect(_db_path())
    try:
        return rows_to_json(rk_query_ci_failures(conn, module))
    finally:
        conn.close()


@mcp.tool()
def query_decisions(area: str) -> str:
    """Return decision rows matching a vault/topic substring."""
    conn = connect(_db_path())
    try:
        return rows_to_json(rk_query_decisions(conn, area))
    finally:
        conn.close()


@mcp.tool()
def query_similar_issues(description: str) -> str:
    """Return loosely related patterns/evidence rows for a natural-language description."""
    conn = connect(_db_path())
    try:
        return rows_to_json(rk_query_similar_issues(conn, description))
    finally:
        conn.close()


def main() -> None:
    p = _db_path()
    if not p.exists():
        print(f"repo-knowledge: no DB at {p}; it will be created on first query.", file=sys.stderr)
    conn = connect(p)
    conn.close()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
