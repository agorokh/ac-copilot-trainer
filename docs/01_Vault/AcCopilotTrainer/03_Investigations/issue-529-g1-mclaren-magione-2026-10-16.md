---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-529-g1-cold-p4-scientist-2026-08-08.md
  - AcCopilotTrainer/03_Investigations/issue-746-749-repeatability-and-thermal-gate-2026-08-10.md
workspace: "ac_copilot"
---

# EPIC #529 — fresh G1 cold-start datapoint: ks_mclaren_650_gt3 @ magione (2026-10-16)

**Operator directive this session:** `not-this-cycle` removed from #529; run a fresh live-rig
G1 cold-start on an **unseen known-archetype** combo and record an honest dated verdict even if
pace-within-5% is not met.

**Outcome (one line):** cold-start **mechanics generalize** to a new mid-engine GT3 (McLaren 650S
GT3), but **G1 pace is NOT met** — best AC-valid lap **97.378 s (1:37.378)** vs TT top-10
**P10 74.784 s / P1 72.035 s**, i.e. **+30.2% off P10** (+35.2% off P1), far outside the 5% gate.
Consistent with the standing finding that cold-start pace lands conservative and G1 pace remains
architecturally blocked.

## Run

- Rig `AG_PC`, merged `main` `70ed2fe`, junction provenance **match** every stage.
- Combo genuinely **unseen**: harness logged `identification REQUIRED — no plant artifact for this
  combo`. Known archetype = **mid-engine GT3** (same mechanical family as the already-seen 488/Huracan).
- One command, off-rig via the console-session transport (#697):
  `remote_launcher start -- -m tools.ac_harness.auto_alien --car ks_mclaren_650_gt3 --track magione
  --laps 3 --ggv-scale 1.0 --scale-step 0.15 --iterations 4 --max-scale 1.2`
- Evidence: `.scratch/harness-evidence/alien-529-mclaren-magione-20261016-000614-34316-4886/`
  (`alien_report.json`, per-stage `report.json`, `hud.png`); lap archives under `journal/laps/lap_20261016-07*`.

## Lap trajectory (every autonomous lap on this cold combo)

| Stage | ggv_scale | lap times (s) | valid | note |
|---|---|---|---|---|
| identify (handshake + ID) | — | 148.838, 135.560 | probes | plant measured from scratch |
| base drive | 1.00 | 111.156 (out), 97.397, **97.378** | ✓ | AC-valid, 0 recoveries |
| iter1 (plant refit) | 1.00 | 112.982 (out), 97.427, 97.459 | ✓ | all AC-valid, 0 recoveries, flying spread 0.03%; adopted 1 lateral bin (monotonic merge, retained) |
| iter2 (envelope) | 1.15 | 113.028 (out) → crash | ✗ | **falsified**: recovery cap (6) exceeded at 2906 m; plant refit from iter1 retained |

- **Total autonomous laps: 9** (2 identify + 3 + 3 + 1) — best pace reached in **5 laps**. Well
  within the G1 **≤20-lap** budget.
- **Best AC-valid lap: 97.378 s.** HUD (`drive/hud.png`) corroborates: Racelogic dash reads
  `1:37.378`, McLaren 650S GT3 cockpit at Magione, live coaching overlay firing.
- L3 (#582) **reverted all 7 corners** (prior-dominated bins, `refined=0`): conservative/honest
  on a cold plant with no low-variance lateral evidence yet.

## Gate accounting (vs the #529 2026-10-13 retained gates)

- **G1 pace — NOT met.** 97.378 s is +30.2% / +35.2% off the TT top-10 (P10/P1). The 5% gate is
  unmet by a wide margin. The run's own observer also flagged the stint **nonstationary**
  (`thermal_delta_c=9.92≥8.0; pressure_delta_psi=1.59≥1.5`, `reidentify_recommended`), so the pace
  number is not even at the gate's required stationary environment state.
- **G1 mechanics — demonstrated for a new GT3 car.** Cold plant-ID → min-curvature line + QSS →
  AC-valid autonomous laps, **zero recoveries** at the safe scale, self-play plant refit retained.
- **G4 honesty — intact.** The overspeed rung (1.15) was **falsified** and not promoted; the
  retained plant is the validated iter1 refit; nonstationary env surfaced, not hidden.

## TT reference (public, read 2026-10-16)

`app.tracktitan.io/leaderboards/assettoCorsa/magione/ks_mclaren_650_gt3` (McLaren 650S GT3, All
Time, all conditions): P1 Akshara **1:12.035**, P10 Usera4a3 **1:14.784**. 5%-of-P10 threshold
78.523 s; 5%-of-P1 threshold 75.637 s.

## Disposition

**Keep #529 OPEN.** This is a fresh honest G1 datapoint, not a closure: G1 pace remains unmet
(architecturally blocked — the pace lever is cross-session plant compounding / a less-conservative
measured prior, root-caused Aug 2026) and **G3 stays operator-gated** (needs a human multi-session
result). No source change was warranted; the plant/line artifacts for this combo now persist on the
rig. Whether to restore the `not-this-cycle` label is the operator's call.
