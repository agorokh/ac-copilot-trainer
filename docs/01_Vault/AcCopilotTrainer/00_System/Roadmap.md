---
type: index
status: active
memory_tier: canonical
created: 2026-06-30
updated: 2026-07-24
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# Product roadmap

Living plan by product vertical. **Canonical tracker:**
[ROADMAP umbrella #401](https://github.com/agorokh/ac-copilot-trainer/issues/401) — this file is
its **durable twin** (state-consistency pair; see Invariant below). Fully reconciled against
merged code on **2026-07-24** (/backlog-steward, operator-approved). Per-claim evidence and the
full capability matrix live in the issue — this file is the map, not the changelog.

## One-line diagnosis (2026-07-24)

The 2026-06-30 longitudinal gaps (session/driver entities, sector deltas, diagnosis depth,
debrief, fuel strategy, setup loop, progression) **all shipped as thin slices** in the
2026-06-30 → 07-02 sprint. The frontier now: **rig reliability (#627 blocks every live gate) ·
autonomy reality gates (#529) · coaching actionability V2 (#675) · surface finish
(#531 G/H/I · #86 · #381 · #117)**.

## Vertical → status map

| Vertical | Status (2026-07-24) | Owning issue(s) · key anchors |
|---|---|---|
| 0. Rig reliability & instrumentation | **OPEN — blocks all live gates** | [#627](https://github.com/agorokh/ac-copilot-trainer/issues/627) master brief · [#625](https://github.com/agorokh/ac-copilot-trainer/issues/625) overlay A/B. PR #626 `resilient_launch.py`; #630 forensics (PRs #637/#642/#644/#646/#647); #668 graceful teardown (PR #669); upstream [acc-extension-config#622](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/622) |
| 1. Telemetry & data platform | Delivered | #402 closed — PR #415 (`coaching_lake/retention.py`, `driver_profile.py`) · #488 closed (PRs #483/#497/#500/#503) |
| 2. Reference & benchmarking | Delivered | #408 closed — PR #418 (`sector_benchmark.py`, SuperLap) + PR #455 · #353 closed (`tools/tt_ingest/`) |
| 3. Diagnosis depth | Delivered | #405 closed — PR #422 (`lap_dynamics.py`, `corner_attribution.py`) · #442 closed (gear) |
| 4. Real-time + debrief | Delivered · V2 open | #404 closed — PRs #423/#453 (`session_review/report.py`) · coach V2 **#675** (successor of #522; V1 via PRs #523/#525/#538, incl. PR #656 calibration-bypass fix) |
| 5. Tyre/brake/fuel mgmt | Delivered thin | #406 closed — PR #416. Wet/brake-temp management depth unowned |
| 6. Setup ↔ driver loop | Delivered | #407 closed — PRs #417/#433 (`setup_advisor.py` family) · continues under #529 P4 (PR #659, `alien_scientist.py`) |
| 7. Driver model & progression | Thin slice · depth unowned | #403 closed — PR #419 (`driver_progression.py`). Skill classification / curriculum has **no open owner** — flag for operator |
| 8. Delivery surfaces | Atelier delivered · polish open | #432 closed-as-delivered (PRs #437/#444 · #434/#445 · #430/#446; code remainder **#673**) · #479 SimHub closed · [#531](https://github.com/agorokh/ac-copilot-trainer/issues/531) Parts A–F delivered (PRs #547/#590/#595/#615/#618), G/H/I open · [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) on-device smoke (camera-gated) · [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) baked-clip A/B listen · [#117](https://github.com/agorokh/ac-copilot-trainer/issues/117) haptics 0/4 built (#534 Part C waits on it) |
| 9. Session review & data products | Delivered | #404 closed — report artifact + review browser |
| —. Autonomy & self-test | Active program | #154 closed 2026-07-11 → [#529](https://github.com/agorokh/ac-copilot-trainer/issues/529) Alien Lap Platform: P1–P5 merged (PRs #535/#551/#573/#579/#583/#656/#659), reality gates G1/G1b/G2/G3 open, unbuilt layers **#674** · [#534](https://github.com/agorokh/ac-copilot-trainer/issues/534) enrichment registry (zero built; Part A buildable now) · all rig-gated work blocked on #627/#625 |

## Sequencing (current program)

1. **No-rig track:** #534 Part A (car-class resolver) · #675 calibration-bypass fix (PR #656 side effect) · #381 baked-clip listen.
2. **Rig track (operator-gated):** #627 boot-scoped suspect arms → redesigned #625 overlay A/B → watch acc-extension-config#622.
3. **When the rig returns:** #529 reality gates + first real scientist batch · #531 Part G latency gate + Part F rig-verify · #86 on-device smoke.
4. **To adjudicate:** vertical-7 quality depth · vertical-5 strategy depth · #674 (#529 L4 stint optimizer, Layer-0 observer, meta-prior transfer).

## Invariant

This file is **THE pair** of the #401 capability matrix (pairing declared 2026-07-24 — it
resolves the earlier ambiguity where this file named `Project State.md` as the pair while the
issue named this file). When a gap flips or an owning issue changes state, flip it in **both the
#401 body and this file in the same change**; `Project State.md` is downstream context, not part
of the pair. Reconcile against **merged code**, not issue titles — every "Delivered" row above
carries its delivering PR so the next session doesn't re-implement shipped work.