---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "docs/**/*"
  - "tools/**/*"
  - "src/**/*"
source: process-miner
rule_fingerprint: 142f6bb6506a509c
mined_from: 36 review comments across 16 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: guideline
---

# Code With This (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ### Marker budget shrinks visible brake points

**Medium Severity**

<!-- DESCRIPTION START -->
With `hasDebugLine`, `primitivesPerMarker` is set to `5` while `MAX_DEBUG_PRIMITIVES` stays `150`, so `m...
- ### Budget undercounts legacy sphere draws when debugSphere unusable

**Low Severity**

<!-- DESCRIPTION START -->
The budget condition on line 167 uses `(hasLegacyDrawSphere and not hasDebugSphere)` ...
- > The `float(regret)` call is redundant as `regret` is already a float.

Addressed: Use `round(regret, 4)` for `priority`.
- > `_run_compare_laps` should catch file/JSON errors and exit with a clear message.

Addressed: Wrapped reads and `json.loads` in `try/except` for `FileNotFoundError`, `PermissionError`, `JSONDecodeErr...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
