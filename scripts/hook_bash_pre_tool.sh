#!/usr/bin/env bash
# PreToolUse:Bash orchestrator (single chain).
#
# tests/test_memory_hooks_wiring_invariant.py asserts this file exists and
# chains hook_memory_gate.py. The single-orchestrator pattern is required
# because the broader test_base_settings_has_no_unsafe_prompt_flow_control
# invariant asserts exactly one command hook on PreToolUse:Bash.
#
# Chain order:
#   1. hook_protect_main.sh           — block dangerous git operations on main (optional)
#   2. hook_memory_gate.py            — block bash file-edit commands when Tier-3 prefetch stale
#   3. hook_detect_git_commit.py
#      + check_vault_follow_up.sh     — vault follow-up nudge on commits (optional)
#
# Optional steps no-op gracefully if the supporting scripts are not present
# in this repo (each child may carry a different subset of helpers).
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && exit 0

input="$(cat)"

# 1) Protect-main (optional)
if [ -f "$here/hook_protect_main.sh" ]; then
  printf '%s' "$input" | bash "$here/hook_protect_main.sh" || exit $?
fi

# Sensitive-file guard for Bash writes (governance-hub#862): the same hub hook as the
# Edit|Write|MultiEdit|NotebookEdit wiring, through its shim, so one path set governs every
# tool. Literal write targets (redirect, tee, cp/mv, dd of=, sed -i) are classified; targets
# built at runtime and interpreter writes are the hub's named residuals.
printf '%s' "$input" | "$PY" "$here/hook_sensitive_file_guard.py" || exit $?

# 2) Memory gate (REQUIRED — invariant)
printf '%s' "$input" | "$PY" "$here/hook_memory_gate.py" || exit $?

# 3) Vault follow-up on commits (optional)
if [ -f "$here/hook_detect_git_commit.py" ] && [ -f "$root/scripts/check_vault_follow_up.sh" ]; then
  if printf '%s' "$input" | "$PY" "$here/hook_detect_git_commit.py"; then
    bash "$root/scripts/check_vault_follow_up.sh" || exit 2
  fi
fi

exit 0
