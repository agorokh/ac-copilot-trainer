---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-16
updated: 2026-06-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/154
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/01_Decisions/csp-custom-ai-mmap-interface.md
---

# Autonomous in-sim drive — LIVE-VERIFIED end-to-end (EPIC #154, 2026-06-16)

**Outcome (operator-grade, observed on screen):** the agent drove the player car around
Magione **with no human at the wheel** via the CSP Custom-AI mmap (`carcsw`) + a pure-pursuit
controller on Kunos's `fast_lane.ai`, and **the AC Copilot Trainer captured a reference lap from
that drive and then coached the car in real time** (HUD: `Best/Last/Record = 6:27.316`; coaching
widget: `T1 — ON PACE — NEXT T1`, `APPROACHING T1 · TARGET ENTRY 41 KMH · CURRENT 43 KMH ·
DISTANCE TO BRAKING POINT 392 M`). This is the L2/L3 goal of #154: an autonomous self-test of the
trainer with no operator input.

## Proven chain
1. **Launch** (the "engine revs but car won't move" bug): AC physics `gear` encoding is
   **0=Reverse, 1=NEUTRAL, 2=1st**. Engine free-revs unless gear≥2 **and**
   `autoclutch_on_start=True` + `autoclutch_on_change=True`. With those + throttle: 0→74 km/h,
   monotonic. **Never write the clutch field** (offset 8) — a manual clutch value fights the
   autoclutch and kills drive.
2. **Steering**: PurePursuit on `fast_lane.ai`, sign **verified live** — `steer=+0.6 → heading
   −22.7°`, `steer=−0.6 → +31.6°` (heading = `atan2(look_x, look_z)`). PurePursuit's convention
   (`steer>0` = turn right) already matches; **no sign flip needed**.
3. **Full clean lap**: 2,525 m, returned to within ~3 m of the start point, zero crashes, at a
   conservative ~42–44 km/h cap (`.scratch/auto_lap4.py`).
4. **Lap registration**: AC counted the car's S/F crossing (`completedLaps` 0→1).
5. **Trainer reference + live coaching**: observed on screen (above).

## Verified mmap offsets (carcsw → productionize into #190)
- **Controls (`cai_car_controls`)**: gas@0, brake@4, clutch@8, steer@12 (f32 −1..1),
  gear_up@20, gear_dn@21 (bool), **autoclutch_on_start@41, autoclutch_on_change@42** (bool),
  **teleport_to@40** (byte; `1`=pits — verified: full car reset, fuel→30 L, drivable).
- **Car0 reads (`cai_car_data`)** — cross-checked equal to `acpmf_physics`: gear@28, rpm@32,
  speed_kmh@36, **position@88** (float3), **look@64** (float3 unit forward), |look|≈1.0.
  **`spline_position@448` reads GARBAGE** (−5…+10, not 0..1) — do NOT use; fix or drop the offset.

## Reset / recovery
- **`teleport_to_pits()` is the only safe reset** — keeps the sim live, revives a crashed/jammed
  car (throttle-dead → responsive). See [[custom-ai-reset-teleport-not-restart]].
- **`SimState.restart_session()` is POISON**: it opens AC's modal session menu, and **OS input
  injection into AC's menu is dead** (clicks/keys ignored; `SimState.pause`/teleport do not
  dismiss it). Recovery then requires a Content-Manager relaunch. Never call it in this setup.

## Menu-skip race (operating the rig headless)
- CM's **"Start race immediately"** (Settings → Drive) is **ON**, but skipping AC's pre-drive
  menu is a genuine timing race — it lost 2 of 3 cold launches. At the pre-drive menu the
  **hijack is absent and the sim is frozen** (rpm pinned), so the car can't be driven from there.
- Workaround: **retry the launch** (kill `acs` → close CM "Cancelled" dialogs via Win32
  `WM_CLOSE` → focus CM → click Go!) until the race wins.
- **The Claude desktop window steals foreground** and broke CM clicks; **minimize it**
  (`ShowWindow(hwnd, 6)`) so CM is reliably interactable. AC's menu is fullscreen and covers CM —
  kill `acs` before driving CM.

## Lap-detection note (harness)
- In **hotlap mode AC only counts VALID laps** in `completedLaps@132`; a pure-pursuit line can
  clip a curb and invalidate the lap, so `completedLaps` is an unreliable lap detector here.
  Use **position-return** (car back within ~10 m of the lap start after ≥~2 km) or
  `acpmf_graphics.normalizedCarPosition` instead.

## Artifacts (gitignored `.scratch/`, promote logic to the PR)
`custom_ai.py` (+autoclutch fields), `ai_line.py` (PurePursuit, steer sign confirmed),
`auto_lap4.py` (clean full lap), `auto_lap5/6.py` (multi-lap), `VERIFIED_FINDINGS.md`.

## Remaining (next session)
- Productionize `carcsw` into PR for #190: mark the verified offsets CONFIRMED, drop/fix
  `spline_position@448`, add the gear-encoding + autoclutch launch recipe + steer-sign facts,
  add position-return lap detection.
- Optional: capture a clean *fast* flying-lap time (continuous out-lap + flying lap, valid) for a
  better trainer reference than the 6:27 standing-start artifact.
- Restore `magione/data/surfaces.ini` (extended-physics + `[_EXTRA_PERMISSIONS]` edit) when done.
