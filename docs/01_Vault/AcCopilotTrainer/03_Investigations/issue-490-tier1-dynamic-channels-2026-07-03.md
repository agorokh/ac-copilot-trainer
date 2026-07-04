---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-03
updated: 2026-07-03
issue: https://github.com/agorokh/ac-copilot-trainer/issues/490
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-478-tier-b-channels-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/telemetry-capture-surface-for-ml-2026-07-03.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Issue #490 — Tier-1 base-AC dynamic channels (PR #492, rig-verified)

**Merged:** squash [`73ebe82`](https://github.com/agorokh/ac-copilot-trainer/pull/492) (2026-07-04). EPIC #488 Part A, Tier 1.

## What shipped

Appended **46 append-only trace columns** (30 → **76**) to the lap-archive trace — all **base-AC shared memory** via CSP Lua `ac.getCar().wheels[i]` / car state, **no CSP extended physics**. Per-wheel (FL/FR/RL/RR): `tyreTempInner/Mid/Outer` (°C), `brakeTemp` (°C), `wheelLoad` (N), `tyreWear`, `tyreDirty`, `camber` (deg), `suspTravel` (m), `damperVel` (m/s, derived d/dt). Car scalars: `rideHeightFront/Rear`, `brakeBias`, `turboBoost`, `fuel`, `accG_vert` (completes the g-cube with #478).

Capture: `wheel_read.lua` / `chassis_read.lua` new pcall-guarded accessors (SDK-grounded), `telemetry.lua` wiring + damper d/dt derive, `lap_archive.lua` ⟷ `reference_lap.py` byte-identical (76). Analysis: `lap_dynamics.LapTrace` tyre bands + camber; `corner_attribution` cross-tread gradient → `camber_pressure_imbalance` **verdict** rule; `lap_archive_export` CSV/DuckDB (samples auto-widens).

## Grounded corrections to the issue body (CSP lua-sdk `ac.StateWheel`/`ac.StateCar`)

- **camber is DEGREES** (CSP `camber`), not base-SM `camberRAD` radians — column stores degrees, documented.
- **brake temp = `discTemperature`** (no CSP `brakeTemp` field).
- accG_lat/long, yaw_rate, wheelsPressure were **already** captured by #478/#483 — only `accG_vert` (vertical axis) was genuinely new.

## Rig verification (operator-grade, 2026-07-04)

Real Magione lap, 911 GT3 R, `auto_drive --driver ggv --wait-lap`: PASS (208.7 km/h, gear 6, 2504 m, clean hijack). Archive = 76-field trace, 2000 samples. Evidence bundle `.scratch/harness-evidence/issue-490-verify/`.

- **41/46 columns carry real dynamic values** — tyre bands 53–79 °C (real cross-tread gradients), wheelLoad 0–13.5 kN, camber mean −3°, suspTravel 0.003–0.045 m, **damperVel ±0.6 m/s (Lua d/dt derive validated)**, rideHeight rake, accG_vert −1.3..+2.7 G, brakeBias 0.68, fuel 30 L, tyreDirty real.
- **5 zeros are correct-for-context**, NOT wrong field names: `tyreWear`=0 (fresh tyres on an out-lap), `turboBoost`=0 (911 GT3 R is naturally aspirated).
- DuckDB `samples` auto-widened to **80 cols** (76 trace + 4 identity); #490 cols queryable; older 30-col archives coexist with NULL (NULL-aware `avg` matched the lap exactly).
- Attribution: `corner_live_signals` emitted `tyreCrossGradient` on **all 5 real corners** (verdict correctly no-fires at peak 4.7 °C < 7 °C threshold; unit test fires at 15 °C).

## Caveat / follow-up

**`brakeTemp` (`discTemperature`) read a constant 26 °C (ambient)** across a hard-braking lap — accessor correct, but brake-disc heating appears **base-physics-inactive** for this car. Follow-up: confirm whether any base-AC car heats `discTemperature`, or whether it is extended-physics-gated (would move brake-temp to #488 Tier 2). Non-blocking; the channel is captured.

Tyre-wear as an ML target still needs the AC wear-scale convention documented (issue #490 pitfall) before use.
