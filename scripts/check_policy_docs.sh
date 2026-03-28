#!/usr/bin/env bash
# Fail if canonical agent policy docs are missing.
set -euo pipefail
cd "$(dirname "$0")/.."
missing=0
required=(
  AGENTS.md
  AGENT_CORE_PRINCIPLES.md
  CLAUDE.md
  .cursorrules
  docs/00_Core/SESSION_LIFECYCLE.md
  docs/01_Vault/00_Graph_Schema.md
)
optional=(
  CODEX.md
  WARP.md
)
for f in "${required[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Policy check failed: $f not found" >&2
    missing=1
  fi
done
for f in "${optional[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Policy check warning: optional $f not present (child repos may omit)" >&2
  fi
done
[[ "$missing" -eq 0 ]] || exit 1
echo "Policy docs: OK"
