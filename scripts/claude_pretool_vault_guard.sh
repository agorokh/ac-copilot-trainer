#!/usr/bin/env bash
# PreToolUse Bash hook: run vault follow-up guard for `git commit` commands.
# stdin = Claude hook JSON. Fail closed on parse errors when commit intent is likely (Bugbot #80).
set -euo pipefail

input="$(cat)"
if ! cmd="$(printf '%s' "$input" | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('tool_input', {}).get('command', ''))")"; then
  if printf '%s' "$input" | grep -qE 'git[[:space:]]+commit'; then
    echo "[claude_pretool_vault_guard] failed to parse hook JSON for a likely git commit; blocking" >&2
    exit 2
  fi
  exit 0
fi

case "$cmd" in
*git*commit*)
  root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  AC_VAULT_FOLLOW_UP_COMMAND="$cmd" bash "$root/scripts/check_vault_follow_up.sh" || exit 2
  ;;
esac
exit 0
