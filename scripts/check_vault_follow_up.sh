#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  exit 0
fi
if ! cd "$ROOT"; then
  echo "[check_vault_follow_up] error: cannot cd to repository root: $ROOT" >&2
  exit 1
fi

STAGED="$(git diff --cached --name-only 2>/dev/null || true)"
if [[ -z "$STAGED" ]]; then
  exit 0
fi

SENSITIVE="$(printf '%s\n' "$STAGED" | grep -E '^(\.claude/|docs/01_Vault/|scripts/|\.github/workflows/)' || true)"
if [[ -z "$SENSITIVE" ]]; then
  exit 0
fi

ACKED="$(printf '%s\n' "$STAGED" | grep -E '^(docs/01_Vault/[^/]+/01_Decisions/|docs/01_Vault/[^/]+/02_Investigations/|docs/01_Vault/[^/]+/00_System/Next Session Handoff\.md$|docs/01_Vault/[^/]+/00_System/Current Focus\.md$|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)' || true)"
[[ -n "$ACKED" ]] && exit 0

cat >&2 <<EOF
[check_vault_follow_up] Sensitive staged paths without a vault follow-up:

$(printf '%s\n' "$SENSITIVE" | sed 's/^/  - /')
EOF
exit 1
