#!/usr/bin/env bash
set -euo pipefail

PHASE=""
PR=""
case "${1:-}" in
  sync|vault)
    PHASE="$1"
    PR="${2:-}"
    ;;
  '')
    echo "usage: scripts/post_merge_sync.sh {sync|vault} <pr_number>" >&2
    exit 2
    ;;
  *)
    PHASE="sync"
    PR="$1"
    ;;
esac

if [[ -z "$PR" ]] || ! [[ "$PR" =~ ^[0-9]+$ ]]; then
  echo "usage: scripts/post_merge_sync.sh {sync|vault} <pr_number>" >&2
  exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -z "$REPO_ROOT" ]] && exit 20
cd "$REPO_ROOT"

phase_sync() {
  STATE="$(gh pr view "$PR" --json state --jq '.state' 2>/dev/null || true)"
  case "$STATE" in
    MERGED) ;;
    OPEN) gh pr merge "$PR" --squash --delete-branch || exit 12 ;;
    "") exit 20 ;;
    *) exit 12 ;;
  esac
  git fetch origin || exit 20
  git checkout main
  git pull --ff-only origin main || exit 10
  echo "Run classification: python3 scripts/post_merge_classify.py --pr $PR"
  echo "Then prepare vault SAVE: scripts/post_merge_sync.sh vault $PR"
}

phase_vault() {
  CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ "$CURRENT" != "main" ]] && exit 20

  VAULT_UNTRACKED="$(git ls-files --others --exclude-standard -- docs/01_Vault/ 2>/dev/null | sed '/^$/d' || true)"
  if git diff --quiet -- docs/01_Vault/ && git diff --cached --quiet -- docs/01_Vault/ && [[ -z "$VAULT_UNTRACKED" ]]; then
    echo "No vault changes."
    return 0
  fi

  OOS_TRACKED="$(git diff --name-only HEAD -- . ':(exclude)docs/01_Vault' 2>/dev/null | sort -u | sed '/^$/d' || true)"
  [[ -n "$OOS_TRACKED" ]] && exit 30

  VAULT_BRANCH="vault/post-merge-pr${PR}"
  git branch -D "$VAULT_BRANCH" >/dev/null 2>&1 || true
  git checkout -b "$VAULT_BRANCH"
  git add docs/01_Vault/
  git commit --no-verify -m "docs(vault): post-merge handoff for PR #${PR}" || exit 10
  git push -u --force-with-lease origin "$VAULT_BRANCH" || exit 11
  gh pr create --title "docs(vault): post-merge handoff for PR #${PR}" \
    --body "Vault-only handoff updates produced by post-merge-steward." \
    --base main --head "$VAULT_BRANCH" --label vault-only || exit 12
  git checkout main >/dev/null 2>&1 || true
}

case "$PHASE" in
  sync) phase_sync ;;
  vault) phase_vault ;;
  *) exit 2 ;;
esac
