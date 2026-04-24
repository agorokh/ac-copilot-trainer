#!/usr/bin/env bash
# PreToolUse:Bash orchestrator: stdin = hook JSON once → protect-main → vault follow-up on commits.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && exit 0

input="$(cat)"

printf '%s' "$input" | bash "$root/scripts/hook_protect_main.sh" || exit $?

if printf '%s' "$input" | "$PY" "$here/hook_detect_git_commit.py"; then
  bash "$root/scripts/check_vault_follow_up.sh" || exit 2
fi
exit 0
