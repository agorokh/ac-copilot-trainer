---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-12
updated: 2026-07-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/532
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/frontier-controller-ggv-2026-06-19.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-multitrack-generality-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/issue-459-harness-product-2026-07-02.md
---

# #532 P1 — Auto-handshake plant ID: machine-measure the controller constants

**Epic:** #529 (Alien Lap Platform), phase **P1**, gate **G0**. Child issue #532, draft PR
[#535](https://github.com/agorokh/ac-copilot-trainer/pull/535).

## Goal

Replace the frontier controller's per-combo **hand constants** (`ff_sign` from a human-lap
correlation, `ff_c1/ff_c2` from a lost `.scratch/model_id.py`, shift points as `RacingDriver`
defaults, one hardcoded `generic_gt3_ggv()`) with **in-sim designed probes** that machine-measure
each constant with a quality gate + provenance — zero hand-tuned values on the pipeline.

## What shipped (`tools/ac_harness/plant_id.py`)

`HandshakeController` conforms to the `RacingDriver` `step()`/`on_recovery()` contract, so the
**unchanged** `rig_drive` loop executes it. Probes on straights:

- **steer pulses** (both directions) → `ff_sign`, measured in the SAME (x,z) cross convention as
  `ggv_profile.signed_curvature_profile` (so the pulse and the controller share one convention).
- **corner mining** → `ff_c1`/`ff_c2` via the existing `ggv_profile.fit_steer_feedforward` (no
  duplicated fit; sign cross-checked vs the pulse `ff_sign`).
- **WOT sweep** (pull from the current gear through natural upshifts) → per-gear ratios +
  `rpm_up`/`rpm_dn` (accel-crossover, honest limiter-margin fallback).
- **coast** → `r_eff` from `wheelAngularSpeed[4]@104` (added to `racing_telemetry.parse_physics`).

Each constant carries a quality metric; a missed gate FAILs at `stage="handshake"` naming the
probe. Artifacts persist at `<AC user dir>/plant_id/<car>__<track>.json` (durable, never `.scratch`).
`auto_drive --driver handshake` measures; `--use-plant off|auto|full` consumes on the ggv path.

## Live verification (rig, AG_PC, 2026-07-12)

Three rig runs drove the fixes now in PR #535:

1. **Magione requested → CM served Spa** (cached-session launch). The harness drove Magione's line
   on Spa → recovery cap. **Fix: track-match guard** (`auto_drive.rig_verify_track` reads
   `acpmf_static.track`; FAILs at `stage="launch"` on mismatch). Separable CM root cause filed as
   **#537**.
2. **Clean Spa drive but car stuck in 2nd, "no result".** The WOT sweep forced a downshift to 2nd
   and re-queued forever; the drive ended before self-completion. **Fixes:** bounded per-probe
   FAILURE cap (drop a probe a track can't satisfy so the schedule completes), `finalize()` at
   drive-end (always produce a result + diagnostics), and a WOT sweep from the CURRENT gear.
3. **First G0 attempt (`handshake-spa-911-2`):** 4/5 measured; `steer_ff` FAILed honestly (4 corner
   rows) because **acs.exe crashed at 3068 m** (`sim_dead`). Tuned handshake pace 0.65 → 0.8 for
   corner-row yield.
4. **G0 PASS (`handshake-spa-911-3`, `stage=done`):** clean drive (10919 m ≈ 1.5 Spa laps, 0
   recoveries, no crash), **all 5 constants machine-measured**, plant artifact persisted to
   `<AC user dir>/plant_id/ks_porsche_911_gt3_r_2016__spa.json`:
   - `ff_sign=+1` (4 pulses agree)
   - `steer_ff`: `ff_c1=5.254`, `ff_c2=0.00110`, **rms_frac=0.065** over **81 corner rows**
   - `gear_ratios`: 4 gears (g1..g4, monotonic)
   - `shift_points`: `rpm_up=8300`, `rpm_dn=6023` (accel-crossover method)
   - `r_eff=0.349 m` (per-wheel 0.341/0.341/0.357/0.357 — real 911 GT3 R tyre)

   HUD screenshot inspected (real Spa cockpit, trainer live). The artifact **round-trips through the
   real consumption path**: `load_plant_artifact` → `plant_driver_kwargs` feeds the ggv driver
   measured shift points (`--use-plant auto`) and measured curvature-FF steering (`full`).

## Key empirical facts

- `acpmf_static.track` at byte **134** (UTF-16LE, 33-char), `carModel@68` — live-verified.
- `wheelAngularSpeed[4]` at **@104** in `acpmf_physics` (r_eff channel).
- CM launches its cached last session, ignoring the `presetFile` URL, when a session is already
  configured (#537) — the guard makes this fail honestly.
- AC mid-session crash (`sim_dead`) remains an intermittent rig reality that can cut a probe drive
  short; `finalize()` makes the partial result diagnosable.

## Remaining

- Part B (same #532): progressive-envelope friction ID → per-combo uncertainty-carrying `GGVModel`
  replacing `generic_gt3_ggv()`.
- Optional live proof of a `--use-plant full` ggv drive consuming the Spa artifact end-to-end
  (consumption is unit-tested + the off-rig build path is verified; a full flat-out drive is P2/P3
  territory).
- `#537` (CM cached-session launch) still open — the guard makes it fail honestly.
