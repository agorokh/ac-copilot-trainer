---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tests/**/*"
  - "src/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: bfa64abf9a0c95bf
mined_from: 24 review comments across 13 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: typecheck
---

# Code Summary Details (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `analyzeTrace()` documents `trace` elements as only `{ throttle, brake }`, but the implementation assumes `eMs` exists (used for dt estimation and segment timing). This mismatch can cause runtime erro...
- Lua annotations for `LapTraceSample` in this module only declare `spline` and `eMs`, but `bestSpeedKmhAtSpline()` interpolates the `speed` field. This mismatch makes the contract unclear for callers a...
- `LapTraceSample.speed` is annotated as optional (`number|nil`), but `interpAtSpline()` does arithmetic on the chosen field without guarding against `nil` (`va + t * (vb - va)`), which will raise at ru...
- `guessFastLanePath()` sanitizes the track string by replacing non-[%w%.%-_] characters with “_”. That will break tracks with layouts stored as subfolders (e.g. `track/layout`), causing `content/tracks...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
