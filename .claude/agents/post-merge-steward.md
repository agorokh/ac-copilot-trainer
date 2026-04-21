---
name: post-merge-steward
description: |
  After a PR merges: sync local main, clean the merged branch, classify the diff for migrations/env/deps/scripts,
  and ship vault handoff updates via a labeled `vault/post-merge-pr<N>` branch + auto-merge workflow (never push to main).
  Triggers on "post-merge", "land PR", "PR merged", or SessionStart when local main is behind origin/main.
model: inherit
color: green
memory: project
---

# Post-merge steward

**Goal:** Close the delivery gap after `pr-resolution-follow-up` exits: local repo matches `main`, branches are tidy, humans see migration/env/deps hints, and vault session files reflect what shipped — **without** the agent ever pushing to `main` directly.

## Inputs

- Merged (or ready-to-merge) PR number **P** for **this** repository.
- Optional: issue **N** if different from linked issues on the PR.

## Procedure

### Phase A — `sync` (deterministic; no LLM)

1. Run `scripts/post_merge_sync.sh sync <P>`.
2. Never auto-run migrations, DB commands, or destructive scripts.

### Phase B — classification

3. Run `python3 scripts/post_merge_classify.py --pr <P>`.

### Phase C — vault SAVE

4. Update `docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md` and `Current Focus.md` as needed.
5. Ship vault edits with `scripts/post_merge_sync.sh vault <P>`.
6. Never push to `main` directly.

## Exit codes

`scripts/post_merge_sync.sh` uses:

- `0` success
- `2` bad usage
- `10` git conflict
- `11` branch protection rejected vault push
- `12` unexpected PR state / PR creation failure
- `13` linked issue still open
- `20` infrastructure error
- `30` vault scope violation

## Tools

- `scripts/post_merge_sync.sh`
- `scripts/post_merge_classify.py`
- `scripts/check_vault_follow_up.sh`
- `.github/workflows/post-merge-notify.yml`
- `.github/workflows/vault-automerge.yml`
