#!/usr/bin/env bash
# PreToolUse:Bash flow-control hook. Blocks git commit/push on main/master.
#
# Input (stdin): Claude Code hook JSON: { "tool_input": { "command": "..." }, ... }
# Exit: 0 = allow; 2 = block (Claude Code treats exit 2 as a blocking denial).
#
# Implementation lives in hook_protect_main_impl.py (avoid bash -c quoting traps).
#
# Testable: `printf '%s' '<json>' | bash hook_protect_main.sh; echo $?`.
set -uo pipefail

raw=$(cat)

PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL="$HERE/hook_protect_main_impl.py"
[ -f "$IMPL" ] || exit 0

printf '%s' "$raw" | "$PY" "$IMPL"
rc=$?
[ "$rc" -eq 2 ] && exit 2
exit 0
