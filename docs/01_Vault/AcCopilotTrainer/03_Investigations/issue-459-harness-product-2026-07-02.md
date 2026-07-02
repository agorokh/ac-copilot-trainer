---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-02
updated: 2026-07-02
issue: https://github.com/agorokh/ac-copilot-trainer/issues/459
relates_to:
  - AcCopilotTrainer/03_Investigations/autonomous-drive-multitrack-generality-2026-06-27.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #459 — Autonomous harness as a product (setup verify, zero-lore launch, evidence, stall fix)

Operator reframing of EPIC #154 (2026-07-02): launching the harness is still a struggle for
agents, runs are half-done because **no car setup is ever selected or verified**, and the proof
looks overfit — the control question "same car (911 GT3 R) at **Spa**" was never run. Goal: a
resilient habit — one command, any downstream task, no reinvented `.scratch` drivers.

## What shipped (branch `feat/issue-459-harness-product`)

- **Setup as a first-class parameter** — `auto_drive --setup <name>` resolves under
  `<AC user data>/setups/<car>/<track|generic>/`, applies via the sidecar `setup.load` relay
  (Lua `ac.loadSetup`, pits gate), and the run FAILS at `stage="setup"` unless the in-sim ack
  names the requested setup (`verify_setup_ack`). Setup runs generate `StartType=PIT` presets.
- **Zero-lore launch** — `--car` generates the deterministic practice `.cmpreset`
  (#154 Part-G determinism lock); `preflight()` asserts content, CSP `[CUSTOM_AI] ENABLED=1`
  (user `cfg/extension` overrides AC-root `extension/config`), CM presence, preset↔CLI combo
  consistency, setup resolvability. Sidecar reused (Game Point child on :8765) or auto-started.
- **Stall recovery (the ~500 m flake)** — drivers' stuck detectors are gas-gated
  (`gas > stuck_throttle`), so low-throttle stalls never recovered. New driver-agnostic
  `ProgressWatchdog` (no forward progress ⇒ recover, any throttle), recovery **cap** with an
  honest FAIL naming the stall distance, and spawn-to-line custom teleport
  (`CarControls.teleport_dir` now packed; position read-back verified, pit fallback).
- **Evidence bundle** — `report.json` (combo, setup ack, drive stats incl. recoveries, WS frame
  counts) + generated preset + `hud.png` liveness + lap-archive paths, default under
  `.scratch/harness-evidence/`.
- **Habit surface** — runbook `docs/10_Development/18_Autonomous_Harness.md` (the single
  documented path + rig-lore troubleshooting table) and pointer skill
  `.claude/skills/ac-harness/SKILL.md` (no re-inlined procedure).

## Empirical facts recorded

- `race.ini [CAR_0]` carries `_EXT_SETUP_FILENAME=<abs setup ini>` when CM launches with a
  selected setup (observed on the rig for `Copilot_Balanced_Fast.ini`) — a fallback application
  path if the WS route ever regresses.
- Trainer journal on disk:
  `<user>/cfg/extension/state/lua/app/AC_Copilot_Trainer/ac_copilot_trainer/journal/laps`.
- Rig has 911 GT3 R Spa setups: `Realistic_BB_v1/2/3.ini`; Spa `ai/fast_lane.ai` present.

## Live findings (Spa, 2026-07-02 — PR #460)

- **The pits gate closes under the carcsw hijack.** First live run failed `stage=setup` with
  "must be in pits" even though the car was in the pit box — CSP holds `ac.isCarResetAllowed()`
  false while a Custom-AI controller owns car 0. **Fix:** apply + verify the setup *before* the
  hijack, inside the launch loop (a relaunch is a fresh session, so re-apply each attempt).
- **Menu-skip race is invisible to the LIVE gate.** After a cold relaunch AC can sit at the
  pre-drive "Drive/Setup/Exit" screen with `status=LIVE` and physics **advancing** — the launch
  gate cannot tell it from a real session, but the trainer Lua app never ticks, so the sidecar
  answers "no loopback Lua peer connected" forever. `rig_apply_setup` now flags
  `retryable_launch=True` when the Lua peer never answers, and the orchestrator **relaunches**
  (like a failed hijack) rather than hard-failing. Confirmed live: pkt advancing, `in_pit=True`,
  Lua peer never connected across a 150 s window; also observed the agent's own foreground window
  losing the menu-skip race → added a best-effort foreground-minimize before each CM launch.
- **Setup timeout raised 60→150 s**: the Lua peer reconnect after a cold relaunch measured
  well over a minute.

## Review hardening (PR #460, 15-agent adversarial workflow → 12 confirmed, all fixed)

- Setup leg moved before the hijack (the HIGH above); `<car>/generic/` now enumerated by
  `setup_library.lua M.list()` (it resolved off-sim but `loadByName` reported "not found");
  `loadByName` path match normalized (separator + case) so path-first disambiguation works;
  `custom_ai_enabled` reads `utf-8-sig` and catches `UnicodeDecodeError` (BOM'd CSP inis);
  car/track/layout ids validated before they become path segments (evidence dir / setups join);
  `ensure_sidecar` timeout path kills its half-started child (no orphan on :8765); recovery-cap
  veto is now a structured `DriveStats.recovery_capped` flag, not a magic substring; dual
  tap+drive failure keeps the pipeline stage and records the drive crash in `notes`.

## Remaining (this issue)

Part F live proof: Spa + `ks_porsche_911_gt3_r_2016` + `Realistic_BB_v3` via the one command,
evidence bundle on #154/#459; TT Spa reference ingest + session-review comparison. Live checks
still open: confirm `ac.loadSetup` succeeds pre-hijack in the pit box; do the custom-teleport
offsets land (else pit-exit fallback); root-cause the 450–580 m stall with the watchdog telemetry.
