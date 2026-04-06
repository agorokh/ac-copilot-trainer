---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tests/**/*"
source: process-miner
rule_fingerprint: f65aca819ae7a1db
mined_from: 3 review comments across 1 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: architecture
---

# Test Phases Phase (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **issue (testing):** PD-02 description says "6 phases" but tests and implementation only cover 5, which makes the test misleading.

The docstring mentions “all 6 phase string literals,” but the test a...
- Test name/docstring says “six phases” (PD-02), but the assertion loop checks only 5 phase literals (and the state machine comment lists 5 states including straight). Please align the wording with what...
- PD-02 comment says the state machine has "6 phase string literals", but the test only checks for 5 phases (straight/approaching/braking/corner/exiting). Update the docstring to match the actual assert...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
