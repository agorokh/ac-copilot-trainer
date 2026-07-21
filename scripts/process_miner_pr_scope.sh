#!/usr/bin/env bash
# OWNER: @agorokh
# Fail closed unless the staged weekly-miner diff contains only added or repaired learned rules.
set -euo pipefail

if git diff --cached --quiet; then
  exit 0
fi

INVALID_STAGED="$(
  git diff --cached --name-status |
    awk '
      $1 !~ /^(A|M)$/ ||
      ($2 !~ /^\.claude\/rules\/learned\/.*\.md$/ &&
       $2 !~ /^\.cursor\/rules\/learned\/.*\.mdc$/) { print }
    '
)"
if [[ -n "$INVALID_STAGED" ]]; then
  echo "Weekly miner PR must contain only added or repaired learned-rule files." >&2
  printf '%s\n' "$INVALID_STAGED" >&2
  exit 1
fi
