---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "scripts/**/*"
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 4f8a18ebc1883198
mined_from: 25 review comments across 14 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Code This Comments (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `snapToTrack()` accesses `hit.position.y` directly when `hit` is a table. If `hit.position` is a userdata (common for vec3-like types) or has a metamethod that throws on `.y`, this will error outside ...
- This test name is misleading: `tools.ai_sidecar.server` can be imported even when `websockets` is missing (the import happens inside `_run`). Either rename the test to reflect what it checks, or chang...
- `lastTry` starts at 0, so with `sim.time` starting near 0 this prevents the first connection attempt for ~5 seconds (`t - lastTry < RECONNECT_SEC`). If the goal is to connect ASAP when configured, ini...
- `configure()` clears `sock` but doesn’t reset `lastTry`, so changing `wsSidecarUrl` at runtime can delay reconnect attempts for up to `RECONNECT_SEC`. Reset `lastTry` in `configure()` (or trigger an i...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
