---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 326b6027dcbe5870
mined_from: 4 review comments across 1 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: architecture
---

# Current Code Speed (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `realtimeCoaching.tick()` is fed `lastLapCornerFeats` (features from the previous completed lap) rather than any current-lap telemetry, so “real-time” hints will reflect last lap’s entry/min speeds in...
- `buildRealTime()` only compares **last-lap** corner features vs **best-lap** features; it doesn’t use any current-lap telemetry (e.g., current speed on approach). That means the “real-time” hint won’t...
- The realtime coaching tick currently generates hints solely from `state.lastLapCornerFeats` vs `state.bestCornerFeatures`. That means hints during lap N are based on lap N-1 performance and won’t reac...
- ## Code Review

This pull request implements a real-time per-corner coaching engine, utilizing a state machine and a bucket-based lookup system for efficient track segment tracking. It adds real-time ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
