---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "src/**/*"
source: process-miner
rule_fingerprint: 969092cf2dfafb47
mined_from: 11 review comments across 6 PRs
last_updated: 2026-05-04
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: guideline
---

# Code Only Code_Block (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- > `_as_float` should reject booleans like `_positive_lap_time_ms` so JSON `true` is not treated as `1.0`.

Addressed: Added `isinstance(v, bool)` guard in `_as_float` and `test_as_float_rejects_bool`....
- `findNextBrakeOrCorner()` forces `d` to 1 when `entry.s0 == sp` (`if d < 1e-9 then d = 1 end`). That makes the “next” segment appear a full lap away exactly at a brake/corner boundary, which can preve...
- `script.update` calls `wsBridge.tick()` and then `wsBridge.startSidecarIfNeeded()` every frame. Since `wsBridge.tick()` already attempts `tryOpen()` on its 5s cadence when `sock` is nil, `startSidecar...
- The EmmyLua annotations for `archiveCarIdFromCar` / `archiveTrackIdFromSim` declare `car`/`sim` as `table|nil`, but the functions are designed to accept CSP `ac.StateCar` / `ac.StateSim` userdata (the...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
