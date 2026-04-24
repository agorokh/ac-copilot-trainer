---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: bug
scope_paths:
  - "docs/**"
  - "**/vault/**"
  - "**/*state*"
  - "**/*config*"
  - "**/pipeline/**"
domains: [trading, legal, gaming]
canonical_prs:
  - repo: agorokh/ac-copilot-trainer
    prs: [38, 35]
    note: Session-exit persistence never runs, next session reuses stale state
  - repo: agorokh/disclosures-discovery
    prs: [135]
    note: ON CONFLICT DO UPDATE overwrites description despite PR constraint saying provenance-only
  - repo: agorokh/alpaca_trading
    prs: [780]
    note: Architecture health score arithmetic inconsistent between sections
relates_to:
  - AcCopilotTrainer/pitfalls/vault-path-integrity.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# State consistency

**4 clusters, 44 comments, 3 repos**

## Pattern

Document/config state drifts from code state. The implementing agent modifies one representation (code, config, or doc) without updating the others, creating contradictions that confuse subsequent agents and users.

Most common forms:
- Vault handoff docs reference wrong PR numbers or deleted branches
- `ON CONFLICT DO UPDATE` clauses overwrite fields the PR explicitly said must not change
- Calculated values in docs don't match the formula in code
- Session state persisted at wrong lifecycle point (e.g., before completion)

## Preventive rule

When modifying state or config, the acceptance criteria MUST include:
1. **Document current state** -- what the value IS before the change
2. **Specify mutation scope** -- exactly which fields change and which MUST NOT change
3. **Assert preservation** -- a test or check that verifies unchanged fields stay unchanged after the operation
4. **Lifecycle correctness** -- state persistence happens AFTER the operation completes, not before or during

## Canonical damage

In `ac-copilot-trainer` PR #38, `persistSnapshot()` was called on the first main-menu frame (before the session started) but not on session exit. The next session loaded stale state from the previous-previous session, causing coaching hints to reference wrong track data.
