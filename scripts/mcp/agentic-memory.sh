#!/usr/bin/env bash
# Thin consumer shim for the canonical agorokh/mcp-servers agentic-memory launcher.
#
# Purpose:
#   Validate the child-repo launch contract, then hand off to the canonical launcher
#   from agorokh/mcp-servers. Operational bridge logic stays centralized there.
#
# Env vars (with defaults, sibling-clone assumption):
#   AGENTIC_MEMORY_MCP_SERVERS_ROOT   default: ../mcp-servers
#     Path to agorokh/mcp-servers checkout. Provides:
#       scripts/mcp/agentic-memory.sh
#       servers/agentic-memory/src/agentic_memory/server.py
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
#   Exports AGENTIC_MEMORY_CHILD_REPO_ROOT so mcp-servers can materialize the
#   registry and run Doppler from the calling child repo.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
CHILD_REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)" || exit 1

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
    return 0
  fi
  if [[ "${p}" == "~/"* ]]; then
    printf '%s' "${home}/${p:2}"
    return 0
  fi
  printf '%s' "${p}"
}

_to_abs_path() {
  local p
  p="$(_expand_home "${1:-}")" || return 1
  if [[ "${p}" != /* ]]; then
    p="${CHILD_REPO_ROOT}/${p}"
  fi
  printf '%s' "${p}"
}

_resolve_root() {
  local label="${1:-root}"
  local value="${2:-}"
  local default_path="${3:-}"
  local p resolved
  if [[ -n "${value}" ]]; then
    p="$(_to_abs_path "${value}")" || return 1
  else
    p="${default_path}"
  fi
  if [[ ! -d "${p}" ]]; then
    _die "${label} not found at ${p}; clone the expected sibling checkout or set the env var."
  fi
  if ! resolved="$(cd -- "${p}" 2>/dev/null && pwd -P)"; then
    _die "${label} exists but is not accessible: ${p}."
  fi
  printf '%s' "${resolved}"
}

_resolve_command_executable() {
  local name="${1:-}"
  local resolved=""
  if [[ -z "${name}" ]]; then
    return 1
  fi
  if ! resolved="$(type -P "${name}")"; then
    return 1
  fi
  if [[ "${resolved}" == *$'\n'* ]]; then
    return 1
  fi
  if [[ "${resolved}" == */* && "${resolved}" != /* ]]; then
    local resolved_dir resolved_base
    resolved_dir="$(dirname -- "${resolved}")"
    resolved_base="$(basename -- "${resolved}")"
    if ! resolved_dir="$(cd -- "${resolved_dir}" 2>/dev/null && pwd -P)"; then
      return 1
    fi
    resolved="${resolved_dir}/${resolved_base}"
  fi
  if [[ "${resolved}" == /* && ( ! -f "${resolved}" || ! -x "${resolved}" ) ]]; then
    return 1
  fi
  printf '%s' "${resolved}"
}

_resolve_python() {
  local candidate="${1:-}"
  if [[ -n "${candidate}" ]]; then
    candidate="$(_expand_home "${candidate}")" || return 1
    if [[ "${candidate}" == */* || "${candidate}" == ./* ]]; then
      if [[ "${candidate}" != /* ]]; then
        candidate="${CHILD_REPO_ROOT}/${candidate}"
      fi
      if [[ ! -f "${candidate}" || ! -x "${candidate}" ]]; then
        return 1
      fi
      printf '%s' "${candidate}"
      return 0
    fi
    _resolve_command_executable "${candidate}"
    return $?
  fi
  if [[ -n "${MCP_ROOT:-}" && -x "${MCP_ROOT}/.venv/bin/python" ]]; then
    printf '%s' "${MCP_ROOT}/.venv/bin/python"
    return 0
  fi
  _resolve_command_executable python3
}

MCP_ROOT="$(_resolve_root "AGENTIC_MEMORY_MCP_SERVERS_ROOT" "${AGENTIC_MEMORY_MCP_SERVERS_ROOT:-}" "${CHILD_REPO_ROOT}/../mcp-servers")" || exit 1
AGENTIC_PKG="${MCP_ROOT}/servers/agentic-memory/src"
if [[ ! -d "${AGENTIC_PKG}" ]]; then
  _die "agentic-memory package not found at ${AGENTIC_PKG}; verify AGENTIC_MEMORY_MCP_SERVERS_ROOT points at a checkout of agorokh/mcp-servers."
fi

AF_ROOT="$(_resolve_root "AGENTIC_MEMORY_AGENT_FACTORY_ROOT" "${AGENTIC_MEMORY_AGENT_FACTORY_ROOT:-}" "${CHILD_REPO_ROOT}/../agent-factory")" || exit 1

if [[ -n "${AGENTIC_MEMORY_SOURCE_REGISTRY:-}" ]]; then
  SRC_REGISTRY="$(_expand_home "${AGENTIC_MEMORY_SOURCE_REGISTRY}")" || exit 1
  if [[ "${SRC_REGISTRY}" != /* ]]; then
    SRC_REGISTRY="${AF_ROOT}/${SRC_REGISTRY}"
  fi
else
  SRC_REGISTRY="${AF_ROOT}/tools/hermes_adapter/fleet_registry.toml"
fi
if [[ ! -f "${SRC_REGISTRY}" ]]; then
  if [[ -n "${AGENTIC_MEMORY_SOURCE_REGISTRY:-}" ]]; then
    _die "AGENTIC_MEMORY_SOURCE_REGISTRY not found at ${SRC_REGISTRY}."
  fi
  _die "fleet_registry.toml not found at ${SRC_REGISTRY}; verify AGENTIC_MEMORY_AGENT_FACTORY_ROOT points at a checkout of agorokh/agent-factory."
fi

if ! BRIDGE_PYTHON="$(_resolve_python "${AGENTIC_MEMORY_MCP_PYTHON:-}")"; then
  if [[ -n "${AGENTIC_MEMORY_MCP_PYTHON:-}" ]]; then
    _die "AGENTIC_MEMORY_MCP_PYTHON is set but not found or not executable: ${AGENTIC_MEMORY_MCP_PYTHON}"
  fi
  _die "no python3 interpreter found; install python3 or set AGENTIC_MEMORY_MCP_PYTHON."
fi

if ! (
  cd -- "${AF_ROOT}" && \
  PYTHONPATH="${AF_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    "${BRIDGE_PYTHON}" -c "import tools.hermes_adapter.agentic_memory_registry_materialize" >/dev/null 2>&1
); then
  _die "tools.hermes_adapter.agentic_memory_registry_materialize not importable from ${AF_ROOT}; verify AGENTIC_MEMORY_AGENT_FACTORY_ROOT."
fi

if [[ -n "${PYTHONPATH:-}" ]]; then
  CHECK_PYTHONPATH="${AGENTIC_PKG}:${PYTHONPATH}"
else
  CHECK_PYTHONPATH="${AGENTIC_PKG}"
fi
if ! PYTHONPATH="${CHECK_PYTHONPATH}" "${BRIDGE_PYTHON}" -c "import agentic_memory.server" >/dev/null 2>&1; then
  _die "agentic_memory.server not importable from ${MCP_ROOT}; verify AGENTIC_MEMORY_MCP_SERVERS_ROOT."
fi
unset CHECK_PYTHONPATH

CANONICAL_LAUNCHER="${MCP_ROOT}/scripts/mcp/agentic-memory.sh"
if [[ ! -x "${CANONICAL_LAUNCHER}" ]]; then
  _die "canonical agentic-memory launcher is not executable at ${CANONICAL_LAUNCHER}."
fi
SCRIPT_REAL="$("${BRIDGE_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${SCRIPT_DIR}/agentic-memory.sh")" || _die "could not resolve this consumer shim path."
CANONICAL_REAL="$("${BRIDGE_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${CANONICAL_LAUNCHER}")" || _die "could not resolve canonical agentic-memory launcher path."
if [[ "${CANONICAL_REAL}" == "${SCRIPT_REAL}" ]]; then
  _die "AGENTIC_MEMORY_MCP_SERVERS_ROOT points at this consumer repo, which would recursively invoke itself."
fi
unset SCRIPT_REAL CANONICAL_REAL

export AGENTIC_MEMORY_CHILD_REPO_ROOT="${CHILD_REPO_ROOT}"
export AGENTIC_MEMORY_MCP_SERVERS_ROOT="${MCP_ROOT}"
export AGENTIC_MEMORY_AGENT_FACTORY_ROOT="${AF_ROOT}"
export AGENTIC_MEMORY_SOURCE_REGISTRY="${SRC_REGISTRY}"
export AGENTIC_MEMORY_MCP_PYTHON="${BRIDGE_PYTHON}"
unset AGENTIC_MEMORY_REGISTRY_PATH

cd -- "${CHILD_REPO_ROOT}" || _die "child repo root is no longer accessible: ${CHILD_REPO_ROOT}."

exec "${CANONICAL_LAUNCHER}" "$@"
