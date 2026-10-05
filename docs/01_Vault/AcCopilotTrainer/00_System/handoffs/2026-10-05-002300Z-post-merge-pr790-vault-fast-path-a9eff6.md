---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-05
updated: 2026-10-05
last_updated: 2026-10-05T00:23:00Z
pr: https://github.com/agorokh/ac-copilot-trainer/pull/790
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Workflow OS.md
  - AcCopilotTrainer/00_System/glossary/ci-fast.md
---

# Post-merge PR #790: vault-only PRs run `make ci-vault`

## Resume here

1. Nothing is owed in this repo. The product focus in `Current Focus.md` is unchanged.
2. The PR that ships this node is the first real vault-only PR through the fast path. Its
   `build` job must log `full-build=false (every changed path is under docs/01_Vault/)`, skip
   `make ci-fast` and run `make ci-vault`. The result is recorded on governance-hub#701.
3. `build` is not a required check yet. Making it required is a repository setting and is
   decided on governance-hub#701, not here.

## Shipped

- PR #790 squash-merged at vetted head `bb32cbe4119668d063e8dd1342aa6450b9a641ee`; merge commit
  `a9eff6965b9070f7c6661f18a791d0b709404e42` at 2026-10-05T00:22:23Z. Author vendor `anthropic`.
- Review on the vetted head: the self-hosted reviewer's `antigravity` and `grok` lenses, no
  findings at or above medium. The `cursor` lens did not run (quota) and `kimi` did not review.
  Zero review threads. Checks green: `build`, `Canonical docs exist`, `conformance`, `pip-audit`.
- `build` on the PR took the full path: `full-build=true (8 changed path(s) outside
  docs/01_Vault/)`, `make ci-fast` 306s, `4133 passed, 76 skipped` (main before it: `4110 passed,
  76 skipped`; the same 76 skips).

## What changed

- `.github/workflows/ci.yml`: a `Classify PR scope` step (`id: scope`, no `if:`) right after
  checkout. `make ci-fast` is gated on `steps.scope.outputs.full-build != 'false'`, `make
  ci-vault` on `== 'false'`. The install step is unchanged and runs on both paths. The job has
  `pull-requests: read`; the token goes to the scope step only.
- `.fleet-governance-vendor/scripts/classify_pr_scope.py`: the governance-hub classifier,
  vendored unchanged. This repo is public and cannot resolve the private hub action.
- `tests/test_vendored_classifier_pin.py`: SHA-256 pin of that file. The same hash is written
  in the workflow step as `CLASSIFIER_SHA256`.
- `tests/test_ci_vault_fastpath.py`: the wiring contract, plus tests that run the step's own
  shell script against a local stub of the pull request API.
- `Makefile`: `ci-vault: ci-conventional ci-secrets ci-policy`, then pytest on `VAULT_TESTS`
  (eight traced vault readers and the pin test).
- `pyproject.toml`: `.fleet-governance-vendor/` joins ruff's `extend-exclude`.

## Rules to keep

- A test that starts reading live vault notes joins `VAULT_TESTS`. A missed one still runs on
  every code PR, so it fails late, not never.
- Re-vendoring the classifier means updating two pins together: the test and the workflow.
- The scope step runs the pull request's copy of the classifier, because a vendored script lives
  in the workspace. It is safe only while all three hold: it runs before any step that installs
  or runs PR code; it refuses a file whose hash is not the workflow's pin; it runs Python with
  `-I`, so a module planted beside the script cannot shadow the standard library. The contract
  test fails if any of the three is removed.
- A PR that edits `.github/workflows/ci.yml` itself can make `build` do anything. That was true
  before and no check in the job can prevent it. Review workflow changes.

## Phase B classification

- `pyproject.toml` changed (ruff exclusion only; no dependency change).
- `.github/workflows/` changed: one job gained `pull-requests: read`; no secret is used.
- `Makefile` changed: new target `ci-vault`, noted in `AGENTS.md`.

## Noticed, not changed

- `template-sync.yml` has failed at its `Copier update` step on each of its last four weekly
  runs (2026-09-09 to 2026-09-30).
