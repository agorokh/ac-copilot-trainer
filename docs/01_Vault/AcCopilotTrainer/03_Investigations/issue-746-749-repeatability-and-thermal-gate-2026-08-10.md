---
type: investigation
status: active
memory_tier: canonical
created: 2026-08-10
updated: 2026-08-10
issue: https://github.com/agorokh/ac-copilot-trainer/issues/746
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-g1-cold-p4-scientist-2026-08-08.md
  - AcCopilotTrainer/03_Investigations/issue-703-decoupled-ladder-2026-07-28.md
  - AcCopilotTrainer/03_Investigations/issue-529-pace-ladder-115-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #746 repeatability gate + #749 thermal gate — the two things capping EPIC #529 G1

## 1. The self-play oracle accepted UNREPEATABLE envelopes — #746, PR #748 MERGED `c9ec97c`

`evaluate_selfplay_iteration` accepted an iteration on *drive passed + zero recoveries + every
archived lap AC-valid*. Those prove an envelope was **survivable once**, not **repeatable**, so an
envelope the controller could not reproduce was retained and compounded into the plant.

Measured over every self-play-era archive on the rig — 31 oracle-passing batches with ≥2 flying
laps: **median spread 0.02 %**, only 4 above 1 %, and three pathologies at **5.2 / 17.7 / 22.0 %**.
The out-lap must be excluded or that 0.02 % median becomes ~19 % and every healthy batch trips.
Threshold set at 5 %.

**This changed the epic's own record.** The recorded G2 ladder (2026-07-26) had `80.791 s` then
`95.122 s` in one clean stint — both AC-valid, zero recoveries, 17.7 % — which the old oracle
accepted, so the 86.27 s-floor plant was **retained on it**. That ladder now stops at that rung and
the plant rolls back. G2 itself stands: ladder 2 ran `81.505 / 81.519` (14 ms apart) under the same
floor. What is withdrawn is *the retention of a plant refined from an unrepeatable stint*.

### What the eleven review rounds actually taught

17 defects found; **~6 were introduced by my own earlier fixes in the same PR**, and **2 were latent
in the test doubles**: `_SelfplayHarness` wrote a constant `lap_ms: 90000` into every fake archive
regardless of the times it reported, and two scientist fixtures numbered a *candidate* drive's laps
3–4 (a fresh standing-start session never does). **That is why eight rounds of green tests coexisted
with reachable holes** — the doubles had drifted from the real archive contract. Worth remembering
before trusting this suite again.

The design lesson: I introduced a third state — *"valid, but withheld from the refit"* — and every
consumer had to be taught about it separately (refit, scientist baseline, scientist candidate, rung
counter, persisted plant candidate). Review found **four of five** consumers I had missed. It was
replaced by the simple rule that an unattributable batch **falsifies** through the existing #703
keep-last-valid path, which deleted more code than it added.

Attribution now asserts the archive contract directly rather than proxying for it: well-formed,
positive and **contiguous from lap 1**, single `session_uuid`, and **reproducing the reported
lap-time stream in order**. Each weaker proxy was defeated by a concrete counter-example.

## 2. The thermal stability gate refuses second-session refits — #749 (OPEN, G1 critical path)

EPIC #529's stated lever for the unmet **G1 pace** gate is retained-plant compounding. On a second
session it does not compound: `ggv_from_lap_archives` raises `no thermally consistent valid lap
archives` and every refit is refused. Of seven eligibility terms exactly one fails —
`stability >= 0.80` (`DEFAULT_THERMAL_STABILITY_FRACTION`):

| batch | ggv_scale | core °C | stability | eligible |
|---|---|---|---|---|
| 2026-08-10 base | 1.00 | 63.5 | **1.000** | yes |
| 2026-08-10 it1 | 1.15 | 73.8 | **0.53** | no |
| 2026-08-09 it2/it3 | 1.15 | 68–69 | **1.000** | yes |

Wheel spread (9.9–12.0 °C) is under the 15 °C cap, coverage is 1.0, `setup_hash` is a real
`snapshot-sha256:` in both sessions.

**Two hypotheses were raised and then REFUTED by measurement — do not re-run them:**

1. *"A #740/#743 regression made `setup.snapshot` empty."* No — the 2026-08-08 archives that refit
   successfully have the identical empty snapshot. `setup_hash` is derived and non-`None` either way.
2. *"Temps are still climbing; give the tyres a settling budget (`--laps 6`)."* No — the traces show
   temps rise ~3 °C through a lap and **reset to the same value next lap**. It is a repeating
   per-lap *cycle*, not a climb to a plateau; extra laps repeat it. Accepted 2026-08-09 laps show
   the same shape at +2.1 °C. The discriminator is cycle **amplitude**.

**And a third claim of mine was withdrawn:** I framed this as *"the gate rejects the fast laps; the
better the plant gets the more its own evidence is discarded"*. The full history refutes the
generalisation — only **3 of 71** flying laps are ineligible, and on the 911 the single rejection was
a *slow* lap (145.36 s vs a 99.11 s eligible mean) across 57/58 eligible laps including the sub-82 s
G2 runs. It is a **rarely-firing gate that fired on the one batch that mattered**, so the real
question is narrower: *why huracan@spa at 1.15 specifically* (wheel spread 12 °C vs ~7 °C).

**Why not just lower the threshold:** the plant merge is strictly monotone (**raise-only**) and these
tyres run **cold** (63–78 °C vs 95 °C optimal), so grip rises with temperature. An untagged fit of a
lap that climbed 8 °C adopts the **hottest-sample** grip and then commands it from a cold start.
Council (3/5 answered) split: mistral + perplexity name temperature-tagged friction as the physically
correct fix; gemini prefers a bounded-`dT/dt` gate — which the amplitude finding also rules out.

## Ladder result (huracan@spa, retained plant)

base@1.00 **180.366 / 180.387** (vs 185.53 cold on 2026-08-08 = **5.2 s inherited carry**, so
compounding *works* when the refit lands) · it1@1.15 167.300 / 167.470 · it2@1.20 **FALSIFIED**
(`recovery cap (6) exceeded at 10366m`, 7 recoveries — honest physics). Refit refused throughout.

**Measurement-integrity note:** iteration 1's flying laps are **not clean** — three concurrent
`pytest` runs shared this 6-core i5-9400F while the car was driving. The base drive predates them
and is clean. The thermal finding is unaffected (it1's out-lap was already ineligible beforehand).

## Follow-ups

- [#749](https://github.com/agorokh/ac-copilot-trainer/issues/749) — thermal gate (G1 critical path).
- [#750](https://github.com/agorokh/ac-copilot-trainer/issues/750) — scientist compares **out-laps**.
  Recomputed: the `plateau_rear_wing` verdict direction **holds** on flying laps (101.961 vs
  107.595), so it is under-evidenced (n=1 flying lap per arm), not wrong — my earlier "suspect"
  framing was withdrawn.
- [#751](https://github.com/agorokh/ac-copilot-trainer/issues/751) — `lap_archives` not scoped to its
  batch. **This is the structural end of #746's review spiral**: rounds 4–11 all existed because the
  oracle reconstructs which laps were its own. Scope at source and they become assertions.
