#!/usr/bin/env bash
# Fail if canonical agent policy docs are missing.
set -euo pipefail
cd "$(dirname "$0")/.."
missing=0
for f in AGENTS.md AGENT_CORE_PRINCIPLES.md CLAUDE.md; do
  if [[ ! -f "$f" ]]; then
    echo "Policy check failed: $f not found" >&2
    missing=1
  fi
done
[[ "$missing" -eq 0 ]] || exit 1
echo "Policy docs: OK"
