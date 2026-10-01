#!/usr/bin/env bash
# Launch the repo-knowledge stdio MCP server from the repo root.
#
# Bare `python` / `python3` in .mcp.json resolves to the system interpreter,
# which lacks the `mcp` package (ModuleNotFoundError -> MCP error -32000
# "Connection closed") — and on machines with no `python` alias at all it fails
# outright. This wrapper mirrors scripts/mcp/agentic-memory.sh: cd to ROOT_DIR
# and prefer the repo's own .venv interpreter, which has `mcp` installed
# (pip install -e ".[knowledge]").
#
# REPO_KNOWLEDGE_DB is intentionally NOT set here; it is passed via the
# .mcp.json env block so the DB path stays config-driven.
#
# Worktree-aware (ported from workstation-ops#2097; fleet rollout
# Atelier-AppliedAI/workstation-ops#3548): inside a linked git worktree with no
# venv or knowledge DB of its own, reuse the MAIN checkout's venv and serve its
# DB read-only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Canonicalize to the physical path: MAIN_ROOT (below) is resolved with pwd -P, and a
# symlinked checkout path would otherwise compare unequal to it — falsely triggering
# the worktree fallbacks in the MAIN checkout itself (PR #2097 gemini review).
ROOT_DIR="$(cd -- "${ROOT_DIR}" && pwd -P)"
cd "${ROOT_DIR}"

# Main checkout root — differs from ROOT_DIR only inside a linked git worktree
# (Cursor/.claude/agentd worktrees). Empty when git is unavailable or the
# common dir cannot be resolved; all main-checkout fallbacks then stay inert.
MAIN_ROOT=""
if _git_common="$(git -C "${ROOT_DIR}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  && [[ -n "${_git_common}" ]]; then
  MAIN_ROOT="$(cd -- "${_git_common}/.." 2>/dev/null && pwd -P || true)"
fi
unset _git_common

# Expand a leading ~ in a path (HOME-relative override support).
_expand_home() {
  local p="${1:-}"
  if [[ "${p}" == "~" ]]; then
    [[ -n "${HOME:-}" ]] && { printf '%s' "${HOME}"; return; }
    printf '%s' "${p}"; return
  fi
  if [[ "${p}" == "~/"* ]]; then
    [[ -n "${HOME:-}" ]] && { printf '%s' "${HOME}/${p:2}"; return; }
    printf '%s' "${p}"; return
  fi
  printf '%s' "${p}"
}

# Validate that a python path is non-empty and executable.
_validate_python_path() {
  local p="${1:-}" explicit="${2:-0}"
  if [[ -z "${p}" ]]; then
    [[ "${explicit}" == "1" ]] \
      && echo "repo-knowledge.sh: REPO_KNOWLEDGE_PYTHON is set but empty" >&2 \
      || echo "repo-knowledge.sh: python path is empty" >&2
    exit 1
  fi
  if [[ ! -x "${p}" ]]; then
    [[ "${explicit}" == "1" ]] \
      && echo "repo-knowledge.sh: REPO_KNOWLEDGE_PYTHON is set but not executable: ${p}" >&2 \
      || echo "repo-knowledge.sh: python path is not executable: ${p}" >&2
    exit 1
  fi
}

# This server runs on MCP SDK v2 only (tools/repo_knowledge/mcp_server.py imports
# `from mcp.server import MCPServer`); every interpreter probe tests that exact symbol.
_mcp_server_importable() { "$1" -c "from mcp.server import MCPServer" >/dev/null 2>&1; }

# The venv interpreter under a checkout root: Windows (git-bash) layout first, then POSIX.
_venv_python() {
  local root="${1:-}"
  if [[ -x "${root}/.venv/Scripts/python.exe" ]]; then
    printf '%s' "${root}/.venv/Scripts/python.exe"
  elif [[ -x "${root}/.venv/bin/python" ]]; then
    printf '%s' "${root}/.venv/bin/python"
  fi
}

# Interpreter selection (in priority order):
#   1. REPO_KNOWLEDGE_PYTHON — explicit operator override (validated; fatal if bad).
#   2. This checkout's own venv, accepted only when it can import the v2 server API — a
#      stub venv falls through instead of dying untried at the preflight (PR #2097).
#   3. <main checkout>/.venv — inside a linked git worktree with no usable venv of its
#      own, reuse the main checkout's venv, but only when it can import the server API.
#   4. system python3 / python (Windows ships `python`).
if [[ -n "${REPO_KNOWLEDGE_PYTHON:-}" ]]; then
  PYTHON="$(_expand_home "${REPO_KNOWLEDGE_PYTHON}")"
  _validate_python_path "${PYTHON}" 1
else
  PYTHON=""
  _own="$(_venv_python "${ROOT_DIR}")"
  if [[ -n "${_own}" ]] && _mcp_server_importable "${_own}"; then
    PYTHON="${_own}"
  elif [[ -n "${MAIN_ROOT}" && "${MAIN_ROOT}" != "${ROOT_DIR}" ]]; then
    _main="$(_venv_python "${MAIN_ROOT}")"
    if [[ -n "${_main}" ]] && _mcp_server_importable "${_main}"; then
      PYTHON="${_main}"
    fi
  fi
  unset _own _main
  if [[ -z "${PYTHON}" ]]; then
    PYTHON="$(command -v python3 || command -v python || true)"
    if [[ -z "${PYTHON}" ]]; then
      echo "repo-knowledge.sh: Neither .venv python nor system python/python3 is executable" >&2
      exit 1
    fi
  fi
fi

# Preflight: the selected interpreter must provide the MCP v2 server API. A v1 install can import
# `mcp` but cannot run this server, so test the exact public symbol used by the module. Without this
# the server starts then dies with a bare ModuleNotFoundError that surfaces to
# the client only as MCP -32000 "Connection closed" — exactly the failure this
# wrapper exists to fix. Fail early with an actionable message instead.
if ! _mcp_server_importable "${PYTHON}"; then
  echo "repo-knowledge.sh: interpreter '${PYTHON}' lacks MCP SDK v2 — install it with: ${PYTHON} -m pip install -e '.[knowledge]'" >&2
  exit 1
fi

# Worktree-aware DB fallback: a relative REPO_KNOWLEDGE_DB resolves against
# this checkout, but a linked worktree usually has no .cache of its own. Serve
# the MAIN checkout's knowledge DB READ-ONLY (REPO_KNOWLEDGE_READONLY=1: the
# server opens it SQLite mode=ro and skips mkdir/schema, so the fallback never
# mutates or lock-contends the main DB; WAL tolerates a concurrent writer).
# A worktree-local DB always wins when present. The fallback fires for BOTH an
# unset var and the explicit relative default in .mcp.json — the config value is
# a default, not an intent for a worktree-local DB (PR #2097 review). Opt out
# and force a fresh worktree-local DB: set an ABSOLUTE REPO_KNOWLEDGE_DB, or
# pre-create the worktree file. The stderr notice names the freshness caveat:
# the main DB is only as current as its last index run.
DB_VAL="${REPO_KNOWLEDGE_DB:-.cache/repo_knowledge/knowledge.db}"
if [[ "${DB_VAL}" != /* && "${DB_VAL}" != "~"* && ! "${DB_VAL}" =~ ^[A-Za-z]:[/\\] ]]; then
  if [[ ! -f "${ROOT_DIR}/${DB_VAL}" ]] \
    && [[ -n "${MAIN_ROOT}" && "${MAIN_ROOT}" != "${ROOT_DIR}" ]] \
    && [[ -f "${MAIN_ROOT}/${DB_VAL}" ]]; then
    export REPO_KNOWLEDGE_DB="${MAIN_ROOT}/${DB_VAL}"
    export REPO_KNOWLEDGE_READONLY=1
    # Preflight the read-only open BEFORE serving: a WAL DB needs its directory
    # writable for -shm recovery, and a zero-byte/interrupted file opens as an empty
    # schema-less DB — both must fail here with a scoped diagnostic, not as a zombie
    # server or per-query errors (PR #2097 kimi + codex reviews).
    if ! "${PYTHON}" - "${REPO_KNOWLEDGE_DB}" <<'PY' >/dev/null 2>&1
import sqlite3
import sys
from pathlib import Path

uri = Path(sys.argv[1]).expanduser().resolve().as_uri()
conn = sqlite3.connect(f"{uri}?mode=ro", uri=True)
try:
    tables = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
finally:
    conn.close()
sys.exit(0 if tables >= 1 else 1)
PY
    then
      echo "repo-knowledge.sh: fallback DB at ${REPO_KNOWLEDGE_DB} is not readable read-only (WAL sidecar writability) or is empty/invalid (probe interpreter: ${PYTHON}); refusing to start a broken server. Re-index the main checkout, fix the directory writability, or give this worktree its own .cache DB." >&2
      exit 1
    fi
    echo "repo-knowledge.sh: worktree has no ${DB_VAL}; serving main checkout DB read-only at ${MAIN_ROOT}/${DB_VAL} (as fresh as its last index run)" >&2
  fi
fi
unset DB_VAL

exec "${PYTHON}" -m tools.repo_knowledge.mcp_server "$@"
