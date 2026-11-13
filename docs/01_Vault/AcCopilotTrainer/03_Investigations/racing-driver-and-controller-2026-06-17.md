---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-17
updated: 2026-06-17
issue: https://github.com/agorokh/ac-copilot-trainer/issues/244
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/cm-url-deelevated-launch-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/csp-custom-ai-mmap-interface-2026-06-16.md
---

# Racing driver + the steering wall — what the agent can/can't drive (EPIC #154 Part G, #241/#244)

The autonomous self-test needs the agent to drive **racing dynamics** so the trainer's racing
coaching is actually exercised. The old `lap_driver` is a 44 km/h **zero-brake** lane-keeper — a
crawl, not a test. This is the racing-driver effort + the wall it hit.

## What was built (PR #242, branch `feat/issue-241-racing-driver`)

- **`fast_lane.ai` has an embedded speed profile.** Per main point, the AiPointExtra block
  (`speed@0, gas@4, brake@8`, **72-byte stride**, after `16 + count*20 + 4`) holds the speed the game
  AI drives (magione: 0→**223 km/h**, `brake` up to 0.92). The position loader discarded it;
  `racing_driver.load_speed_profile()` reads it.
- **`RacingDriver`** (pure `step()`): a backward pass bakes braking points (brake *before* corners);
  hard braking when over the profile; trail braking (release brake as steer rises); traction-limited
  throttle (lift when cornering). Steering reuses `PurePursuit`.

## Live findings (magione, Porsche 911 GT3 R, `AG_PC`)

- **Gear bug — "stuck in 1st":** 1st gear's rev limiter plateaus at **~7400 rpm**, BELOW the old 7600
  upshift point → the car bounced off the limiter at 80 km/h, never upshifting. Fix: shift point to
  **7000** (below any gear's limiter). Then it shifts **1→4 (33 shifts)**, **146 km/h** (was 52),
  range **12–146**.
- **The wall is STEERING, not the racing logic.** `PurePursuit` cuts apexes / understeers, so corner
  speeds must be throttled down and it still clips curbs → AC marks the lap **INVALID** → `lap`/
  `delta` telemetry + a clean coaching reference never flow. Straights are fine; corners limit pace.
- **Input channel is fully racing-capable** (direct probe): 333 Hz, `brake=1.0`→**1.48 g**, full
  throttle (TC off)→wheelspin, coupled trail-brake accepted. So only the *controller* is missing.

## The path: human-lap telemetry → a real controller

`tools/ac_harness/racing_telemetry.py` records a human-driven session (acpmf_physics inputs +
dynamics + acpmf_graphics lap/position) to CSV. A few real GT3 laps give the line, braking points,
carried corner speeds, and lateral-grip envelope to build a **path-tracking steering controller**
(Stanley/MPC) at the human's pace — and a real coaching reference. See [[cm-url-deelevated-launch-2026-06-16]]
for launch, [[csp-custom-ai-mmap-interface-2026-06-16]] for the actuation, and #244 for the plan.

## Gotchas

- Gear encoding: AC `gear` is 0=R, 1=N, **2=1st** — log `gear-1` for the real gear.
- Menu-skip launch is flaky; the first launch after a `surfaces.ini` edit can load stale → relaunch.
- Custom-AI on magione needs the `surfaces.ini` extended-physics + `[_EXTRA_PERMISSIONS]` edit
  (offline-hash; restore from `surfaces.ini.bak-precustomai`); not needed for human driving.
