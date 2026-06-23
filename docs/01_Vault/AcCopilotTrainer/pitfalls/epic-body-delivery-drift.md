---
type: pitfall
status: active
created: 2026-06-22
updated: 2026-06-22
severity: maintainability
origin: human-curated
domains: [process, backlog]
relates_to:
  - AcCopilotTrainer/pitfalls/redundant-code-drift.md
  - AcCopilotTrainer/pitfalls/_index.md
  - AcCopilotTrainer/02_Investigations/process-miner-corpus-analysis-2026-04.md
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# EPIC body delivery-drift (the re-rake trap)

**Project-curated** (not fleet-mined — no cluster/comment metadata). Surfaced by a
`/backlog-steward` intent-vs-delivery sweep on 2026-06-22.

> Deliberately carries **no `scope_paths`** — this is a process pitfall about *issue/EPIC
> tracking*, not a code-path mistake, so the issue-writer must **not** inject it into every
> code issue. It is meant to be read during backlog grooming / steward runs.

## Pattern

A long-lived `[EPIC]` issue with labeled Parts (A–G…) keeps its **original body** while Part
after Part ships under separate PRs. The body still reads as all-future work; the merged
delivery lives only in PR titles, the vault handoff, and the code. Re-reading the EPIC weeks
later, an agent (or the operator) takes the body at face value and **re-attempts work that
already shipped in a different shape** — *stepping on a rake.* The cost is highest precisely on
the EPICs that succeeded fastest, because those accumulated the most undocumented delivery.

The tell: the EPIC's `updated_at` moves (label tweaks, comments) but the **body's
delivered/remaining split never moves**. Age is not the signal — *un-reconciled delivery* is.

## Canonical damage

- **`ac-copilot-trainer#154`** — "[EPIC] Autonomous self-test harness". Parts A–G all shipped
  across ~12 PRs (#157, #158, #173/#182/#185, #191/#201/#209/#221/#226, #176/#229/#233,
  #236/#239/#242 + the #244 racing-controller sub-program) and **L2 was live-verified** in
  PR #196 (agent drove a no-human lap; trainer coached it in real time). The body still framed
  every Part as future work until reconciled by `/backlog-steward` on 2026-06-22. Contrast
  **`#86`** (rig-screen EPIC), which carried a "Delivered / No Longer Active" section from the
  start and never drifted — the working antidote.

## Preventive rule

1. **Reconcile the EPIC body at each Part merge**, not at the end. The merging PR (or the
   `/post-merge` step) should check off the delivered Part in the EPIC body with its PR number,
   the same turn it lands. A one-line edit beats a months-late audit.
2. **Every EPIC keeps a `## Delivered / No Longer Active` section** with PR evidence, and a
   `## Current Scope After Reconciliation` that lists only what is genuinely open (prefer links
   to child issues over re-stated scope). Model it on `#86`.
3. **Before re-picking up any EPIC or its child, run `/backlog-steward`** (or at minimum diff
   the body against merged PRs). The steward's reconciliation ledger
   (`.scratch/backlog-steward/ledger.json`) exists to make this cheap on the next pass.
4. **The verdict, not the merge, owns the status.** A merged Part-PR that only partially
   delivers must be recorded as `partially-delivered`, not silently checked off — otherwise the
   body lies in the other direction.

## Detection

- `/backlog-steward` flags an EPIC as `partially-delivered` when ≥2 merged PRs name its Parts
  but the body shows no delivered section — exactly how `#154` was caught.
- Cheap manual check: `gh pr list --state merged --search "<epic-#> in:title,body"` vs the
  EPIC's checkbox state.

## Upstream candidate

EPIC-body delivery-drift is **domain-agnostic** — it applies to any repo that runs large
labeled-Part EPICs. Per the upstream-template-sync rule (`.claude/rules/workflow.md`), this is
a candidate to propagate into the **template-repo hub** `pitfalls/` so the whole fleet's
issue-writer and steward can surface it. Operator decision; not auto-propagated.
