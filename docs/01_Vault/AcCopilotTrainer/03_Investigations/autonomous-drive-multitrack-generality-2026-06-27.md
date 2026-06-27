---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-27
updated: 2026-06-27
issue: https://github.com/agorokh/ac-copilot-trainer/issues/154
relates_to:
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/csp-custom-ai-mmap-interface-2026-06-16.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Autonomous drive — multi-track / multi-car generality LIVE-VERIFIED (EPIC #154 Part G, 2026-06-27)

**Question (operator):** does the autonomous self-test setup actually work on a *different track
and different cars*, or is it "overly orchestrated theater"? Prior L2 verification was **Magione +
Porsche 911 GT3 R only**.

**Answer: it generalizes — not theater.** Verified live on the rig (`AG_PC`), no human at the wheel,
on two new combos plus a third drive:

| Combo | Track | Car | Result |
|---|---|---|---|
| 1 | **Imola** | **ks_audi_r8_lms** | carcsw **full lap** (5200 m, 0 recoveries, `drove=true`); trainer registered the lap (HUD `Best/Last/Record 9:13.874`, tyre widget `Laps: 2`); 1173+ `coaching.snapshot`; HUD screenshot inspected — coaching `CURRENT 49 KMH` == carcsw telemetry |
| 2 | **Mugello** | **ks_corvette_c7r** | carcsw 2.5 km @ ~65 km/h; 703 `coaching.snapshot` + 357 `tire_temps`; `coaching.snapshot.current_speed_kmh=64.81` == carcsw telemetry; HUD screenshot inspected |

`load_ai_line` parses imola/mugello/monza/spa/ks_laguna_seca `fast_lane.ai` cleanly — the racing-line
loader is track-agnostic. `lap_driver` (conservative pure-pursuit, ~50–65 km/h cap) drove all combos
with the default tune. The trainer reads `ac.getCar(0)` and coaches whatever drives car 0.

## New findings (folded into PR #325 / #324)

1. **`surfaces.ini` permission is NOT required to hijack car 0.** The carcsw hijack landed on Imola
   and Mugello with **only the global `extension/config/new_behaviour.ini [CUSTOM_AI] ENABLED=1`** —
   **no** per-track `[_EXTRA_PERMISSIONS] ALLOW_CUSTOM_AI_MANIPULATION=1` edit. The Magione
   `surfaces.ini` edit recorded in [[csp-custom-ai-mmap-interface-2026-06-16]] was for a *different*
   experiment (extended-physics / AI-line manipulation); it is **not** on the player-car hijack path.
   Correction to the documented recipe.
2. **Early-LIVE hijack race.** CSP only creates the `Car0` read section once its Custom-AI subsystem
   is watching. Creating `CarControls0` too soon after `AC_STATUS`→LIVE silently no-ops (live: hijack
   FAILED at `gfx=13`; SUCCEEDED at `gfx=26907` once settled). Mitigation: settle after LIVE, retry
   the hijack, relaunch on failure.
3. **Sim-death false-green.** When `acs.exe` crashes mid-drive the Car0 mmap freezes and
   `read_car_data()` returns the last frame forever — a parked car read as "still driving" (observed:
   Mugello AC crash at drive-t≈125 s, scratch loop spun on stale `dist=2487m`). Mitigation: detect
   Car0 `packet_id` stagnation and stop. (AC mid-session crashes remain a flaky rig reality.)

## Composition gap closed

`self_test.py` (#236) asserts the WS producer contract but **never drives** — the only
motion-requiring check (`--wait-lap`) was wired to nothing that produces motion. New
`tools/ac_harness/auto_drive.py` (PR #325, closes #324) composes **launch → wait LIVE+settle →
carcsw hijack (retry/relaunch) → autonomous `lap_driver` drive (background thread) → tap sidecar WS
+ assert → teardown**, parametrized by car/track/preset. Pure injectable orchestration → 11 off-sim
tests; rig wiring `pragma: no cover`.

Reusable rig recipe: tokenless loopback sidecar (`python -m tools.ai_sidecar --host 127.0.0.1
--port 8765`); per-combo `.cmpreset` is just JSON with `CarId`/`TrackId` (template from
`autodrive_magione.cmpreset`); CM-URL launch survives the elevated-shell split (#233).

## Flat-out (`--driver ggv`) — full GT3 send, live-verified

Operator pushback: the first composed run used the cruise `LapDriver` (1st gear, 49 km/h) — "not
racing." Fixes, in order:
1. **`--driver racing`** (default) → `RacingDriver` on the AI line's embedded speed profile: shifts
   1→3, ~130 km/h on Spa, full reference coaching (`T3 ON PACE`, `TARGET ENTRY 253 KMH`). But the
   stock AI lines are moderate-speed (Imola maxes 93 km/h), so it's not flat-out.
2. **`--driver ggv`** → flat-out: a generic-GT3 friction-circle min-time profile
   (`ggv_speed_profile_from_model`) driven verbatim by `RacingDriver.from_ggv_profile`.
   **Live-verified Spa + BMW Z4 GT3: top gear 6, max 211 km/h, all gears 1→6**, with reference
   coaching at speed (`T2 · TARGET ENTRY 241 KMH · CURRENT 182 · braking point 25 m`). HUD
   screenshot inspected: 6th gear / 182 km/h on Kemmel.

**Critical GGV correction (#259 red-team, re-confirmed live this session):** the generic GGV's
**`k_aero_lat` MUST be 0**. A first-pass `k_aero_lat=0.00007` made the profile carry too much corner
speed and the GT3 **spun out** (live: hit 5th/165 km/h then spun to neutral). The live-fitted plant
(`mu_lat_g=1.5, k_aero_lat=0, brake=0.955+0.0214·v_ms, ellipse_n=1.55`) — the Stanley+GGV config
that ran clean 95.3s at Magione — holds the line. Steering stays Stanley + `ax_feedforward=False`
(the verified-stable config); the faster curvature-ff/ax-ff pace (83.5s) needs runtime `ff_c1/c2`
calibration from a human CSV + per-track `ff_sign` — separate scope. At flat-out on Spa the
geometric controller still loses a few corners and recovers (honest: not yet the clean 83s line).

`max_gear_used` was added to `DriveStats`/report so a crawl-in-1st run now visibly FAILs the racing
intent. The verified GGV plant is encoded in `auto_drive.generic_gt3_ggv()`.

## Remaining (Part-G optional formal gate)
Determinism-lock preset + CSP precondition assert, and the false-green-rate <5% KPI shadow report.
The sim-death guard here is a concrete anti-false-green step toward that KPI. Deliver if the formal
KPI is wanted; else descope per the #154 Closure Criterion.
