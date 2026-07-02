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

## Live findings (Spa, 2026-07-02 — PR #460) — the setup mechanism, proven

The initial WS `setup.load` approach was **fundamentally wrong** and was replaced after live
investigation:

- **AC applies a car setup only at car spawn, from `race.ini`.** The in-sim WS `setup.load` is
  gated by `ac.isCarResetAllowed()`, which stays **false for a freshly-spawned autonomous car**
  ("must be in pits" even in the pit box, even *before* any carcsw hijack — the hijack was not the
  cause). So no mid-session load works for the harness.
- **Working mechanism (live-verified):** bake `[CAR_0] _EXT_SETUP_FILENAME=<abs path>` (CM's own
  key) + vanilla `SETUP=<name>.ini` into `race.ini`, then **direct-launch acs** (this rig shell is
  non-elevated, so no Steam-integrity mismatch). AC logs `Setup change ... SPRING_RATE_RR ...` at
  spawn and `acpmf_physics.fuel` reads the setup's `FUEL` value **exactly (45.00 L ==
  Realistic_BB_v3 `FUEL=45`)**. Verification is fuel-vs-`[FUEL] VALUE` — universal and cheap.
- **CM regenerates `race.ini`** from its Quick-Drive preset, and that preset has **no setup key**;
  so a setup baked before a CM launch is wiped. The harness primes with CM (correct combo), then
  bakes + direct-relaunches.
- **`gui.ini [GUI] FORCE_START=1` skips AC's pre-drive Drive/Setup/Exit menu** on a direct launch
  (OS input injection to that menu is CSP-blocked; computer-use `request_access` times out here).
  Live-verified: with it, the hijack lands first attempt. **Removed from the shipped code** (PR #460
  review — the harness must not write CSP install-tree config, and a killed harness would leave a
  global CSP setting changed); the menu-skip that would let a setup run also *drive* is deferred to
  #461. The setup **verification** does not need it — fuel reads back at the pre-drive menu too.
- **Shared-memory offsets used:** `acpmf_graphics` status @4 (2=LIVE; 8 is session type, an easy
  mis-read), `acpmf_physics` fuel @12, gear @16, speed @28.

**End-to-end result:** `auto_drive --car ks_porsche_911_gt3_r_2016 --track spa --setup
Realistic_BB_v3 …` runs the whole thing automatically and the report carries
`setup_applied=True, detail="fuel 45.0L matches setup FUEL 45.0L"`. The operator's core ask — pick
a setup and *check* it, at Spa on the 911 — is delivered and proven.

## Sim-death guard bug (fixed) — Car0 packet_id ≠ main physics packet_id

The drive's sim-death guard keyed on the **Car0 (Custom-AI) packet_id**, which live-probing showed
**does not advance frame-to-frame** — it holds constant (`pkt=24`) for a stationary car while the
**main `acpmf_physics` packet_id advances normally** (91235→93570). So the guard **false-declared
"acs.exe died" 4 s into a start-line spawn, before the car could even shift out of neutral**
(gear=1=NEUTRAL). Fixed: sim-death now keys on the main physics packet_id (advances every frame,
freezes only on a real acs crash). After the fix a PIT-spawn drive ran the full recovery cycle and
failed honestly via the recovery cap instead of a false sim-death.

## Genuine residual (tracked follow-up) — setup runs vs. the drive don't compose yet

- **`START` spawn on a direct launch freezes the Car0 mmap** → the hijack never lands.
- **`PIT` spawn** hijacks fine (proven) but the car **can't escape Spa's pit box** — the
  custom-teleport offsets that would jump it to the racing line are doc-extracted / unverified, and
  the OUT-phase can't drive out of the garage. The recovery cap then fires honestly (`drove=False,
  reason="recovery cap (6) exceeded at 0m"`).
- The **drive itself is proven** separately (multi-track: Spa + Z4 flat-out 211 km/h via a CM
  **grid** launch). The tension: the drive needs a CM/grid launch, the setup needs a direct
  relaunch; each blocks the other. Resolution options: CM setup-carry, fix the `START`-spawn
  Custom-AI freeze, or verify the custom-teleport offsets. **File as a #154 follow-up.**

## Review hardening (PR #460, 15-agent adversarial workflow → 12 confirmed, all fixed)

- `<car>/generic/` now enumerated by `setup_library.lua M.list()` (it resolved off-sim but
  `loadByName` reported "not found"); `loadByName` path match normalized (separator + case) so
  path-first disambiguation works; `custom_ai_enabled` reads `utf-8-sig` and catches
  `UnicodeDecodeError` (BOM'd CSP inis); car/track/layout ids validated before they become path
  segments (evidence dir / setups join); `ensure_sidecar` timeout path kills its half-started child
  (no orphan on :8765); recovery-cap veto is a structured `DriveStats.recovery_capped` flag, not a
  magic substring; dual tap+drive failure keeps the pipeline stage and records the drive crash in
  `notes`. (The setup-leg reorder + `retryable_launch` from the first cut were superseded by the
  launch-bake mechanism above — the WS `setup.load` path is gone.)

## Delivered vs. remaining

**Delivered + proven (PR #460):** the setup mechanism (launch-bake `_EXT_SETUP_FILENAME` + fuel
verify) runs automatically in one command and confirmed `setup_applied=True` (fuel 45.0==45.0) for
Spa + 911 GT3 R + Realistic_BB_v3 — evidence bundle in
`.scratch/harness-evidence/spa-911-bbv3-FINAL/`. Sim-death guard fixed (main physics packet_id).
FORCE_START menu-skip proven. 15-agent review hardening (12 findings) all fixed.

**Follow-up ([#461](https://github.com/agorokh/ac-copilot-trainer/issues/461), child of #154):**
compose setup runs with a completed autonomous DRIVE — resolve the `START`-spawn Custom-AI freeze
vs. `PIT`-spawn pit-escape tension (CM setup-carry, or fix the freeze, or verify the custom-teleport
offsets). TT Spa reference ingest + session-review comparison depends on the drive-produced lap
archive that composition would yield, so it rides on #461.
