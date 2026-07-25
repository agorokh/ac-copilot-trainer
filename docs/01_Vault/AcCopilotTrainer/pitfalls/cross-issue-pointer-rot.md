---
type: pitfall
status: active
created: 2026-07-24
updated: 2026-07-24
severity: maintainability
origin: human-curated
domains: [process, backlog]
relates_to:
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/pitfalls/_index.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# Cross-issue pointer rot & phantom gates

**Project-curated** (steward sweep 2026-07-24, 12 issues, 60 dependency claims verified).
No `scope_paths` — process pitfall for backlog grooming, not code issues.

## Pattern

Cross-issue references rot in four ways, each observed this sweep:

1. **Pointer rot** — gates/acceptance targets keep naming issues that closed
   (sometimes *before* the pointing issue was filed). Damage: #625's acceptance
   target #624 closed; #534 Part C gates on "Epic #59 Phase 1" — #59 closed
   SPLIT_AND_REPLACE before #534 existed (live gate is open #117).
2. **Phantom gates** — an issue closed `completed` with unchecked boxes and
   nothing built creates dependencies on chains where every node is closed but
   the work does not exist. Damage: #119 (pedal haptics, zero firmware) closed
   "completed" → #534 Part D gates on a fully-dead chain.
3. **Delivery under a different issue** — a PR satisfies checklist items of an
   issue it doesn't name, so the owning issue never learns. Damage: #86 Part E
   shipped via #363/PR #365; Part A4 via PR #430 under the #432 lineage;
   #522's premise refuted by PR #656 (#529 P5).
4. **Frozen experimental designs** — method sections encode statistical or
   mechanistic models later evidence refutes; running them as written yields
   false conclusions. Damage: #625's n≥20/arm power math assumes the i.i.d.
   coin-flip model that #668 refuted (per-boot launch-cycle accumulator).

## Preventive rules

- On closing any issue, run an inbound-reference sweep
  (`gh search issues "<#N>" --state open`) and re-point every open issue that
  names it. Use `not_planned` + explicit successor pointer when closing
  undelivered scope — never `completed`.
- PR authors (and `/orchestrate`) comment on **every** issue whose checklist
  items the PR satisfies, not only the `Closes #N` target.
- Method sections state the model assumptions they depend on; re-validate
  against the newest investigation node before executing a prepared experiment.

## Detection

`/backlog-steward` dep-map pass: resolve every `blocked by` / gate / acceptance
target to live state; flag open issues pointing at closed targets, and closed
"completed" issues with unchecked acceptance boxes.
