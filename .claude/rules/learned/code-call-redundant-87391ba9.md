---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 87391ba9a18d356d
mined_from: 3 review comments across 1 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: typecheck
---

# Code Call Redundant (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `aliases` dictionary is static and should be defined as a module-level constant to avoid re-allocation on every call to `_no...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `str(k)` call is redundant as keys from a JSON-loaded dictionary are already strings.

```suggestion
            nk = _norma...
- > Remove redundant local import of `extract_corner_table` (already imported at module level).

Addressed: Dropped the inner import in `test_extract_corner_table_ignores_unknown_and_malformed`. Pushed ...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
