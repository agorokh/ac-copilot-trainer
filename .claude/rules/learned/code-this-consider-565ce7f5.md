---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 565ce7f550200ff5
mined_from: 4 review comments across 3 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Code This Consider (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `ac.getTrackFullID("/")` is called unguarded; if this API isn’t present in a given CSP build, this will throw “attempt to call field … (a nil value)” and reintroduce the startup crash this PR is tryin...
- Same as above: `ac.getCarID(0)` / `ac.getTrackID()` are called unguarded when building the operator-facing message. If these APIs are unavailable in some CSP builds, this helper can still throw during...
- `enableDraw3DDiagnostics` is documented as “troubleshooting only”, but it’s now enabled by default. That will emit `[COPILOT]` logs every ~2s for all users and can add noise/perf overhead; consider ke...
- `ui.deltaTime()` is called unconditionally. Elsewhere in the codebase UI APIs are treated as optional (guarded with `type(...)=="function"`/`pcall`), so this can crash on CSP builds where `ui.deltaTim...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
