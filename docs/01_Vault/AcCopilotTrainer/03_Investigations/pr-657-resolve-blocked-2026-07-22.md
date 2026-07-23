---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-22
updated: 2026-07-23
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
---

# PR #657 resolve-pr blocked (Codex limits + Actions silence)

## Finding

Resolve-pr for [#657](https://github.com/agorokh/ac-copilot-trainer/pull/657) on
`feat/issue-625-overlay-freeze-ab` cannot exit cleanly until hosted gates recover:

1. **Codex usage limits** — `@codex review` often returns quota exhausted after a full cooldown + retry.
2. **GitHub Actions** — no new `pull_request` CI/policy/conformance runs on tip SHAs after `cc83191`
   (close/reopen did not help). Other PRs on the same day still received Actions.

## Tip (keep in sync)

Current resolve tip is the PR head on `feat/issue-625-overlay-freeze-ab` (see GitHub). Landmark
commits on this branch: `8156db2` (STABLE/`--no-hold` survives failed exclusive `--json` write;
atomic exclusive report publish; Windows `list2cmdline` plan paste), `0dbd784` (Qodo fd-leak /
index / OSError / launch tests). Prefer the live PR head over short SHAs in older handoff
paragraphs.

## Evidence already in hand

- GraphQL blocking threads: 0 unresolved (pre-push rounds).
- Resolve-gate ledger: clean when last run locally.
- Local harness tests green on the tip series (156+ in resilient_launch + init_perturber_ab).
- Physical A/B run remains operator-gated by design.

## Next

1. Confirm hosted CI fires on the latest tip (branch-specific Actions delivery).
2. Fresh Codex atomic gate when quota allows.
3. Re-run `/resolve-pr 657` until CI green + Codex settled + threads/ledger clean.

## Update 2026-07-23

Tip `8c11685`: hosted CI **green**; GraphQL threads 0; resolve-gate clean. Remaining blocker is
**Codex usage limits** (no current-SHA review after `@codex review` + `sleep 600` retries). Escalated
on the PR.
