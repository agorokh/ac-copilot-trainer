---
type: investigation
status: active
created: 2026-06-15
updated: 2026-06-15
relates_to:
  - AcCopilotTrainer/02_Investigations/_index.md
---

# PR-creating workflows routed through GH_PAT (fail-closed)

## Summary

Repo policy blocks the default `GITHUB_TOKEN` from `createPullRequest` and from
pushing changes under `.github/workflows/`. Three scheduled workflows that open
pull requests were therefore failing (or would fail) when run with the default
token. This investigation records the fix: route every PR-creating step through
the fine-grained PAT `secrets.GH_PAT` (already provisioned in this repo from
Doppler) and fail closed when that secret is absent.

## Affected workflows

- `.github/workflows/process-miner.yml` — "Open PR with learned rules" step.
- `.github/workflows/template-sync.yml` — `actions/checkout` (so pushes can
  include `.github/workflows` changes) and the "Create sync PR" step.
- `.github/workflows/cross-repo-mining.yml` — `learned-rules-pr` job's
  `peter-evans/create-pull-request` action.

## Fix

1. **process-miner.yml** — `GH_TOKEN` now reads `secrets.GH_PAT`; the run block
   starts with `set -euo pipefail`, a guard aborts with a clear `::error::` if
   `GH_PAT` is empty, and the `gh pr create` invocation is wrapped so a failed
   creation deletes the orphan branch instead of leaving it to accumulate.
2. **template-sync.yml** — `actions/checkout` now passes `token: secrets.GH_PAT`
   (needed so pushes can include `.github/workflows` changes and the PR can be
   created); the "Create sync PR" step switches `GH_TOKEN` to `secrets.GH_PAT`
   and adds the same fail-closed guard. The label-creation step that uses
   `GITHUB_TOKEN` purely for `gh label create` is intentionally left unchanged.
3. **cross-repo-mining.yml** — the `learned-rules-pr` job's create-pull-request
   action token switches to `secrets.GH_PAT`, and a "Verify GH_PAT is configured"
   guard step runs before it. The read-only `aggregate` job and its
   `GITHUB_TOKEN` (API reads only) are left unchanged.

## Provenance

This is the proven fleet fix, already merged and verified in
`agorokh/workstation-ops` and `agorokh/template-repo`. See
agorokh/workstation-ops#624.

`GH_PAT` was already provisioned (fine-grained PAT projected from Doppler); no
secret was created or modified by this change.
