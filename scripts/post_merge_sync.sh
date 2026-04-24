#!/usr/bin/env bash
# Post-merge: deterministic sync helper for the post-merge-steward agent.
#
# Phases (run in order, each reports via exit code; agent must NOT improvise on non-zero):
#   sync   : merge PR if open, ff-pull main, delete merged branch, prune, verify linked issues
#   vault  : create branch `vault/post-merge-pr<N>` from main, restore vault edits onto it,
#            commit with --no-verify (docs-only scope), push, label PR `vault-only`, enable auto-merge
#
# WIP handling: on entry, dirty tree is auto-stashed under a named ref.
# On success the stash is restored; stash pop failure is a hard stop (exit 10).
#
# Exit codes (contract — agent prompt depends on these):
#   0   success
#   2   usage (bad args / missing tools)
#   10  git conflict (ff-pull failed, stash conflict on pop, vault commit failed)
#   11  branch-protection rejection (push to vault branch refused)
#   12  PR state unexpected (neither OPEN nor MERGED), vault PR creation failed, or
#       vault push rejected for recoverable reasons (e.g. non-fast-forward — fix remote and retry)
#   13  linked issue still OPEN after merge (warning-class; agent should surface, not retry)
#   20  infrastructure error (gh missing/auth, network, git fetch, stash push failure,
#       missing local main, linked-issue verify failure)
#   30  vault scope violation (would-be commit touches paths outside docs/01_Vault/)
#
# Usage:
#   scripts/post_merge_sync.sh sync <pr_number>
#   scripts/post_merge_sync.sh vault <pr_number>
#   scripts/post_merge_sync.sh <pr_number>           # back-compat: runs `sync` only
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

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI not found" >&2
  exit 20
fi
if ! command -v git >/dev/null 2>&1; then
  echo "error: git not found" >&2
  exit 20
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "error: not inside a git repository" >&2
  exit 20
fi
cd "$REPO_ROOT"

STASH_LABEL="post-merge-pr${PR}-wip"
SAVED_STASH=""

stash_wip_if_dirty() {
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    echo "Working tree dirty; stashing as '${STASH_LABEL}'..."
    if git stash push --include-untracked --message "$STASH_LABEL" >/dev/null 2>&1; then
      SAVED_STASH="$(git stash list --grep="$STASH_LABEL" --pretty=format:'%gd' | head -n1)"
      echo "Stashed: ${SAVED_STASH:-(unknown ref)}"
    else
      echo "error: git stash push failed; resolve the working tree and retry." >&2
      exit 20
    fi
  fi
}

restore_stash_best_effort() {
  if [[ -n "$SAVED_STASH" ]]; then
    if git stash pop "$SAVED_STASH" >/dev/null 2>&1; then
      echo "Restored stash $SAVED_STASH"
      SAVED_STASH=""
    else
      echo "" >&2
      echo "error: could not auto-restore stash $SAVED_STASH (likely conflicts with new main)." >&2
      echo "      Recover manually: git stash list ; git stash apply $SAVED_STASH" >&2
      exit 10
    fi
  fi
}

print_stash_on_exit() {
  local code="$?"
  if [[ -n "$SAVED_STASH" && "$code" -ne 0 ]]; then
    echo "" >&2
    echo "Your WIP is preserved as $SAVED_STASH (label: $STASH_LABEL)." >&2
    echo "Recover with: git stash list ; git stash apply $SAVED_STASH" >&2
  fi
  exit "$code"
}
trap print_stash_on_exit EXIT

# -----------------------------------------------------------------------------
# Phase: sync
# -----------------------------------------------------------------------------
phase_sync() {
  stash_wip_if_dirty

  STATE="$(gh pr view "$PR" --json state --jq '.state' 2>/dev/null || true)"
  case "$STATE" in
    MERGED)
      echo "PR #$PR already merged."
      ;;
    OPEN)
      echo "Merging PR #$PR (squash, delete remote branch)..."
      if ! gh pr merge "$PR" --squash --delete-branch; then
        echo "error: gh pr merge failed" >&2
        exit 12
      fi
      ;;
    "")
      echo "error: gh could not look up PR #$PR (auth or network)" >&2
      exit 20
      ;;
    *)
      echo "PR #$PR is neither OPEN nor MERGED (state=$STATE); aborting." >&2
      exit 12
      ;;
  esac

  HEAD_REF="$(gh pr view "$PR" --json headRefName --jq '.headRefName' 2>/dev/null || true)"
  CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"

  echo "Updating local main..."
  if ! git fetch origin; then
    echo "error: git fetch origin failed (network or remote misconfiguration)" >&2
    exit 20
  fi
  if ! git show-ref --verify --quiet refs/heads/main; then
    echo "error: local branch main not found" >&2
    exit 20
  fi
  git checkout main
  if ! git pull --ff-only origin main; then
    echo "error: ff-pull failed (local main has divergent commits)" >&2
    exit 10
  fi

  if [[ -n "$HEAD_REF" && "$HEAD_REF" != "main" ]]; then
    if git show-ref --verify --quiet "refs/heads/$HEAD_REF"; then
      echo "Deleting local branch $HEAD_REF (PR head; squash merges usually need -D)..."
      git branch -d "$HEAD_REF" 2>/dev/null || git branch -D "$HEAD_REF" 2>/dev/null || true
    fi
  fi

  git fetch --prune origin >/dev/null 2>&1 || true

  echo ""
  echo "Pruning local branches whose upstream is gone (excluding main)..."
  while IFS=$'\t' read -r name track; do
    [[ -z "$name" ]] && continue
    [[ "$name" == "main" ]] && continue
    [[ "$track" == *"[gone]"* ]] || continue
    if out="$(git branch -D "$name" 2>&1)"; then
      echo "Deleted gone branch: $name ($out)"
    else
      echo "Note: could not delete gone branch $name: $out" >&2
    fi
  done < <(git for-each-ref --format='%(refname:short)%09%(upstream:track)' refs/heads/ 2>/dev/null || true)

  echo ""
  echo "Linked issues (verify closed):"
  NUMS="$(gh pr view "$PR" --json closingIssuesReferences --jq '.closingIssuesReferences[].number' 2>/dev/null || true)"
  OPEN_LINKED=0
  ISSUE_VERIFY_FAILED=0
  if [[ -n "${NUMS//[$'\n\r\t ']/}" ]]; then
    while IFS= read -r num; do
      [[ -z "${num// }" ]] && continue
      if ! istate="$(gh issue view "$num" --json state --jq '.state' 2>/dev/null)"; then
        echo "  #$num [VERIFY_FAILED] (could not read issue state from GitHub)" >&2
        ISSUE_VERIFY_FAILED=1
        continue
      fi
      if ! ititle="$(gh issue view "$num" --json title --jq '.title' 2>/dev/null)"; then
        ititle="(title unavailable)"
      fi
      echo "  #$num [$istate] $ititle"
      [[ "$istate" == "OPEN" ]] && OPEN_LINKED=1
    done <<< "$NUMS"
  else
    echo "  (none reported by GitHub for this PR)"
  fi

  if [[ "$ISSUE_VERIFY_FAILED" -eq 1 ]]; then
    echo "error: linked issue state could not be verified (auth or network); fix and re-run sync." >&2
    exit 20
  fi

  restore_stash_best_effort

  echo ""
  echo "Run classification: python3 scripts/post_merge_classify.py --pr $PR"
  echo "Then prepare vault SAVE: scripts/post_merge_sync.sh vault $PR"
  if [[ "$CURRENT" != "main" ]]; then
    echo "(You were on branch $CURRENT before sync; now on main.)"
  fi

  if [[ "$OPEN_LINKED" -eq 1 ]]; then
    echo "" >&2
    echo "WARNING: at least one linked issue is still OPEN; verify the merge should have resolved it." >&2
    exit 13
  fi
}

# -----------------------------------------------------------------------------
# Phase: vault
# -----------------------------------------------------------------------------
phase_vault() {
  vault_return_to_main() {
    git checkout main >/dev/null 2>&1 || true
  }

  # The agent has already edited vault files in the working tree on `main`. We
  # capture only docs/01_Vault/* changes, move them to a labeled branch, and
  # push without invoking unrelated drift hooks.
  CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ "$CURRENT" != "main" ]]; then
    echo "error: vault phase expects HEAD=main with vault edits in working tree (currently on $CURRENT)" >&2
    exit 20
  fi

  # Detect any vault changes: tracked edits, staged edits, or new untracked files
  # under docs/01_Vault/ (git diff alone misses brand-new files).
  VAULT_UNTRACKED="$(
    git ls-files --others --exclude-standard -- docs/01_Vault/ 2>/dev/null | sed '/^$/d' || true
  )"
  if git diff --quiet -- docs/01_Vault/ &&
    git diff --cached --quiet -- docs/01_Vault/ &&
    [[ -z "$VAULT_UNTRACKED" ]]; then
    echo "No staged, unstaged, or untracked changes under docs/01_Vault/; nothing to vault-commit."
    return 0
  fi

  # Scope guard — refuse to vault-commit if non-vault tracked changes are
  # present (staged or unstaged). Untracked files outside the vault are fine
  # because we only ever `git add docs/01_Vault/`.
  OOS_TRACKED="$(
    git diff --name-only HEAD -- . ':(exclude)docs/01_Vault' 2>/dev/null | sort -u | sed '/^$/d' || true
  )"
  if [[ -n "$OOS_TRACKED" ]]; then
    echo "error: vault phase refuses to commit; non-vault tracked changes present:" >&2
    echo "$OOS_TRACKED" >&2
    echo "Stash or commit them on a feature branch first." >&2
    exit 30
  fi

  VAULT_BRANCH="vault/post-merge-pr${PR}"
  echo "Creating vault branch: $VAULT_BRANCH"
  if git show-ref --verify --quiet "refs/heads/$VAULT_BRANCH"; then
    git branch -D "$VAULT_BRANCH" >/dev/null 2>&1 || true
  fi
  git checkout -b "$VAULT_BRANCH"

  git add docs/01_Vault/
  if git diff --cached --quiet; then
    echo "After staging, nothing to commit."
    git checkout main
    git branch -D "$VAULT_BRANCH" >/dev/null 2>&1 || true
    return 0
  fi

  # docs-only scope: pre-commit drift hooks are intentionally bypassed.
  if ! git commit --no-verify -m "docs(vault): post-merge handoff for PR #${PR}"; then
    echo "error: vault commit failed" >&2
    vault_return_to_main
    git branch -D "$VAULT_BRANCH" >/dev/null 2>&1 || true
    exit 10
  fi

  echo "Pushing $VAULT_BRANCH..."
  push_log="$(mktemp "${TMPDIR:-/tmp}/post_merge_push.XXXXXX")"
  # Bot-managed branch name: --force-with-lease updates only if the remote ref still
  # matches our last-fetched tip (avoids blind --force). If this push fails, fetch and
  # reconcile origin/$VAULT_BRANCH or delete the stale remote branch, then retry.
  if ! git push -u --force-with-lease origin "$VAULT_BRANCH" 2>&1 | tee "$push_log"; then
    if grep -qiE '(GH006|protected branch update failed|protected branch hook declined|remote: error: GH006|remote: error: protected)' "$push_log" 2>/dev/null; then
      echo "error: push rejected by branch protection on $VAULT_BRANCH" >&2
      rm -f "$push_log"
      vault_return_to_main
      exit 11
    fi
    if grep -qiE '(non-fast-forward|failed to push some refs|Updates were rejected)' "$push_log" 2>/dev/null; then
      echo "error: push rejected (non-fast-forward or conflicting remote state). Inspect $VAULT_BRANCH on origin, then delete or reset the remote branch and retry." >&2
      rm -f "$push_log"
      vault_return_to_main
      exit 12
    fi
    echo "error: push failed for $VAULT_BRANCH (see log above)." >&2
    rm -f "$push_log"
    vault_return_to_main
    exit 20
  fi
  rm -f "$push_log"

  # Open PR with vault-only label; vault-automerge.yml will validate scope and enable auto-merge.
  PR_TITLE="docs(vault): post-merge handoff for PR #${PR}"
  PR_BODY=$'Vault-only handoff updates produced by `post-merge-steward` for PR #'"${PR}"$'.\n\nThis PR is auto-merged by `.github/workflows/vault-automerge.yml` after scope validation (only `docs/01_Vault/**` may change).'

  gh_create_err="$(mktemp "${TMPDIR:-/tmp}/post_merge_gh_create.XXXXXX")"
  if NEW_PR_URL="$(gh pr create \
      --title "$PR_TITLE" \
      --body "$PR_BODY" \
      --base main \
      --head "$VAULT_BRANCH" \
      --label vault-only 2>"$gh_create_err")"; then
    rm -f "$gh_create_err"
    echo "Opened vault PR: $NEW_PR_URL"
  else
    err="$(cat "$gh_create_err" 2>/dev/null || true)"
    if grep -qiE 'label' <<< "$err"; then
      echo "warning: could not apply label vault-only; retrying PR without label (add label on GitHub for auto-merge)." >&2
      : >"$gh_create_err"
      if NEW_PR_URL="$(gh pr create \
          --title "$PR_TITLE" \
          --body "$PR_BODY" \
          --base main \
          --head "$VAULT_BRANCH" 2>"$gh_create_err")"; then
        rm -f "$gh_create_err"
        echo "Opened vault PR (unlabeled): $NEW_PR_URL"
      else
        echo "error: gh pr create failed after label retry: $(cat "$gh_create_err" 2>/dev/null || true)" >&2
        rm -f "$gh_create_err"
        vault_return_to_main
        echo "note: handoff commit may still exist on origin/$VAULT_BRANCH — open a PR manually if needed." >&2
        exit 12
      fi
    else
      echo "error: gh pr create failed: $err" >&2
      rm -f "$gh_create_err"
      vault_return_to_main
      echo "note: handoff commit may still exist on origin/$VAULT_BRANCH — open a PR manually if needed." >&2
      exit 12
    fi
  fi

  vault_return_to_main
  echo ""
  echo "Vault phase done. Auto-merge will land the PR once branch protection checks pass."
  echo "If branch protection blocks the bot, the human must merge $NEW_PR_URL."
}

case "$PHASE" in
  sync)  phase_sync ;;
  vault) phase_vault ;;
  *)
    echo "internal error: unknown phase '$PHASE'" >&2
    exit 2
    ;;
esac
