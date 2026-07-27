---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-26
updated: 2026-07-27
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-695-qss-apex-envelope-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-693-off-rig-session0-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-577-alien-selfplay-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-582-l3-corner-refinement-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #529 — **G2 met**: 81.505 s at Magione, under the 82.7 s floor (2026-07-26)

Live rig session driven **off-rig** from the laptop through the `m4max-studio` → `pc` SSH hop and a
console-session scheduled task. Merged `main` @ `670b529`, which is the first rig run to carry the
#696 QSS-apex fix.

**Headline: two ladders, 88.425 s → 85.072 s → 84.587 s → 81.505 s.** The second ladder beat the
82.7 s Track-Titan floor on two consecutive flying laps (81.505 s and 81.519 s), zero recoveries,
all archives `is_valid: true`. See § *G2* below — the gain came from **retaining** the plant refit,
which is the whole of [#703](https://github.com/agorokh/ac-copilot-trainer/issues/703).

## Ladder 1 (hand-run recipe): best 85.072 s

One unmodified command,
`auto_alien --car ks_porsche_911_gt3_r_2016 --track magione --laps 3 --ggv-scale 1.0
--scale-step 0.15 --iterations 2 --max-scale 1.2`:

| ggv_scale | best flying lap | verdict |
|---|---|---|
| 1.00 (base) | 96.285 s | PASS — 0 recoveries |
| **1.15** | **85.072 s** | **VALID** — 0 recoveries, 222.1 km/h, every lap `is_valid=True` |
| 1.20 | — | **FALSIFIED** — `recovery cap (6) exceeded at 3335m`, 7 recoveries → plant reverted |

`auto-alien: OK`, wrapper `exit=0`. The 1.20 falsification is **physics** (the car could not hold
1.44× lateral g), unlike the previous session's 1.15 "falsification", which was the #695 solver bug.

Gap to the 82.7 s Track-Titan floor: **6.9 % → 2.87 %**. Evidence bundle:
`.scratch/harness-evidence/alien-529-g2-911-magione-20260726-195901-17748-7359/`.

**Verified, not inferred.** The three iteration-1 lap archives all carry `is_valid=True`
(`lap_20260727-031108_1d26a810_2_85072_…json`), the stage report shows `recoveries=0`,
`sim_dead=false`, and the captured cockpit frame shows the car's **own Porsche dash reading
`Last Lap 1:25:13`** — the 85.132 s lap confirmed on an instrument the harness does not write.

## #696 is proven on the rig — the 1.15 rung had never been driven

The previous session's ladder never got a physics verdict for 1.15: the run died in
`alien line build failed — QSS profile exceeds the plant lateral envelope`, the #695 solver bug
(a bare fixed point on the step-function `ay_max`). That was recorded as "FALSIFIED" but was a
solver defect, not a spin. This session the same rung built its line and drove it clean, and
iteration 2 rebuilt the line again at 1.20 (`QSS 87.0 s, plant fit 33bbf3293f94`). The fix holds
against the case that motivated it.

## G2 — ladder 2 broke the floor: 81.505 s

Same night, driven **through the #697 entrypoint** (`remote_launcher start … -- -m
tools.ac_harness.auto_alien … --max-scale 1.15`). The two ladders form a controlled pair: both
reached `ggv_scale` **1.15**, and the *only* difference was the plant.

| stage | plant QSS floor | scale | best flying lap |
|---|---|---|---|
| base | 91.26 s | 1.00 | 96.286 s |
| iteration 1 | 91.26 s (refit no-op) | 1.15 | 84.587 s |
| **iteration 2** | **87.14 s** (refit `adopted=4 raised=1`) | **1.15** | **81.505 s** |

`selfplay done — completed` (**not** falsified) → the refit was **retained**. `recoveries=0`,
`recovery_capped=false`, `sim_dead=false`, 222.3 km/h, all three archives `is_valid: true`.
Evidence: `.scratch/harness-evidence/20260727T033059Z_alien_ks_porsche_911_gt3_r_2016_magione/`.

**Ladder 1 stepped to 1.20, falsified, and lost its refit — and stalled at 85.072 s. Ladder 2 capped
at a known-valid 1.15, kept the refit, and broke the floor.** ~3.5 s of the gain is attributable to
refit-retention alone, at identical scale. That is the direct evidence for #703.

**Assist-parity caveat (operator to adjudicate).** The epic describes the 82.7 s floor as "TC-off,
fixed setup". This run used CM **factory** electronics — `Abs:1`, `TractionControl:1` (what the real
GT3 has), `StabilityControl:0`, no auto-brake/auto-shifter/ideal-line, `AutoBlip:true`; measured
interventions ABS 81/3161 ticks, TC 24/3161. Track `3_clear` 26 °C, `s=1.0 t=1.0`, tyre blankets, no
wear/fuel. So G2's **numeric** criterion is met on a like-for-like hotlap config; a strict TC-off
comparison is one more ladder with `TractionControl:0`.

## Pace claim, stated precisely

G1's pace criterion is "within 5 % of TT top-10 in ≤20 autonomous laps" → ≤86.84 s. Every flying
lap tonight from 85.072 s down clears that band, and 81.505 s beats the floor outright. But these
runs are **not** the G1 gate as written:

- the combo is the **seed** combo (911 @ Magione), not an unseen one;
- the plant was **pre-identified** across earlier sessions and refined again here, so it is not a
  cold start.

So: the pace numbers — **and G2** — are met on the seed combo; the **cold-start, unseen-combo**
form of G1 is a separate, still-unclaimed gate, as are G1b and G3.

## How the ladder actually gains

`--max-scale` is hard-capped at 1.2 by design (`ALIEN_MAX_OVERSPEED_SCALE`: 1.2× speed is already
1.44× lateral g), and ladder 1's 1.20 falsification says that cap is honest. The way past it is
**not** a braver scale — it is the plant, as ladder 2 then demonstrated. Each valid
iteration refines the measured friction bins (`iteration 2 plant refined (lateral bins adopted=4
raised=1)`), which lowers the safe QSS floor itself: 91.3 s → **87.0 s** across this run. A fresh
ladder started at 1.0 on the *refined* plant therefore probes absolutely faster speeds than the
previous ladder's 1.15 — which is exactly what ladder 2 did, and it is what broke the floor. Not a
bigger `--max-scale`.

L3 also fired on the base and 1.15 stages (`refined 2 corner(s), 5 reverted to safe-QSS,
predicted gain 210 ms`), and correctly reverted all 7 corners once the plant changed under it.

**But that refinement did not survive** — and this is the finding that matters for G2. One ladder
iteration bundles **two independent changes**: a refit computed from the *previous* iteration's
validated archives, plus the envelope scale step. `auto_alien.py:601` reverts the plant to
`last_valid_bytes` on any falsified iteration, so the 1.20 drive failure discarded the 87.0 s fit
that iteration 1's *valid* 85 s laps had earned. Live plant is back to `f5f274ba4cb0` / QSS
91.26 s (confirmed on the next run's line build). Filed as
[#703](https://github.com/agorokh/ac-copilot-trainer/issues/703) rather than changed in place —
"a plant that produced a failing drive is not trusted" is a defensible reading, so the design call
is not mine to make silently.

**Workaround, now proven (needs no code change):** cap the ladder at a **known-valid** top rung
(`--max-scale 1.15`) so the refit is retained. Ladder 2 did exactly this and reached 81.505 s —
3.5 s faster than ladder 1 at the identical scale. Until #703 is resolved, never let the ladder's
top rung be one you expect to falsify, or you pay for the refit twice.

## #627 hold-duration data point (~4 h hold)

The rig had **not** been rebooted (boot 2026-07-25T16:16, ~27.7 h uptime) and the accumulator was
already post-onset from the previous session. After a **~4-hour hold with no launches** this run
obtained **~6 consecutive launch cycles** (3 in the base stage, 2 in iteration 1, 1 in iteration 2),
all landing. Against the previously recorded arms — ~9 cycles from a cold boot, **2** after a
35-minute hold — this says recovery from a hold **scales with hold length** and a multi-hour hold
gets most of the way back to a fresh boot. Same caveat as the prior data point: n=1 per arm,
observed while pursuing #529 evidence rather than as a controlled measurement.

Both ladders ran on that one hold — the second obtained a further ~5 cycles (3 in its base stage,
1 per iteration) immediately after the first, for **~11 landed launch cycles in one evening** with no
reboot and no `sim never reached LIVE` failure at any point.

Consequence: a reboot was **not** needed. The previous session's "the honest unblock is a reboot"
resume was wrong — a multi-hour hold was sufficient.

## Rig invariant re-confirmed

The primary checkout (which the AC app junction serves) was found at `49f90f1` — stale by four
commits, and missing #696 itself. Detached to `origin/main` @ `670b529` before the run; every stage
then reported `installed app provenance: match`. This is the third session in a row where the
#575/#543 stale-app trap was live on arrival — the pre-run check earns its place in the runbook.
