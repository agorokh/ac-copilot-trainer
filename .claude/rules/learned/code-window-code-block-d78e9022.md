---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: d78e902214cec4e8
mined_from: 27 review comments across 14 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: typecheck
---

# Code Window Code_Block (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `bestCornerFeatures` is now persisted/loaded in `ac_copilot_trainer.lua`, but `normalizeLoaded()` doesn’t validate/coerce it like the other new v3 fields. For schema hygiene (and to avoid surprising t...
- `guessSetupIniPath()` flattens the track identifier with `gsub("[^%w%.%-_]+", "_")`, which can break setup resolution for tracks with layout subfolders (e.g. `track/layout`), since the actual setups p...
- With `lastTry` initialized to 0 and the reconnect guard `t - lastTry < RECONNECT_SEC`, the first connection attempt won’t happen until ~5s after session start (when `sim.time` reaches 5). If you want ...
- `math.floor(bestLineN / 2)` can be 0 when `bestLineN` is 1, so `line[mid]` won’t log even though data exists. It’s also not the true midpoint for odd lengths (e.g., 3 → 1). Consider using a 1-based mi...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
