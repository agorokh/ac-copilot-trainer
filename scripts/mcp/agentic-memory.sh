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
# Materialization (MCP runtime cache — not a memory tier):
#   The materializer runs from agent-factory and anchors --repo-root there, so
#   relative vault_root paths in the central registry resolve against the
#   registry-owning checkout rather than whichever child repo launched the MCP.
#   It writes a derived bridge TOML under .cache/agentic_memory/ (gitignored, same
#   class as .cache/repo_knowledge/). This is ephemeral MCP wiring regenerated from
#   agent-factory's fleet_registry.toml — not Tier-1/2/3 memory; agents must not treat
#   it as durable knowledge or add it to ops/memory_manifest.yml workspaces.
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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CHILD_REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

_die() {
  printf 'agentic-memory.sh: %s\n' "$1" >&2
  printf 'See scripts/mcp/agentic-memory.sh header for required env vars.\n' >&2
  exit 1
}

_expand_home() {
  local p="${1:-}"
  local home="${HOME:-}"
  if [[ "${p}" == "~" || "${p}" == "~/"* ]]; then
    if [[ -z "${home}" ]]; then
      if ! home="$(cd ~ 2>/dev/null && pwd -P)"; then
        _die "HOME is unset and shell could not resolve ~; set HOME or use absolute AGENTIC_MEMORY_* paths."
      fi
    fi
  fi
  if [[ "${p}" == "~" ]]; then
    printf '%s' "${home}"
    return
  fi
  if [[ "${p}" == "~/"* ]]; then
    printf '%s' "${home}/${p:2}"
    return
  fi
  printf '%s' "${p}"
}

_to_abs_path() {
  local p="$(_expand_home "${1:-}")"
  if [[ "${p}" != /* ]]; then
    p="${CHILD_REPO_ROOT}/${p}"
  fi
  printf '%s' "${p}"
}

_resolve_python() {
  local candidate="${1:-}"
  if [[ -n "${candidate}" ]]; then
    candidate="$(_expand_home "${candidate}")"
    if [[ "${candidate}" == */* || "${candidate}" == ./* ]]; then
      if [[ "${candidate}" != /* ]]; then
        candidate="${CHILD_REPO_ROOT}/${candidate}"
      fi
      if [[ ! -x "${candidate}" ]]; then
        return 1
      fi
      printf '%s' "${candidate}"
      return 0
    fi
    if ! command -v "${candidate}" >/dev/null 2>&1; then
      return 1
    fi
    command -v "${candidate}"
    return 0
  fi
  if [[ -x "${MCP_ROOT}/.venv/bin/python" ]]; then
    printf '%s' "${MCP_ROOT}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

# Resolve AGENTIC_MEMORY_MCP_SERVERS_ROOT.
if [[ -n "${AGENTIC_MEMORY_MCP_SERVERS_ROOT:-}" ]]; then
  MCP_ROOT="$(_to_abs_path "${AGENTIC_MEMORY_MCP_SERVERS_ROOT}")"
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
  AF_ROOT="$(_to_abs_path "${AGENTIC_MEMORY_AGENT_FACTORY_ROOT}")"
else
  AF_ROOT="${CHILD_REPO_ROOT}/../agent-factory"
fi

if [[ ! -d "${AF_ROOT}" ]]; then
  _die "AGENTIC_MEMORY_AGENT_FACTORY_ROOT not found at ${AF_ROOT}; clone agorokh/agent-factory as a sibling of this repo or set the env var."
fi

# Resolve source registry path (relative overrides are under agent-factory root).
if [[ -n "${AGENTIC_MEMORY_SOURCE_REGISTRY:-}" ]]; then
  SRC_REGISTRY="$(_expand_home "${AGENTIC_MEMORY_SOURCE_REGISTRY}")"
  if [[ "${SRC_REGISTRY}" != /* ]]; then
    SRC_REGISTRY="${AF_ROOT}/${SRC_REGISTRY}"
  fi
else
  SRC_REGISTRY="${AF_ROOT}/tools/hermes_adapter/fleet_registry.toml"
fi

if [[ ! -f "${SRC_REGISTRY}" ]]; then
  _die "fleet_registry.toml not found at ${SRC_REGISTRY}; verify AGENTIC_MEMORY_AGENT_FACTORY_ROOT points at a checkout of agorokh/agent-factory."
fi

# Resolve python interpreter for the bridge (materialize + server).
if ! BRIDGE_PYTHON="$(_resolve_python "${AGENTIC_MEMORY_MCP_PYTHON:-}")"; then
  if [[ -n "${AGENTIC_MEMORY_MCP_PYTHON:-}" ]]; then
    _die "AGENTIC_MEMORY_MCP_PYTHON is set but not found or not executable: ${AGENTIC_MEMORY_MCP_PYTHON}"
  fi
  _die "no python3 interpreter found; install python3 or set AGENTIC_MEMORY_MCP_PYTHON."
fi

if ! (
  cd -- "${AF_ROOT}" && \
  "${BRIDGE_PYTHON}" -c "import tools.hermes_adapter.agentic_memory_registry_materialize" >/dev/null 2>&1
); then
  _die "tools.hermes_adapter.agentic_memory_registry_materialize not importable from ${AF_ROOT}; verify AGENTIC_MEMORY_AGENT_FACTORY_ROOT."
fi

# Host-aware bridge resolution: when this wrapper runs on a non-central host
# (HERMES_HOST_ID != the host marked is_memory_central in the manifest), the
# helper emits the central host's tailnet name (or Tailscale-resolved IP if
# system DNS doesn't know it). The materializer then rewrites loopback
# endpoints to ``http://<central>:<port>/`` automatically. Operator-set
# AGENTIC_MEMORY_BRIDGE_HOST always wins (helper emits nothing in that case).
_bridge_host_override_check="${AGENTIC_MEMORY_BRIDGE_HOST:-}"
_bridge_host_override_check="${_bridge_host_override_check//[[:space:]]/}"
if [[ -z "${_bridge_host_override_check}" ]]; then
  _detected_bridge_host="$(
    cd -- "${AF_ROOT}" && \
    "${BRIDGE_PYTHON}" -m tools.hermes_adapter.agentic_memory_host_aware_bridge \
      --manifest "${AF_ROOT}/ops/memory_manifest.yml"
  )" || _detected_bridge_host=""
  _detected_bridge_host="${_detected_bridge_host%%$'\n'*}"
  if [[ -n "${_detected_bridge_host}" ]]; then
    export AGENTIC_MEMORY_BRIDGE_HOST="${_detected_bridge_host}"
  fi
fi
unset _bridge_host_override_check

# Materialize the fleet registry. Run from the agent-factory root so the
# tools.hermes_adapter package import resolves. Stdout is the absolute path to
# the materialized registry; capture it into AGENTIC_MEMORY_REGISTRY_PATH.
_materialize_status=0
MATERIALIZED="$(
  cd -- "${AF_ROOT}" && \
  "${BRIDGE_PYTHON}" -m tools.hermes_adapter.agentic_memory_registry_materialize \
    --source "${SRC_REGISTRY}" --repo-root "${AF_ROOT}"
)" || _materialize_status=$?

# Materializer must emit a single filesystem path on stdout (logs belong on stderr).
MATERIALIZED="${MATERIALIZED%%$'\n'*}"

if [[ ${_materialize_status} -ne 0 || -z "${MATERIALIZED}" || ! -f "${MATERIALIZED}" ]]; then
  _die "agentic_memory_registry_materialize failed or produced no output at ${MATERIALIZED:-<empty>}"
fi

export AGENTIC_MEMORY_REGISTRY_PATH="${MATERIALIZED}"
# Prepend agentic-memory src so agentic_memory.server resolves before inherited PYTHONPATH.
if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${AGENTIC_PKG}:${PYTHONPATH}"
else
  export PYTHONPATH="${AGENTIC_PKG}"
fi

if ! "${BRIDGE_PYTHON}" -c "import agentic_memory.server" >/dev/null 2>&1; then
  _die "agentic_memory.server not importable from ${MCP_ROOT}; verify AGENTIC_MEMORY_MCP_SERVERS_ROOT."
fi

exec "${BRIDGE_PYTHON}" -m agentic_memory.server "$@"
