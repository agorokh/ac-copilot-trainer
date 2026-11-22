---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/02_Investigations/post-merge-determinism-overhaul-2026-04.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Issue #327 — vault-automerge guard + build "broken": ALREADY RESOLVED (2026-06-28)

[#327](https://github.com/agorokh/ac-copilot-trainer/issues/327) closed **COMPLETED** by
`/autonomous-deliver 327` after reconciling the (stale) issue body against live state — **no code
written**, because the fix had already landed. This is a clean Closing-reconciliation-gate outcome:
the issue described a broken state that the evolved `main` no longer has.

## What #327 claimed
Two symptoms on vault-only PRs since #320:
1. `guard-and-automerge` fails in ~3s: `Unable to resolve action 'agorokh/governance-hub', not found`.
2. `build` fails on `make: *** [Makefile:8: ci-conventional] Error 1`.

## Reconciliation (live evidence)
**Symptom 1 = duplicate of #329, fixed by #330.**
- `gh issue view 329` → `CLOSED 2026-06-27T23:07:07Z` (same governance-hub regression, filed by a
  parallel autonomous session).
- `gh pr view 330` → `MERGED 2026-06-27T23:07:06Z` — fix is the fleet-bot **app-token + checkout +
  local-path `uses:`** pattern (a cross-repo `uses:` of a *private* action can't resolve with the
  default `GITHUB_TOKEN`). Present at `HEAD` (`b88791b`) in `.github/workflows/vault-automerge.yml`.

**Symptom 2 = branch-name artifact, not a defect.**
- The `build` failure occurred **only on PR #326**, pushed from `claude/gifted-diffie-9dbb3a`.
  `claude/` is not in `ALLOWED_BRANCH_PREFIXES` in `scripts/ci_policy.py`, so `ci-conventional`
  correctly rejected it. (Locally reproducible: `make ci-conventional` on any `claude/...` worktree
  branch fails the same way — a false positive, not the bug.)
- Proper vault-SAVE PRs use `vault/...` (allowed) + `docs(vault): ...` titles (conventional-valid),
  so they pass. **Do not** add `claude/` to the allowlist — that would weaken the policy. The real
  rule: vault SAVE must ship on a `vault/...` branch (post-merge skill already does this; PR #326 was
  a one-off where an autonomous session committed vault docs on its working `claude/` branch).

## Live verification — observed, not inferred
`gh pr view <N> --json headRefName,statusCheckRollup`:

| PR | branch | build | guard-and-automerge |
|----|--------|-------|---------------------|
| #326 | `claude/gifted-diffie-9dbb3a` | FAILURE | FAILURE (pre-#330 + bad branch) |
| #331 | `vault/post-merge-pr330` | SUCCESS | SUCCESS |
| #332 | `vault/issue277-resolved` | SUCCESS | SUCCESS |
| #337 | `vault/post-merge-pr334` | SUCCESS | SUCCESS (most recent; merged 2026-06-28T05:17Z) |

The outcome #327 asked for — vault-only PRs auto-merge with green `build` + `guard-and-automerge` —
is observed working on live `main`. The vault SAVE PR for *this* session is itself a fresh end-to-end
proof of the same path.

## Takeaway for future sessions
Before re-attempting a CI-regression issue, reconcile against live state: a parallel autonomous
session may have already filed+fixed the same root cause under a different number (here #329/#330).
A `claude/...` branch failing `ci-conventional` locally is expected and is not the issue under test.
