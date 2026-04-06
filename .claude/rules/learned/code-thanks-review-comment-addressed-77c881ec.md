---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tests/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: 77c881ec3c632c08
mined_from: 5 review comments across 1 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: architecture
---

# Code Thanks Review_Comment_Addressed (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `@agorokh`, thanks for the confirmation! The explicit non-empty assertions before `data[0]` / `ranking[0]` indexing will now surface a clear `AssertionError` (with a meaningful message) instead of an ...
- `@agorokh`, thanks for the fix and the dedicated test — adding `math.isfinite(f)` guard and covering it with `test_as_float_rejects_non_finite` is exactly the right approach. 

<!-- <review_comment_ad...
- `@agorokh`, thanks for the confirmation! The boolean guard and the accompanying test `test_lap_time_true_is_ignored_for_pb` are exactly the right approach here — rejecting `True`/`False` before the `i...
- `@agorokh`, thanks for the thorough fix! The implemented handling is actually more complete than my original suggestion — the `PermissionError` catch and the `{e.filename!r}` / `at char {e.pos}` addit...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
