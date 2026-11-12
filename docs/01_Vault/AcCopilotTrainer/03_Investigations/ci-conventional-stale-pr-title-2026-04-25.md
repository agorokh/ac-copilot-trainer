---
type: pitfall
status: active
created: 2026-04-25
updated: 2026-04-25
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# CI `ci-conventional` fails after PR title rename — stale event payload

## Symptom

`make ci-fast` step `ci-conventional` (driven by `scripts/ci_policy.py`) fails on a fresh PR with:

    ci_policy: PR title must follow conventional commits, e.g. 'feat: add parser', 'fix(scope): handle edge case', 'chore: bump deps'.
    make: *** [Makefile:8: ci-conventional] Error 1

…even though `gh pr view <N> --json title` returns a title that obviously matches the conventional-commits regex (e.g. `feat(screen): Phase-2 LVGL bring-up + UI scaffold (issue #86 Part A)`).

## Root cause

The PR was opened with a non-conventional title (often the linked issue's title, e.g. `[EPIC] Rig screen Phase-2 UI — App launcher + 3 custom app screens (...)`) and **renamed** to a conventional form *after* the workflow had already triggered. GitHub Actions captures the `pull_request` event payload at trigger time and writes it to `GITHUB_EVENT_PATH`; renaming the PR does **not** re-fire the workflow. `scripts/ci_policy.py` reads `event["pull_request"]["title"]` from that frozen payload, so it sees the original (non-conventional) title even though the live title is now valid.

This is observable from the timeline:

    gh api repos/<owner>/<repo>/issues/<N>/timeline \
      --paginate -q '.[] | select(.event=="renamed") | {actor, created_at, from, to}'

If the `created_at` of the rename is *after* the failed CI run started, the rename caused the false-positive failure.

## Fix

Push another commit (any change) to the branch — that creates a fresh `synchronize` event, and the workflow's new payload sees the corrected title. **No need to revert the rename or close+reopen the PR.**

For autonomous runs: when the orchestrator is about to file a PR for an issue, it should set the PR title to a conventional form on `gh pr create` rather than letting `gh pr create` auto-derive from the issue title. Pattern:

    gh pr create --title "feat(scope): short imperative" --draft ...

## Why this isn't a bug in `ci_policy.py`

The script is correct — it's enforcing the contract on whatever payload Actions hands it. The mismatch is a known GitHub Actions semantic (the `pull_request` event is "frozen" snapshot semantics, not live-state semantics).

## See also

- [`AcCopilotTrainer/00_System/Next Session Handoff.md`](../00_System/Next%20Session%20Handoff.md) — PR #91 captured this pitfall in flight.
- `scripts/ci_policy.py` lines 60–68 (regex + error message).
- [`AGENTS.md`](../../../../AGENTS.md) — branch + title naming conventions.
