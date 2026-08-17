#!/usr/bin/env python3
"""
MCP preflight: fail CI if the declared stdio MCP servers cannot start.

`.mcp.json` declares `repo-knowledge`, launched via scripts/mcp/repo-knowledge.sh.
That wrapper needs the `mcp` package importable in the repo interpreter it
selects (REPO_KNOWLEDGE_PYTHON → .venv/Scripts/python.exe → .venv/bin/python →
system python3/python). A venv created without the `.[knowledge]` extra makes
every agent host (Kimi, Claude Code, Cursor) fail the MCP handshake at session
launch with a bare "Connection closed" — this check turns that into an
actionable `make ci-fast` failure instead.

Exits 0 when `.mcp.json` is absent or declares no wrapper-launched server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WRAPPER = "scripts/mcp/repo-knowledge.sh"
REQUIRED_MODULE = "mcp"
REMEDIATION = ".venv/bin/python -m pip install -e '.[knowledge]'"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _declares_wrapper(repo_root: Path) -> bool:
    """True when .mcp.json launches the repo-knowledge wrapper script."""
    mcp_json = repo_root / ".mcp.json"
    if not mcp_json.is_file():
        return False
    try:
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    servers = data.get("mcpServers") or {}
    for server in servers.values():
        args = (server or {}).get("args") or []
        if any(str(a).replace("\\", "/").endswith(WRAPPER) for a in args):
            return True
    return False


def _resolve_wrapper_python(repo_root: Path, env: dict[str, str]) -> str | None:
    """Mirror the interpreter precedence of scripts/mcp/repo-knowledge.sh."""
    override = env.get("REPO_KNOWLEDGE_PYTHON", "").strip()
    if override:
        if override.startswith("~/") or override == "~":
            home = env.get("HOME", "")
            override = home + override[1:] if home else override
        return override if os.access(override, os.X_OK) else None
    for candidate in (
        repo_root / ".venv" / "Scripts" / "python.exe",  # Windows venv layout
        repo_root / ".venv" / "bin" / "python",
    ):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("python3") or shutil.which("python")


def _can_import(python: str, module: str) -> bool:
    try:
        proc = subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def main() -> int:
    repo_root = _repo_root()
    if not _declares_wrapper(repo_root):
        return 0

    python = _resolve_wrapper_python(repo_root, dict(os.environ))
    if python is None:
        print(
            "check_mcp_preflight: no usable interpreter found for "
            f"{WRAPPER} (REPO_KNOWLEDGE_PYTHON, .venv, or system python3).",
            file=sys.stderr,
        )
        return 1

    if not _can_import(python, REQUIRED_MODULE):
        print(
            f"check_mcp_preflight: interpreter '{python}' cannot import "
            f"'{REQUIRED_MODULE}' — the repo-knowledge MCP server will fail to "
            "start in every agent host.\n"
            f"Fix with: {python} -m pip install -e '.[knowledge]'",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
