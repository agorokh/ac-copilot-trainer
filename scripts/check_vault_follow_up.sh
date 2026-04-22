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
# Long options that take a separate argv value (Codex #80); without this, the next token is misread as a pathspec.
long_needs_next = {
    "--author",
    "--date",
    "--cleanup",
    "--trailer",
    "--reuse-message",
    "--reedit-message",
}

while i < len(parts):
    token = parts[i]
    # `git commit -p/--patch` and `--interactive` can fold unstaged paths into the
    # commit; cached-only diff is then insufficient (Codex #80).
    if token in {"-p", "--patch", "--interactive"}:
        raise SystemExit(0)
    # `--pathspec-from-file` can commit unstaged paths without positional pathspecs (Codex #80).
    if token == "--pathspec-from-file" or token.startswith("--pathspec-from-file="):
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
    if token in long_needs_next:
        i += 2
        continue
    # `--fixup` / `--squash` take a commit object (Codex #80); `=` forms consume one token.
    if token.startswith("--fixup"):
        i += 2 if token == "--fixup" else 1
        continue
    if token.startswith("--squash"):
        i += 2 if token == "--squash" else 1
        continue
    if token.startswith("--"):
        i += 1
        continue
    if token.startswith("-"):
        rest = token[1:]
        pos = 0
        while pos < len(rest):
            ch = rest[pos]
            # `-u<mode>` / `-S<keyid>` attach values in the same argv token (Codex #80).
            if ch == "u":
                suffix = rest[pos + 1 :]
                if suffix:
                    i += 1
                elif len(rest) == 1:
                    # Lone `-u` / `-S`: optional mode/key may be the next argv (Codex #80).
                    i += 2 if i + 1 < len(parts) else 1
                else:
                    # `-vu`, etc.: trailing `-u` uses its default; do not eat the pathspec (Bugbot #80).
                    i += 1
                break
            if ch == "S":
                suffix = rest[pos + 1 :]
                if suffix:
                    i += 1
                elif len(rest) == 1:
                    i += 2 if i + 1 < len(parts) else 1
                else:
                    i += 1
                break
            if ch == "a":
                raise SystemExit(0)
            if ch == "p":
                raise SystemExit(0)
            if ch in {"m", "F", "c", "C", "t"}:
                suffix = rest[pos + 1 :]
                # `-mfoo` carries the message in the same argv token (Bugbot #80).
                if suffix:
                    i += 1
                else:
                    i += 2 if i + 1 < len(parts) else 1
                break
            pos += 1
        else:
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

SENSITIVE="$(printf '%s\n' "$FILES_TO_CHECK" | grep -E '^(\.claude/|docs/01_Vault/|docs/00_Core/|scripts/|\.github/workflows/)' || true)"
if [[ -z "$SENSITIVE" ]]; then
  exit 0
fi

ACK_ALLOW='^(docs/01_Vault/|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)'
SENSITIVE_NOT_ACKED="$(printf '%s\n' "$SENSITIVE" | grep -Ev "$ACK_ALLOW" || true)"
if [[ -z "$SENSITIVE_NOT_ACKED" ]]; then
  exit 0
fi

# Codex #80: any same-commit path under docs/01_Vault/ counts as a vault follow-up for the rest of the sensitive set.
if printf '%s\n' "$FILES_TO_CHECK" | grep -qE '^docs/01_Vault/'; then
  exit 0
fi

cat >&2 <<EOF
[check_vault_follow_up] Sensitive commit paths without a vault follow-up:

$(printf '%s\n' "$SENSITIVE_NOT_ACKED" | sed 's/^/  - /')
EOF
exit 1
