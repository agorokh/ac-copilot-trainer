---
type: investigation
status: active
created: 2026-06-12
updated: 2026-06-12
relates_to:
  - AcCopilotTrainer/03_Investigations/pr-75-ollama-corner-coaching-protocol.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
---

# Lua coaching logic is testable WITHOUT AC via synthetic telemetry-trace replay

## Question
How far can the Lua coaching logic run under lupa, off a synthetic/recorded
telemetry frame stream, with NO Assetto Corsa and NO live `ac.*`/`ui.*`/`physics.*`?

## Finding (confirmed empirically under lupa 2.8)
The five coaching-logic core modules are **pure functions of plain Lua tables** —
they reference `ac.*`/`sim.*`/`os.*` only in luadoc comments, never as runtime calls:

- `corner_analysis.lua`, `delta.lua`, `coaching_hints.lua` — ZERO global refs.
- `realtime_coaching.lua` — `M.tick(opts)` takes a plain opts table; only `os.` ref
  is a comment ("no os.time dependency"). `wsBridge` is duck-typed via `opts.wsBridge`.
- `telemetry.lua` — `:update(dt, car, sim)` reads plain fields off `car`/`sim`;
  only real dep is `require("csp_helpers")` → `simSeconds(sim)` which reads
  `sim.gameTime`/`sim.time` via pcall (works on a mock table). No `ac.*` shim needed.
- `brake_detection.lua` — `:update(car, dt)` on a plain table; only external call is
  `math.atan2` (LuaJIT/5.1) for heading.

**A mock `ac.*` shim is NOT required for these modules.** They only need plain-table
`car`/`sim`/`opts`/`trace` inputs — i.e. a "telemetry-trace replay" feeder.

## Proof (ran, all passed)
Under lupa with package.path → modules/, fed synthetic frames:
- brake_detection: emitted brake event on release, entrySpeed=180, spline=0.20.
- realtime_coaching.tick: "BRAKE NOW" (kind=brake, target=100, dist~10m) and
  "CARRY MORE SPEED" (in_corner) from synthetic opts.
- corner_analysis.buildSegments + delta.deltaSecondsAtSpline: full pure pipeline.
- telemetry:update: 50 frames ingested with plain car/sim tables.

## Pitfall: lupa binds Lua 5.5, CSP runs LuaJIT (5.1)
`math.atan2` was removed in Lua 5.3+; lupa 2.8 binds Lua 5.5 → `brake_detection`
throws `attempt to call a nil value (field 'atan2')` on `:update`. CSP/LuaJIT HAS it.
Fix: one-line parity shim in the harness:
`if not math.atan2 then math.atan2 = function(y,x) return math.atan(y,x) end end`.
The current `tests/test_lua_runtime_smoke.py` never hit this because it only calls
`require()`, never `:update`. The replay layer (which calls `:update`/`tick`) must add
this shim; recommend a `csp_luajit_parity.lua` helper to keep harness/CSP in sync.

## Proposed layer: tests/test_lua_trace_replay.py
A pytest module that (1) installs the LuaJIT-parity shim, (2) loads each pure module,
(3) feeds a fixture trace (reuse the columnar lap_archive format:
fields = spline,speed,eMs,throttle,brake,steer,gear,px,py,pz), (4) asserts brake
points / segments / delta / viewmodel outputs. This is the no-human inner loop:
the agent generates/perturbs traces and asserts coaching outputs deterministically,
with zero AC, zero Windows box, zero WebSocket.
