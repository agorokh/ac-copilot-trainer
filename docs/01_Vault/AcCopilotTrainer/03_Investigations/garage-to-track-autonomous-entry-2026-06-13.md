---
type: investigation
status: active
created: 2026-06-13
updated: 2026-06-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/154
relates_to:
  - AcCopilotTrainer/03_Investigations/_index.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/03_Investigations/csp-web-socket-api.md
---

# Investigation: getting car 0 from the pre-drive garage menu onto the track, driving, with no human / no OS input injection (EPIC #154)

## The question splits into two independent problems
OS input injection into CSP's menu fails (raw input + no background focus). But the
problem is really two:

1. **Session entry** (garage/pit menu -> car spawned on track). This is a *launch*
   concern, NOT a Custom-AI / in-sim concern. No CSP Lua API and no Custom-AI field
   leaves the pre-drive menu — they all assume an active session with car 0 already spawned.
2. **Driving** the car once on track. Solved by Custom AI mmap OR a `cphys` car-physics
   script OR a New Mode controls override.

## Findings (grounded)
- **Trainer is a CSP Lua *App*** (`manifest.ini`: `[CORE] BACKGROUND=LUA`, app windows,
  `Draw3D`). App context does NOT load `ac_physics_unrestricted`, `ac_physics_ai`,
  `ac_car_control_physics`, or `ac.endSession` — those are gated to `newmodes`/`cphys`/
  track-script contexts. **So `ws_bridge.lua` actionHandlers CANNOT pilot the car or
  start a session: wrong script context.** (verified against acc-lua-sdk `ac_new_modes.lua`
  `__allow 'newmodes'`, `ac_car_control_physics.lua` `__allow 'carc'`, `ac_physics_unrestricted.lua`).
- **Custom AI** (cup.acstuff.club/docs/csp/other-things/custom-ai): `cai_car_controls`
  (333 Hz write) drives any controllable car incl. car 0; `cai_sim_control` =
  {pause, restart_session, disable_collisions, extra_sleep_ms}; car-level
  `teleport_to` (1=pits, 2=custom). **Assumes session already running + car spawned.**
  `restart_session` restarts an *already-started* session; nothing leaves the menu.
  Enable: `new_behaviour.ini [CUSTOM_AI] ENABLED=1` + track `surfaces.ini
  [_EXTRA_PERMISSIONS] ALLOW_CUSTOM_AI_MANIPULATION=1`.
- **`race.ini` direct launch** (`Documents\Assetto Corsa\cfg\race.ini` + `acs.exe`, the
  path Content Manager drives): writes the full session config and **spawns car 0 already
  on the grid/track in a drivable state, bypassing the CSP garage menu entirely.** This is
  the real answer to problem #1. Content Manager can launch a saved preset from CLI.
- **`ac.overrideCarState` is render-thread only** — not a driver (prior verdict, holds).
- **ViGEm/virtual-gamepad** is open-loop, drifts (butterfly effect) — last resort.
- **`physics.setControlsInput`/teleport/`extraSleep`** exist in the `physics` namespace but
  require the *track* to opt in via `surfaces.ini [_SCRIPTING_PHYSICS] ALLOW_*` + extended
  physics, and a `newmodes`/`cphys`/track-script context — not the App.

## Recommendation
**Two-stage, no human, no OS input:**
1. Launch into the session with `race.ini`/Content Manager CLI (car 0 spawns on track) — solves garage->track.
2. Drive car 0 with the **Custom AI mmap** external app (sidecar writes `cai_car_controls` at 333 Hz; `cai_sim_control` for teleport/restart/slow). Matches EPIC #154 decision node.

The trainer's WS action registry stays the *control plane* (start/stop/scenario selection,
oracle taps) — the sidecar owns the mmap driver. Do not try to drive from the App's Lua.

## Empirical addendum (in-game on AG_PC, 2026-06-14)

Tested live, refining the source-based claim above: switching `[SESSION_0]` to Hotlap
(`TYPE=3 SPAWN_SET=HOTLAP`) + relaunching `acs.exe` DID spawn car 0 on track (RT-DIAG `sp`
advancing 0.357→0.369, vs the pit's constant `sp=0.9773`) — confirming the spawn lever for
problem #1. **But it did NOT skip the pre-drive "Drive / Setup / Exit" session screen** — AC
still showed it, `sim.isInMainMenu` stayed true, so `wsBridge.tick` never ran and the v1
handshake never completed (a `harness_client` tap saw zero `coaching.snapshot`). So
`race.ini` + `acs.exe` alone does NOT auto-enter *driving* on this CSP/CM setup; it only
fixes the spawn location. Entering driving needs ONE of: (a) the in-game **Drive** click —
but OS input injection into AC's menu is **confirmed dead** (raw input + no background-process
focus; SetForegroundWindow / AppActivate / mouse_event all rejected); (b) Content Manager's
**"start session immediately"** Drive toggle (CM Settings → Drive), a one-time human setting,
after which CM launches click-free straight into driving. **Net: the single minimal human
action that unlocks full in-sim autonomy is enabling CM "start session immediately" once.**
After that one toggle, the two-stage pipeline (race.ini/CM launch → Custom AI mmap driver)
is human-free. (Unverified-on-rig next: whether the CM toggle truly yields click-free entry,
and whether Custom AI drives the *player* car 0 — both need that one attended pass.)

## Sources
acc-lua-sdk `common/ac_new_modes.lua`, `common/ac_car_control_physics.lua`,
`common/ac_physics_unrestricted.lua`, `common/ac_game.lua` (ac.CarControlsInput);
cup.acstuff.club/docs/csp/other-things/custom-ai; AC `race.ini` launch (Steam/OverTake
threads). Local trainer: `src/ac_copilot_trainer/manifest.ini`,
`src/ac_copilot_trainer/modules/ws_bridge.lua`.
