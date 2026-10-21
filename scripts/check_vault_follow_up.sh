#!/usr/bin/env bash
# Pre-commit reminder: if staged paths touch policy-sensitive areas (.claude/,
# docs/01_Vault/, scripts/, .github/workflows/) and the commit does NOT also
# include a vault follow-up artefact (investigation, decision, dated handoff
# node, or SESSION_LIFECYCLE / MAINTAINING_THE_TEMPLATE update), block with an
# actionable hint. Otherwise allow silently.
#
# A handoff is one new dated node under 00_System/handoffs/ (governance-hub#918).
# The shared files (Next Session Handoff.md, Current Focus.md, any _index.md) are
# not acknowledgements: two handoffs that edit them conflict by construction, so
# this hook never asks for them.
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
# The handoff entry matches one dated node FILE (YYYY-MM-DD-HHMMSSZ-<slug>.md),
# never the handoffs/ directory as a whole and never handoffs/_index.md.
ACKED="$(printf '%s\n' "$STAGED" | grep -E '^(docs/01_Vault/[^/]+/01_Decisions/|docs/01_Vault/[^/]+/02_Investigations/|docs/01_Vault/[^/]+/00_System/handoffs/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]*\.md$|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)' || true)"

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
  - docs/01_Vault/<ProjectKey>/00_System/handoffs/YYYY-MM-DD-HHMMSSZ-<slug>.md
  - docs/00_Core/SESSION_LIFECYCLE.md
  - docs/00_Core/MAINTAINING_THE_TEMPLATE.md

Add the appropriate vault note (one new dated handoff node is enough) and stage
it before re-running the commit. Do not edit Next Session Handoff.md,
Current Focus.md or an _index.md for this. This check is deterministic and
identical across hosts.
EOF
exit 1
