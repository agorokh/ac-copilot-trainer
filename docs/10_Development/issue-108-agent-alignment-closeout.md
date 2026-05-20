# Issue #108 agent-surface alignment closeout (2026-05)

**Status:** Closed (campaign closeout). **Not** a vault node — per [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) acceptance (“NO vault changes”) and [PR #111](https://github.com/agorokh/ac-copilot-trainer/pull/111) scope.

## What

Campaign issue #108 asked to align five drifted canonical agent bodies to `template-repo@main` with `ProjectTemplate` → `AcCopilotTrainer` substitutions.

PR [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) merged with only `.cursor/rules/memory-contract.mdc` updated (vault invariant links corrected). The five agent files were not touched.

PR [#110](https://github.com/agorokh/ac-copilot-trainer/pull/110) attempted a git revert of #109; that would have restored dead `ProjectTemplate` vault paths. **PR [#111](https://github.com/agorokh/ac-copilot-trainer/pull/111)** documents closeout instead.

## Decision

- **Keep** PR #109’s `memory-contract.mdc` fix (`AcCopilotTrainer` invariant paths).
- **Do not** revert to template placeholder paths in this repo.
- Issue #108 stays **closed**; full SHA alignment of the five agent bodies is **deferred** until Steward re-dispatches.
- Vault handoff updates happen in a follow-up session SAVE (not in this PR).

## Refs

- [agent-factory#199](https://github.com/agorokh/agent-factory/issues/199) § 4 Step 2 (operator close-out plan)
- [agent-factory PR #193](https://github.com/agorokh/agent-factory/pull/193) (campaign plan)
