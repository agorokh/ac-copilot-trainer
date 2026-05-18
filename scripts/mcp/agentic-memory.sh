#!/usr/bin/env bash
# Portable agentic-memory MCP wrapper for child repos.
#
# Purpose:
#   Launch the agentic-memory MCP server (from agorokh/mcp-servers) using fleet
#   registry data (from agorokh/agent-factory) without requiring the child repo
#   to vendor either codebase. Sibling clones are resolved via env vars.
#
# Env vars (with defaults — sibling-clone assumption):
#   AGENTIC_MEMORY_MCP_SERVERS_ROOT   default: ../mcp-servers
#     Path to agorokh/mcp-servers checkout. Provides:
#       servers/agentic-memory/src/agentic_memory/server.py (PYTHONPATH)
#
#   AGENTIC_MEMORY_AGENT_FACTORY_ROOT default: ../agent-factory
#     Path to agorokh/agent-factory checkout. Provides:
#       tools/hermes_adapter/fleet_registry.toml
#       tools.hermes_adapter.agentic_memory_registry_materialize module
#
#   AGENTIC_MEMORY_SOURCE_REGISTRY    default: $AGENTIC_MEMORY_AGENT_FACTORY_ROOT/tools/hermes_adapter/fleet_registry.toml
#   AGENTIC_MEMORY_MCP_PYTHON         default: $AGENTIC_MEMORY_MCP_SERVERS_ROOT/.venv/bin/python OR python3
#
# Output:
#   Exports AGENTIC_MEMORY_REGISTRY_PATH to the materialized registry file,
#   then execs the agentic-memory MCP server over stdio.
#
# Fail-safe contract:
#   If either sibling root is missing, the wrapper emits a clear stderr message
#   and exits non-zero. The caller (Claude Code MCP loader) treats this as a
#   server-unavailable condition and continues without agentic-memory. This is
#   intentional so a child repo without sibling clones on disk does not break
#   agent startup.

set -uo pipefail

# Disable -e for the validation phase so we can emit a clean error message.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CHILD_REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

_die() {
  printf 'agentic-memory.sh: %s\n' "$1" >&2
  printf 'See scripts/mcp/agentic-memory.sh header for required env vars.\n' >&2
  exit 1
}

_expand_home() {
  local p="${1:-}"
  if [[ "${p}" == "~" ]]; then
    printf '%s' "${HOME}"
    return
  fi
  if [[ "${p}" == "~/"* ]]; then
    printf '%s' "${HOME}/${p:2}"
    return
  fi
  printf '%s' "${p}"
}

# Resolve AGENTIC_MEMORY_MCP_SERVERS_ROOT.
if [[ -n "${AGENTIC_MEMORY_MCP_SERVERS_ROOT:-}" ]]; then
  MCP_ROOT="$(_expand_home "${AGENTIC_MEMORY_MCP_SERVERS_ROOT}")"
else
  MCP_ROOT="${CHILD_REPO_ROOT}/../mcp-servers"
fi

if [[ ! -d "${MCP_ROOT}" ]]; then
  _die "AGENTIC_MEMORY_MCP_SERVERS_ROOT not found at ${MCP_ROOT}; clone agorokh/mcp-servers as a sibling of this repo or set the env var."
fi

AGENTIC_PKG="${MCP_ROOT}/servers/agentic-memory/src"
if [[ ! -d "${AGENTIC_PKG}" ]]; then
  _die "agentic-memory package not found at ${AGENTIC_PKG}; verify AGENTIC_MEMORY_MCP_SERVERS_ROOT points at a checkout of agorokh/mcp-servers."
fi

# Resolve AGENTIC_MEMORY_AGENT_FACTORY_ROOT.
if [[ -n "${AGENTIC_MEMORY_AGENT_FACTORY_ROOT:-}" ]]; then
  AF_ROOT="$(_expand_home "${AGENTIC_MEMORY_AGENT_FACTORY_ROOT}")"
else
  AF_ROOT="${CHILD_REPO_ROOT}/../agent-factory"
fi

if [[ ! -d "${AF_ROOT}" ]]; then
  _die "AGENTIC_MEMORY_AGENT_FACTORY_ROOT not found at ${AF_ROOT}; clone agorokh/agent-factory as a sibling of this repo or set the env var."
fi

# Resolve source registry path.
if [[ -n "${AGENTIC_MEMORY_SOURCE_REGISTRY:-}" ]]; then
  SRC_REGISTRY="$(_expand_home "${AGENTIC_MEMORY_SOURCE_REGISTRY}")"
else
  SRC_REGISTRY="${AF_ROOT}/tools/hermes_adapter/fleet_registry.toml"
fi

if [[ ! -f "${SRC_REGISTRY}" ]]; then
  _die "fleet_registry.toml not found at ${SRC_REGISTRY}; verify AGENTIC_MEMORY_AGENT_FACTORY_ROOT points at a checkout of agorokh/agent-factory."
fi

# Resolve python interpreter for the bridge (materialize + server).
BRIDGE_PYTHON="${AGENTIC_MEMORY_MCP_PYTHON:-}"
if [[ -n "${BRIDGE_PYTHON}" ]]; then
  BRIDGE_PYTHON="$(_expand_home "${BRIDGE_PYTHON}")"
  if [[ ! -x "${BRIDGE_PYTHON}" ]]; then
    _die "AGENTIC_MEMORY_MCP_PYTHON is set but not executable: ${BRIDGE_PYTHON}"
  fi
elif [[ -x "${MCP_ROOT}/.venv/bin/python" ]]; then
  BRIDGE_PYTHON="${MCP_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  BRIDGE_PYTHON="$(command -v python3)"
else
  _die "no python3 interpreter found; install python3 or set AGENTIC_MEMORY_MCP_PYTHON."
fi

# Materialize the fleet registry. Run from the agent-factory root so the
# tools.hermes_adapter package import resolves. Stdout is the absolute path to
# the materialized registry; capture it into AGENTIC_MEMORY_REGISTRY_PATH.
set -e
MATERIALIZED="$(
  cd -- "${AF_ROOT}" && \
  "${BRIDGE_PYTHON}" -m tools.hermes_adapter.agentic_memory_registry_materialize \
    --source "${SRC_REGISTRY}" --repo-root "${AF_ROOT}"
)"
set +e

if [[ -z "${MATERIALIZED}" || ! -f "${MATERIALIZED}" ]]; then
  _die "agentic_memory_registry_materialize produced no output at ${MATERIALIZED:-<empty>}"
fi

export AGENTIC_MEMORY_REGISTRY_PATH="${MATERIALIZED}"
export PYTHONPATH="${AGENTIC_PKG}${PYTHONPATH:+:${PYTHONPATH}}"

exec "${BRIDGE_PYTHON}" -m agentic_memory.server
