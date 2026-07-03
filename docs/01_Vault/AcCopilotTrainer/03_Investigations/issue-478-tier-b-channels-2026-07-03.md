---
type: investigation
status: active
created: 2026-07-03
updated: 2026-07-03
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
---

# #478 Tier-B channel capture (accG, yaw_rate, wheelsPressure) + tyre-set id — PR #483

## Summary

Captured the Tier-B channels the setup-aware coaching engine was already wired to confirm from but
never persisted. The "capture half" that flips `corner_attribution` rules advisory→verdict. Direct
successor to #266 (per-wheel omega/slip/temp) and the #402 tyre-set residual. **PR #483 MERGED**
2026-07-03 at `28c0fe1`; **#478 CLOSED**.

## What shipped

- **Part A — chassis dynamics.** New `chassis_read.lua` (pcall-guarded, single-source like
  `wheel_read.lua`) reads `car.acceleration` (**already in G**: `.x`=lateral, `.z`=longitudinal) and
  `car.localAngularVelocity.y` (yaw rate rad/s). `telemetry.lua` persists `accG_long/accG_lat/yaw_rate`.
  Live `telemetry_tick` now publishes real `lat_g/long_g` (were hardcoded 0 at
  `ac_copilot_trainer.lua`).
- **Part B — hot pressure.** `wheel_read.pressure` reads `wheel.tyrePressure` (dynamic, not
  `tyreStaticPressure`) → `wheelsPressure[4]` columns.
- **Part C — first-class tyre-set id.** Lap header `tyres` block (`compoundIndex` + `ac.getTyresName`)
  distinct from `setup.hash`; lakehouse `stints` split on it, canonical on the numeric compound
  **index** (name is fallback). AC exposes no per-physical-set serial to Lua.
- **Part D — weatherType** from `sim.weatherType`; flows to lakehouse `weather_type`.

`TRACE_FIELDS` 23→30, append-only after `rpm`; `_TRACE_FIELD_VARIANTS` keeps the 23-col set so older
archives load & export as blanks. All-zero column = "no live data" (never fabricates a verdict).

## CSP API facts (confirmed from the on-box SDK `ac_apps/lib.lua`)

- `ac.StateCar.acceleration` — vec3 **in G** (`@G-forces, X sideways, Z fwd/back`).
- `ac.StateCar.localAngularVelocity` — vec3 rad/s local frame; `.y` = yaw.
- `ac.StateWheel.tyrePressure` — **dynamic** hot pressure; `tyreStaticPressure` = cold.
- `ac.StateCar.compoundIndex` + `ac.getTyresName(0, idx)` — tyre compound identity.
- `acceleration`/`localAngularVelocity` NOT on the confirmed-safe list → pcall-guarded, added to
  `ac_schema.json`.

## Review hardening (4 self-hosted-reviewer rounds — all real defects, all + tests)

r1 zero-yaw false confirm + CSV false-positive + MoTeC channels; r2 turn_in_lag confirmed on *healthy*
yaw (fixed with `_turn_in_yaw_lag` heading-trails-steer proxy) + tyre-name fabrication when index
unread; r3 ±inf compoundIndex crashes `int()` ingest; r4 stint-key inconsistency (canonicalize on
index) + schema doc.

## Verification

- `make ci-fast`: 2357 passed. The lupa harness drives the **real** Lua `telemetry/wheel_read/
  chassis_read` against a car providing `acceleration/localAngularVelocity/tyrePressure` and confirms
  the trace columns; consume→verdict path tested; byte-identical Lua/Python asserted.
- Lone CI red is environmental (rig sets `AC_COPILOT_SIDECAR_SERIAL_PORT=COM6` for the #463 ESP32;
  passes unset; #478 untouches `server.py` + that test).
- **PENDING (operator-grade, not a #478 AC): live-CSP in-sim spot-check.** Deferred: the shared rig's
  AC Lua symlink points at the primary checkout, which was on `feat/issue-479` (no #478), and 12
  concurrent agent worktrees were active — repointing the shared symlink to force a drive was unsafe.
  Unblock: with #478 the active Lua (primary checkout on `main`@`28c0fe1`, or symlink at a #478
  checkout, + AC relaunch), drive a lap and confirm the newest `journal/laps/lap_*.json` carries
  non-zero `accG_long/accG_lat/yaw_rate/wheelsPressure_*` + a real `tyres` block, and a rotation/
  pressure corner reports a CONFIRMED (non-advisory) verdict.

## Follow-ups (separable, not filed)

- Prefer measured `accG_lat/long` over the `v²·κ` / `dv/dt` proxies in `lap_dynamics` segmentation
  (deferred — changes segmentation behavior; own PR).
- Test-hygiene: `test_external_bind_accepts_env_token` should null `AC_COPILOT_SIDECAR_SERIAL_PORT`
  (env-leak on the rig).
