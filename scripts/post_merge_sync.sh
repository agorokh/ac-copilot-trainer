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
if [[ -z "$REPO_ROOT" ]]; then
  echo "error: could not determine repository root" >&2
  exit 20
fi
cd "$REPO_ROOT"

require_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    echo "error: gh CLI not found" >&2
    exit 20
  fi
}

fail() {
  echo "error: $*" >&2
}

ensure_clean_worktree() {
  UNTRACKED="$(git ls-files --others --exclude-standard 2>/dev/null | sed '/^$/d' || true)"
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$UNTRACKED" ]]; then
    echo "error: working tree is not clean. Please commit, stash, or remove changes before syncing." >&2
    exit 20
  fi
}

phase_sync() {
  require_gh
  ensure_clean_worktree
  STATE="$(gh pr view "$PR" --json state --jq '.state' 2>/dev/null || true)"
  case "$STATE" in
    MERGED) ;;
    OPEN) gh pr merge "$PR" --squash --delete-branch || { fail "failed to merge PR #$PR"; exit 12; } ;;
    "") fail "could not determine PR #$PR state"; exit 20 ;;
    *) fail "PR #$PR is in unexpected state: $STATE"; exit 12 ;;
  esac
  git fetch origin || { fail "failed to fetch origin"; exit 20; }
  git checkout main || { fail "failed to checkout main"; exit 10; }
  git pull --ff-only origin main || { fail "failed to fast-forward local main from origin/main"; exit 10; }
  LOCAL_MAIN_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
  REMOTE_MAIN_SHA="$(git rev-parse origin/main 2>/dev/null || true)"
  if [[ -z "$LOCAL_MAIN_SHA" ]] || [[ -z "$REMOTE_MAIN_SHA" ]]; then
    fail "could not resolve local or remote main after sync"
    exit 20
  fi
  if [[ "$LOCAL_MAIN_SHA" != "$REMOTE_MAIN_SHA" ]]; then
    fail "local main does not match origin/main after sync; refusing to continue"
    exit 10
  fi
  echo "Run classification: python3 scripts/post_merge_classify.py --pr $PR"
  echo "Then prepare vault SAVE: scripts/post_merge_sync.sh vault $PR"
}

phase_vault() {
  require_gh
  CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ "$CURRENT" != "main" ]]; then
    fail "phase_vault must be run from main; current branch is '${CURRENT:-unknown}'"
    exit 20
  fi
  git fetch origin || { fail "failed to fetch origin before vault sync"; exit 20; }
  LOCAL_MAIN_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
  REMOTE_MAIN_SHA="$(git rev-parse origin/main 2>/dev/null || true)"
  if [[ -z "$LOCAL_MAIN_SHA" ]] || [[ -z "$REMOTE_MAIN_SHA" ]]; then
    fail "could not resolve local or remote main before vault sync"
    exit 20
  fi
  if [[ "$LOCAL_MAIN_SHA" != "$REMOTE_MAIN_SHA" ]]; then
    fail "phase_vault requires local main to match origin/main before creating the vault branch"
    exit 10
  fi

  OOS_TRACKED="$(
    {
      git diff --name-only HEAD -- . ':(exclude)docs/01_Vault/' 2>/dev/null
      git diff --cached --name-only -- . ':(exclude)docs/01_Vault/' 2>/dev/null
    } | sort -u | sed '/^$/d' || true
  )"
  if [[ -n "$OOS_TRACKED" ]]; then
    fail "vault-only sync requires all tracked changes to stay under docs/01_Vault/. Offending paths:"
    printf '%s\n' "$OOS_TRACKED" | sed 's/^/  - /' >&2
    exit 30
  fi

  VAULT_UNTRACKED="$(git ls-files --others --exclude-standard -- docs/01_Vault/ 2>/dev/null | sed '/^$/d' || true)"
  if git diff --quiet -- docs/01_Vault/ && git diff --cached --quiet -- docs/01_Vault/ && [[ -z "$VAULT_UNTRACKED" ]]; then
    echo "No vault changes."
    return 0
  fi

  VAULT_BRANCH="vault/post-merge-pr${PR}"
  if git show-ref --verify --quiet "refs/heads/$VAULT_BRANCH"; then
    fail "local branch $VAULT_BRANCH already exists; delete it before rerunning phase_vault"
    exit 10
  fi
  if git ls-remote --exit-code --heads origin "$VAULT_BRANCH" >/dev/null 2>&1; then
    fail "remote branch origin/$VAULT_BRANCH already exists; delete it before rerunning phase_vault"
    exit 11
  fi
  git checkout -b "$VAULT_BRANCH" || { fail "failed to create vault branch $VAULT_BRANCH"; exit 10; }
  git add docs/01_Vault/
  git commit -m "docs(vault): post-merge handoff for PR #${PR}" \
    || { fail "failed to commit vault changes for PR #${PR}"; exit 10; }
  git push -u origin "$VAULT_BRANCH" \
    || { fail "failed to push vault branch $VAULT_BRANCH"; exit 11; }
  EXISTING_PR="$(gh pr list --head "$VAULT_BRANCH" --base main --json number --jq '.[0].number // empty' 2>/dev/null || true)"
  if [[ -n "$EXISTING_PR" ]]; then
    gh pr edit "$EXISTING_PR" \
      --title "docs(vault): post-merge handoff for PR #${PR}" \
      --body "Vault-only handoff updates produced by post-merge-steward." \
      --add-label vault-only || { fail "failed to edit existing vault PR #$EXISTING_PR"; exit 12; }
  else
    gh pr create --title "docs(vault): post-merge handoff for PR #${PR}" \
      --body "Vault-only handoff updates produced by post-merge-steward." \
      --base main --head "$VAULT_BRANCH" --label vault-only || { fail "failed to create vault PR for $VAULT_BRANCH"; exit 12; }
  fi
  git checkout main >/dev/null 2>&1 || { fail "vault PR created, but failed to restore repository to main"; exit 10; }
}

case "$PHASE" in
  sync) phase_sync ;;
  vault) phase_vault ;;
  *) exit 2 ;;
esac
