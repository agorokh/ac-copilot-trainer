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
commit_includes_all_tracked() {
  case " ${AC_VAULT_FOLLOW_UP_COMMAND:-} " in
    *" --all "*|*" -a "*|*" -am "*) return 0 ;;
    *) return 1 ;;
  esac
}

FILES_TO_CHECK="$STAGED"
if commit_includes_all_tracked; then
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

ACKED="$(printf '%s\n' "$FILES_TO_CHECK" | grep -E '^(docs/01_Vault/[^/]+/01_Decisions/|docs/01_Vault/[^/]+/[0-9]{2}_Investigations/|docs/01_Vault/[^/]+/00_System/Next Session Handoff\.md$|docs/01_Vault/[^/]+/00_System/Current Focus\.md$|docs/00_Core/SESSION_LIFECYCLE\.md$|docs/00_Core/MAINTAINING_THE_TEMPLATE\.md$)' || true)"
[[ -n "$ACKED" ]] && exit 0

cat >&2 <<EOF
[check_vault_follow_up] Sensitive staged paths without a vault follow-up:

$(printf '%s\n' "$SENSITIVE" | sed 's/^/  - /')
EOF
exit 1
