---
type: decision
status: active
created: 2026-04-10
updated: 2026-04-10
id: ADR-SHIFT-LEFT
area: agent-os
memory_tier: canonical
issue: https://github.com/agorokh/template-repo/issues/74
relates_to:
  - AcCopilotTrainer/02_Investigations/process-miner-corpus-analysis-2026-04.md
  - AcCopilotTrainer/01_Decisions/self-hosted-pr-agent-baseline.md
  - AcCopilotTrainer/01_Decisions/local-reviewer-model.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Shift-left: issue creation as the primary quality lever

## Problem

PR iteration cycles average 8 commits and 50-70 bot comments per PR (sometimes 250+ comments and 20+ commits). The cost is:
- **Token cost:** each cycle burns tokens across 6-7 review bots + the implementing agent
- **Wall-clock:** hours of CI + bot review + agent fix + re-push per iteration
- **Attention:** user must decide when to merge, with diminishing returns per cycle

Root cause (proven by corpus analysis, April 2026): implementing agents (Cursor Auto, unknown model) make the same conceptual mistakes repeatedly across PRs because:
1. Issues don't warn about known pitfalls in the affected code area
2. The implementing model is cheaper/smaller and doesn't infer constraints from codebase context
3. Review bots catch the mistakes AFTER implementation — the most expensive correction point

## Decision

**Front-load mined recurrence patterns into issue creation.** The issue writer agent (upgrade from stub, #74) reads:

1. **Vault invariants** — architecture rules that never change
2. **Mined pitfalls** — recurring implementation mistakes from the process miner (semantic clusters with `distinct_pr_count >= 3`)
3. **File-path context** — which pitfalls apply based on the files the issue is likely to touch

And produces a structured issue with a **"Known pitfalls"** section: 3-5 bullets, each one paragraph, always citing the canonical PR where the mistake caused real damage.

### Issue structure (target format)

```markdown
## What
[One paragraph: what needs to change and why]

## Acceptance criteria
- [ ] GIVEN ... WHEN ... THEN ...
- [ ] GIVEN ... WHEN ... THEN ...

## Known pitfalls in this area
- **Silent exception swallowing** — Any `except` clause in streaming/async
  code MUST log with `logger.exception()` and re-raise or narrow to specific
  types. We had a kill-switch bypass in PR #751 caused by bare `except ValueError`
  hiding DB connection errors.
- **Doppler secrets** — This repo uses Doppler for all secrets. Never read from
  `.env` directly. Use `doppler run --` or the DISTILL_API_KEY pattern.

## Implementation notes
[Optional: suggested approach, relevant files, architectural constraints]
```

### Why this structure works

1. **"Known pitfalls" is the shift-left payload.** It's the ONLY section that doesn't exist in current issues. The implementing model reads it and avoids the mistake on first pass.
2. **PR citations make it stick.** Cheaper models respect concrete examples ("PR #751 broke the kill switch") more than abstract rules ("ensure proper error handling").
3. **3-5 bullets, not a novel.** Cursor Auto (small model) will skim long issues. Short, specific, anchored bullets survive the attention window.
4. **File-path scoping prevents irrelevant noise.** A pitfall about `agent/streaming/**` doesn't appear in an issue touching `analytics_ui/**`.

### Metric

**Target:** commits-to-green per PR drops from 8 average to 5 within one week at constant velocity.

**Tracking:**
- `distinct_commit_count` per merged PR (already in miner cache)
- `distinct_pr_count` / breadth of recurring patterns after pitfall injection (should decrease)
- `first_pass_green_rate` — % of PRs that pass all bots on first push

### What this does NOT do

- Replace any existing review bot. Bots become confirmation, not iteration.
- Train a local model. That's #26, deferred until this loop proves data quality.
- Remove the need for frontier model distillation. The miner still needs to find patterns; the issue writer still needs to format them.

## Architecture: how mined patterns flow into issues

```text
collect (GitHub API)
  → analyze (semantic cluster via sentence-transformers)
    → aggregate (cross-repo; rank by comment mass and distinct_pr_count)
      → distill (frontier model: conceptual_mistake + preventive_rule + citations)
        → pitfalls/ vault directory (curated rules, file-path scoped)
          → issue writer agent reads pitfalls/ + invariants/
            → structured issue with "Known pitfalls" section
              → implementing agent reads issue, avoids mistake on first pass
```

Each stage is implemented or in progress:
- collect/analyze/aggregate: done (PR #75, #76, #77)
- semantic cluster: done (PR #81)
- distill v2: done (PR #81)
- **pitfalls/ directory: done** — 7 curated rules from fleet scan (597 clusters, 9 repos)
- **issue writer upgrade: done** — hub-spoke fetch via `.claude/pitfalls-hub.json`
- **validation (field test):** steps 2–5 of the validation plan below are still open; step 1 (pitfall curation) is complete

## Consequences

1. Issue creation takes longer (miner lookup + formatting) but saves 3-5x in iteration cost.
2. The pitfalls/ directory becomes a living artifact that agents must maintain. Stale pitfalls are worse than no pitfalls.
3. The miner-to-issue pipeline is the core value loop of the "agent OS." If this works, every improvement to mining directly improves every PR across the fleet.

## Validation plan

1. **Pitfall curation (complete):** 7 families from 597 semantic clusters (PR #82); replaces the earlier “hand-curate 10–15 rules” draft step.
2. Write ONE issue for `ac-copilot-trainer` with the new structure + pitfalls section (hub fetch)
3. Ship it via Cursor Auto, measure commits-to-green vs rolling average
4. If metric moves, automate the mining → pitfalls pipeline
5. If metric doesn't move, the mechanism isn't issue-authoring — investigate other levers
