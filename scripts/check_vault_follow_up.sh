#!/usr/bin/env bash
# Pre-commit reminder: if staged paths touch policy-sensitive areas (.claude/,
# docs/01_Vault/, scripts/, .github/workflows/) and the commit does NOT also
# include a vault follow-up artefact (investigation, decision, handoff, or
# SESSION_LIFECYCLE / MAINTAINING_THE_TEMPLATE update), block with an
# actionable hint. Otherwise allow silently.
#
# Deterministic by design — works the same in Claude Code, Cursor, and Codex.
# (Replaces the `prompt`-type PreToolUse hook that required LLM acknowledgement
# and was auto-blocked by hosts that cannot reply to hook prompts.)
#
# Exit codes:
#   0  allow (no staged paths, no sensitive paths, or vault follow-up acknowledged)
#   1  block (sensitive paths staged without vault follow-up)
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  # Not inside a git work tree — nothing to validate.
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

# Sensitive areas that require vault/workflow follow-up consideration.
SENSITIVE="$(printf '%s\n' "$STAGED" | grep -E '^(\.claude/|docs/01_Vault/|scripts/|\.github/workflows/)' || true)"
if [[ -z "$SENSITIVE" ]]; then
  exit 0
fi

# Acknowledgement signals — any of these in the same staged set means the
# author has already addressed vault/workflow discipline for this commit.
ACKED="$(printf '%s\n' "$STAGED" | grep -E '^(docs/01_Vault/[^/]+/01_Decisions/|docs/01_Vault/[^/]+/02_Investigations/|docs/01_Vault/[^/]+/00_System/Next Session Handoff\.md$|docs/01_Vault/[^/]+/00_System/Current Focus\.md$|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)' || true)"

if [[ -n "$ACKED" ]]; then
  exit 0
fi

cat >&2 <<EOF
[check_vault_follow_up] Sensitive staged paths without a vault follow-up:

$(printf '%s\n' "$SENSITIVE" | sed 's/^/  - /')

Per docs/00_Core/SESSION_LIFECYCLE.md, commits touching .claude/, docs/01_Vault/,
scripts/, or .github/workflows/ should also stage at least one of:
  - docs/01_Vault/<ProjectKey>/01_Decisions/<adr>.md
  - docs/01_Vault/<ProjectKey>/02_Investigations/<note>.md
  - docs/01_Vault/<ProjectKey>/00_System/Next Session Handoff.md
  - docs/01_Vault/<ProjectKey>/00_System/Current Focus.md
  - docs/00_Core/SESSION_LIFECYCLE.md
  - docs/00_Core/MAINTAINING_THE_TEMPLATE.md

Add the appropriate vault note (or update the handoff) and stage it before
re-running the commit. This check is deterministic and identical across hosts.
EOF
exit 1
