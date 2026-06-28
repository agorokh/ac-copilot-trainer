---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/345
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/03_Investigations/pr-309-lap-archive-finalization.md
---

# Coaching lakehouse (DuckDB over the lap-archive corpus) — #344 / #345 P1

## Summary

Shipped `tools/coaching_lake` — an embedded **DuckDB** star schema built
idempotently from the immutable per-lap JSON corpus
(`journal/laps/lap_*.json`). This is the P1 "query the whole data plane" engine
from EPIC #344: the coach can now ask cross-lap trend/dependency questions that
no single lap can answer (e.g. *does +1° front wing improve T1 apex speed across
all my Spa laps and conditions?*).

The DuckDB file is a **derived, disposable** view — rebuilt from JSON; the JSON
is never mutated (data-immutability invariant). No server, single pip wheel,
Windows + py3.11 native.

## Schema (star)

- `laps` — lap grain (car_id, track_id, conditions, setup_hash, lap_ms, is_valid…)
- `corners` — corner grain (entry/min/exit speed, brake point, trail-brake…)
- `setup_params` — tall bridge (lap_uuid, param, value) for setup×outcome joins
- `samples` — telemetry grain; columns = `reference_lap.TRACE_FIELDS` (byte-identical invariant)

`REPORTS` registry: `summary`, `best-laps`, `corner-speed`, `tyre-temps`, and the
flagship `setup-effect` dependency query. `run_query()` runs arbitrary SQL.

## Performance fix

First cut used `executemany` for samples — pathologically slow (row-by-row;
timed out at 2–4 min on 375k rows). Fixed: laps/corners insert inside one
transaction; **samples bulk-load via temp-CSV → vectorized `COPY`**. Full build
now **46s offline** (not on the realtime path).

## Operator-grade verification (real corpus, not synthetic)

Built against the live corpus and read the rows back:

- **213 laps / 11 tracks / 702 corners / 375,103 samples**, build exit 0 in 46s.
- `best-laps`: per-track counts + best/median (magione 118 laps, vallelunga best
  45.869s, red_bull_ring 10 laps best 83.737s…).
- `corner-speed`: per-track per-corner apex/exit averaged across laps.
- ad-hoc SQL (`fastest lap per track`) returns real data.

## Known data-quality gaps (→ P0 #345 capture half)

- `cars=1` — all laps collapse to `function_0xff`: `persistence.tryCarFromCar`
  reads `car.id` (a CSP **function**) and `tostring()`s it. Fix = guard to
  strings so the `safeCarIdRaw()`/`ac.getCarID(0)` fallback runs. **Rig-gated.**
- `setup_params=0` — setup snapshot not captured at archive time (P0).
- Some older sessions have null tyre channels (pre-trace archives).

These are capture-side (Lua, rig-gated), tracked under #345; the lake reads
whatever the corpus holds, so they light up automatically once capture lands.

## Delivery

- 9 off-sim tests (synthetic archives, no rig) incl. the setup×corner flagship.
- `analytics` extra (`duckdb>=1.4`) wired into `.github/workflows/ci.yml` so the
  test runs in CI and `build_analytics` counts toward `--cov-fail-under=80`.
