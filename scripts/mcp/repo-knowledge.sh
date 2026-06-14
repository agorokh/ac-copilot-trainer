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
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

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

# Prefer the repo venv interpreter (has `mcp`); allow an explicit override; fall
# back to system python3 only if the venv interpreter is not executable.
if [[ -n "${REPO_KNOWLEDGE_PYTHON:-}" ]]; then
  PYTHON="$(_expand_home "${REPO_KNOWLEDGE_PYTHON}")"
  _validate_python_path "${PYTHON}" 1
elif [[ -x "${ROOT_DIR}/.venv/Scripts/python.exe" ]]; then
  # Windows venv layout (git-bash): interpreter lives under Scripts/, not bin/.
  PYTHON="${ROOT_DIR}/.venv/Scripts/python.exe"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON="${ROOT_DIR}/.venv/bin/python"
else
  # Windows has `python`, not `python3`; prefer whichever resolves.
  PYTHON="$(command -v python3 || command -v python || true)"
  if [[ -z "${PYTHON}" ]]; then
    echo "repo-knowledge.sh: Neither .venv python nor system python/python3 is executable" >&2
    exit 1
  fi
fi

# Preflight: the selected interpreter must be able to import `mcp`. Without this
# the server starts then dies with a bare ModuleNotFoundError that surfaces to
# the client only as MCP -32000 "Connection closed" — exactly the failure this
# wrapper exists to fix. Fail early with an actionable message instead.
if ! "${PYTHON}" -c "import mcp" >/dev/null 2>&1; then
  echo "repo-knowledge.sh: interpreter '${PYTHON}' cannot import 'mcp' — install it with: ${PYTHON} -m pip install -e '.[knowledge]'" >&2
  exit 1
fi

exec "${PYTHON}" -m tools.repo_knowledge.mcp_server "$@"
