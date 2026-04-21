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
commit_may_include_unstaged_tracked() {
  AC_VAULT_FOLLOW_UP_COMMAND="${AC_VAULT_FOLLOW_UP_COMMAND:-}" python3 - <<'PY'
import os
import shlex
import sys

cmd = os.environ.get("AC_VAULT_FOLLOW_UP_COMMAND", "")
if not cmd:
    raise SystemExit(0)

try:
    parts = shlex.split(cmd)
except ValueError:
    raise SystemExit(0)

try:
    i = parts.index("commit") + 1
except ValueError:
    raise SystemExit(0)

opts_with_values = {"-m", "--message", "-F", "--file", "-c", "-C", "-t", "--template"}

while i < len(parts):
    token = parts[i]
    # `git commit -p/--patch` and `--interactive` can fold unstaged paths into the
    # commit; cached-only diff is then insufficient (Codex #80).
    if token in {"-p", "--patch", "--interactive"}:
        raise SystemExit(0)
    if token in {"-a", "--all", "-i", "--include", "-o", "--only"}:
        raise SystemExit(0)
    if token == "--":
        raise SystemExit(0 if i + 1 < len(parts) else 1)
    if token in opts_with_values:
        i += 2
        continue
    if token.startswith(("--message=", "--file=", "--template=")):
        i += 1
        continue
    if token.startswith("--"):
        i += 1
        continue
    if token.startswith("-"):
        flags = token[1:]
        for flag in flags:
            if flag == "a":
                raise SystemExit(0)
            if flag == "p":
                raise SystemExit(0)
            if flag in {"m", "F", "c", "C", "t"}:
                break
        i += 1
        continue

    raise SystemExit(0)

raise SystemExit(1)
PY
}

FILES_TO_CHECK="$STAGED"
if commit_may_include_unstaged_tracked; then
  UNSTAGED_TRACKED="$(git diff --name-only 2>/dev/null || true)"
  FILES_TO_CHECK="$(printf '%s\n%s\n' "$FILES_TO_CHECK" "$UNSTAGED_TRACKED" | sort -u | sed '/^$/d')"
fi

if [[ -z "$FILES_TO_CHECK" ]]; then
  exit 0
fi

SENSITIVE="$(printf '%s\n' "$FILES_TO_CHECK" | grep -E '^(\.claude/|docs/01_Vault/|scripts/|\.github/workflows/)' || true)"
if [[ -z "$SENSITIVE" ]]; then
  exit 0
fi

ACKED="$(printf '%s\n' "$FILES_TO_CHECK" | grep -E '^(docs/01_Vault/|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)' || true)"
[[ -n "$ACKED" ]] && exit 0

cat >&2 <<EOF
[check_vault_follow_up] Sensitive commit paths without a vault follow-up:

$(printf '%s\n' "$SENSITIVE" | sed 's/^/  - /')
EOF
exit 1
