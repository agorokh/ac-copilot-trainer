---
type: investigation
status: complete
created: 2026-10-05
updated: 2026-10-05
issue: "https://github.com/agorokh/governance-hub/issues/711"
relates_to:
  - AcCopilotTrainer/02_Investigations/2026-09-07-repin-vault-automerge-78a47069.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Re-pin vault-automerge hub action to db8b63c6 (2026-10-05)

PR #793 (squash `40981bbb`) moved the governance-hub `vault-automerge` pin from `78a47069` to
`db8b63c6`, the commit the hub's `hub_pin_drift.py` names as current for the action. Part of the
fleet roll in governance-hub#711.

## What changed here

- `.github/workflows/vault-automerge.yml` line 50: the `actions/checkout` `ref:` (this repo uses
  the checkout shape, so the `ref:` is the pin).
- `tests/test_vault_automerge_workflow.py`: `HUB_ACTION_REF`, which asserts the same SHA.

No caller input changed. Upstream added one optional input (`queue-guarded-admission`, default
`"false"`) and removed none. This repo has no merge queue.

## What the new pin brings

- governance-hub#584: the gate's findings-history fetch is authenticated. This repo is public, so
  the unauthenticated fetch that broke private repos at `78a47069` did not fail here.
- governance-hub#622: a vault PR whose `Refs #N` GitHub would close is refused.
- governance-hub#641, #669, #671: patch parsing, replay budget, merge-queue handling.

## Why this repo went early

It is the fleet's only public repo on a GitHub-hosted runner, and it calls the action through a
local checkout rather than `uses: owner/repo@sha`. The fleet canary (agent-factory) is private,
self-hosted and uses the other shape, so it proved nothing about this one. This note's own PR is
the first live run of the new pin here.

## Rollback

Revert `40981bbb`. It restores `78a47069` in both files.
