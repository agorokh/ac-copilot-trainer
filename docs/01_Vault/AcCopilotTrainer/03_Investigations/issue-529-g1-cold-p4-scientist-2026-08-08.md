---
type: investigation
status: active
memory_tier: canonical
created: 2026-08-08
updated: 2026-08-08
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-pace-ladder-115-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-582-l3-corner-refinement-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-572-alien-pipeline-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #529 — G1 cold-start (5th unseen combo), FIRST real P4 scientist batch, G1b (2026-08-08)

Autonomous rig session on **AG_PC console session 1** (on-rig, no SSH hop), merged `main` @ `a5eb54b`,
junction `provenance: match` every stage. Week-rested boot (AC idle since 2026-08-01) → deep #627 launch
accumulator; ~35 launches landed across the night, every one on probe 1/3.

## TT reference is a SOLVED data dependency (not a blocker)
Public leaderboard `https://app.tracktitan.io/leaderboards/assettoCorsa/<track>/<car_id>` needs no login.
Reads 2026-08-08 (carry the date — the June "82.7 s = Magione top-10" line is stale; 82.7 s ≈ P22 today):
huracan@spa **P10 = 2:17.691** (band ≤2:24.576); 911@magione P1 1:11.035, P10 1:16.787.

## G1 cold-start on an UNSEEN combo — ks_lamborghini_huracan_gt3 @ spa
One unmodified `auto_alien … --laps 3 --iterations 3 --max-scale 1.2 --identify-seconds 900`.
Cold (`identification REQUIRED`) → schema-v3 plant, uncertainty fit promoted → line QSS 177.24 s → ladder,
**~18 laps (≤20)**, strictly monotone: base 185.526 → it1(plant) 185.514 → it2(env 1.15) 166.510 →
**it3(plant 1.15) 161.595 s**. it3 **adopted 11 lateral bins** (was 1) and **L3 fired: 5 corners, +812 ms**
— the same 11-bin+L3 breakthrough the 911 showed, now on a brand-new combo/track.
- **Verified 3 ways:** lap archive `lap.is_valid:true` / `161595` ms / spa 6946 m; iter03 `recoveries=0`,
  `sim_dead=false`, 257 km/h; **iter03 hud.png dash reads 2:41.595** (instrument harness doesn't write).
- **Mechanics: PASS (5th unseen combo).** **Pace: NOT met** — 161.595 s vs P10 137.691 s = **17.4 % off**
  (was 34.7 % cold). Evidence `.scratch/harness-evidence/alien-529-g1-huracan-spa-20260808-r3/`.

**G1-as-written verdict:** the pace half is architecturally out of reach in ONE cold ≤20-lap run with the
current conservative uncertainty gating (the 911 needed 3 retained-plant ladders ≫20 laps 96→80.7 s; its
first cold session hit ~88 s / 15 % off). The lever is **retained-plant compounding across sessions**. The
huracan@spa plant is now retained (11 bins + L3) → a next ladder starts near 161 s, not 185 s.

## P4 — FIRST real rig scientist batch (ledger previously empty)
`auto_alien … --setup Copilot_Balanced_Fast --laps 2 --iterations 1 --scientist --scientist-batch-size 1`.
End-to-end: setup-scoped plant → self-play baseline → hypothesis → candidate written+identified+driven →
Welch compare → **verdict persisted to `journal/alien_scientist/experiments.jsonl` (first entry)**.
- Hypothesis `plateau_rear_wing` WING_2 16→15. Baseline n=2 mean **108.34 s** vs candidate **113.97 s** =
  **−5.2 %** (nominally slower), z=−0.62, p=0.73 → **verdict `falsified`**, constraint `802860d5…`
  durably suppressed for META scope `639fa350…`. Both candidate laps `is_valid:true`. Magione cockpit
  confirmed in hud.png. Run record `runs/20260809T060046Z_9eae67de52cc41cd.json`.
- Fail-closed worked: it refused to promote a change that wasn't actually faster. "Falsified" is the
  correct FIRST outcome, not a null — the machinery + statistics + durable suppression all ran on real data.

## G1b — novel-archetype cold start (bmw_m3_e30 @ magione): honesty PASS
`auto_alien --car bmw_m3_e30 --track magione --laps 2 --identify-seconds 600`. Off-prior archetype (1980s,
low-DF, semi-slick) handed the GT3 generic prior for unmeasured bins. Cold identify PASS (own plant:
ff_c1=5.03, r_eff=0.307, rpm_up=7042). Base alien drive **2 laps `is_valid:true`, 155.6 km/h, recoveries=0**,
**all 7 corners reverted to safe-QSS**; ~4 laps total (≪50). Honest laps 123.6 / 111.1 s — appropriately
slower than the 911's ~91–107 s: the pipeline adapted to the real low-grip car and stayed in a drivable
envelope instead of forcing GT3 pace and spinning. Real E30 cockpit confirmed in hud.png (analog gauges, M3
badge). Evidence `.scratch/harness-evidence/alien-529-g1b-e30-magione-20260808/`.

## Two real defects owned → FILED
1. **Scientist candidate `stage=setup` re-bake race** → [#737](https://github.com/agorokh/ac-copilot-trainer/issues/737).
   First P4 attempt failed `fuel 30.0L != 40.0L` on the candidate identify though the file was correct
   (`[FUEL]=40`). CM regenerates race.ini at launch; the 0.05 s re-bake loop **lost the race once**, and the
   `stage=setup` path has **no relaunch budget** (unlike sim-death) so it aborted the whole batch. Intermittent
   — the identical retry won (`setup_applied:true`). #466 characterized the CSP/CM race as fundamental; the
   narrower fix is a relaunch-on-setup-verify-failure so one transient miss doesn't kill a multi-candidate batch.
2. **CM "Custom Shaders Patch data" pre-drive dialog** relaunch-loop → [#738](https://github.com/agorokh/ac-copilot-trainer/issues/738).
   Hangs on a failing online fetch this boot; the harness kills CM every ~75 s instead of skipping it → ~2×
   launches/drive (15 launches / ~5 drives). Mitigated live with a UIA Skip-clicker (`.scratch/skip_watcher.ps1`).
   NOT the #627 render wedge (there acs never spawns; CM is blocked). First FAIL of the night.

## Gate status after tonight
G0 PASS; **G1 mechanics 5× unseen combos** (huracan@spa added, first 11-bin+L3 compounding on a fresh combo);
**G1 pace unclaimed** (17.4 % off, architecturally out of reach in one cold ≤20-lap run — lever is
cross-session plant compounding); **G1b honesty PASS**; **G2 MET** (80.791 s, 2026-07-26); **G3 operator-gated**
(needs a human across sessions — cannot be produced autonomously); **P4 first real batch DONE** (falsified
verdict, ledger). Comment: #529#issuecomment-5230120646. Keep #529 OPEN.

## Rig state left behind
On-rig AG_PC console session 1; main @ a5eb54b; junction `provenance: match`. No acs.exe, no CM, rig lock
cleared, Skip-watcher stopped. New retained plants: `bmw_m3_e30__magione`, `ks_lamborghini_huracan_gt3__spa`
(11 bins+L3), `ks_porsche_911_gt3_r_2016__magione__setup-Copilot_Balanced_Fast-4eaef714`. Scientist ledger
`journal/alien_scientist/experiments.jsonl` now has 1 entry (falsified WING_2). ~35 launches landed clean;
#627 accumulator deep on this week-rested boot. **TT public leaderboards are the reference source** (no login):
`app.tracktitan.io/leaderboards/assettoCorsa/<track>/<car_id>`.
