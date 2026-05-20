---
type: investigation
status: active
memory_tier: canonical
last_updated: 2026-05-20
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Issue #108 agent-surface alignment closeout (2026-05)

## What

Campaign issue [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) asked to align five drifted canonical agent bodies to `template-repo@main` with `ProjectTemplate` → `AcCopilotTrainer` substitutions.

PR [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) merged with only `.cursor/rules/memory-contract.mdc` updated (vault invariant links corrected). The five agent files were not touched.

PR [#110](https://github.com/agorokh/ac-copilot-trainer/pull/110) originally attempted a git revert of #109; that would have restored dead `ProjectTemplate` vault paths. This PR was retargeted to **document closeout** instead: issue #108 stays **closed**; remaining agent-body alignment is **deferred** (no follow-up issue opened unless Steward re-dispatches).

## Decision

- **Keep** PR #109’s `memory-contract.mdc` fix (`AcCopilotTrainer` invariant paths).
- **Do not** revert to template placeholder paths in this repo.
- Full SHA alignment of the five agent bodies is out of scope for the closeout PR.

## Refs

- [agent-factory#199](https://github.com/agorokh/agent-factory/issues/199) § 4 Step 2 (operator close-out plan)
- [agent-factory PR #193](https://github.com/agorokh/agent-factory/pull/193) (campaign plan)
