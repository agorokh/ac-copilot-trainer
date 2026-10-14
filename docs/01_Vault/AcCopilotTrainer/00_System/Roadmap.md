---
type: index
status: active
memory_tier: canonical
created: 2026-06-30
updated: 2026-10-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# Product roadmap

Canonical tracker: [ROADMAP umbrella #401](https://github.com/agorokh/ac-copilot-trainer/issues/401). This file is its durable state-consistency pair. **Shipped-state refresh 2026-10-14**, merged software through PR #843 (`c8dbfd46`) and fresh tracker records; its reviewed build is distributed. Existing not-this-cycle, C2 and operator/rig gates remain; this does not reactivate parked implementation.

## Current diagnosis

Longitudinal thin slices, Coach V2, L0/L4/META and car-class/SimHub software have shipped. Current acceptance is #813's physical display/MAP proof after merged #814 and #804's separate verification. Retained work includes #529 G1 pace/G3 human improvement, #627 terminal-wedge investigation, #531 Phase 3/broader verification, #86 full smoke/photo and #117 hardware. [#815](https://github.com/agorokh/ac-copilot-trainer/issues/815) has completed Part A research and shipped native provenance/cache inspection ([#834](https://github.com/agorokh/ac-copilot-trainer/pull/834)), offline Game Point review ([#836](https://github.com/agorokh/ac-copilot-trainer/pull/836)) and silent voice shadow validation ([#839](https://github.com/agorokh/ac-copilot-trainer/pull/839)). Expanded Part D live acceptance remains OPEN / acoustic NO_GO. Output-channel, capture and independent deadline changes shipped in [#843](https://github.com/agorokh/ac-copilot-trainer/pull/843), merged as `c8dbfd46`, with its reviewed build distributed; `voice.live_acceptance.record` / `rig_watchdog.run_watchdog`. Track Titan remains; software dispatch timing is not calibrated audible-phrase proof, and assisted/unknown traces are not human progress. The [dated #815 checkpoint](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6173147463) records passing local CI; the packaged OFFLINE REPORT UI was subsequently observed at the same head with shared numeric analysis and silent replay, while human evaluation/live activation remained NO_GO. The same verified package was then distributed to the existing launcher target with the prior binary backed up and installed self-test passing; acoustic acceptance remains unproved.

## Vertical → status map

| Vertical | Shipped evidence | Retained owner / boundary |
|---|---|---|
| 0. Rig reliability | #626/#629/#637/#642/#644/#646/#647/#669; #726 `LaunchVerdict.NOT_DRIVABLE` / v4; #730 `refreshActiveReference` and #809 `bestForSetups` / `lap_metadata.read` finite-scan fixes. | #627 OPEN, block:C2. #625 CLOSED; #725 `init_perturber_ab` tooling. No inferred physical experiment, terminal-wedge closure or present rate. |
| 1. Telemetry/data | #402/#488 closed; #415/#483/#497/#500/#503, `retention.py` / `driver_profile.py` and telemetry/tyre channels; #815 native provenance/cache inspection #834, `lap_qualification.qualify_archive` / `moza_ingest.normalize.normalize_view`. | Shared qualification separates parsing from eligibility; assisted records remain excluded from human progression. |
| 2. References | #408/#353 closed; #418/#455 `sector_benchmark.py`; `tt_normalize.build_reference_archive`; #815 A/B delivered. | Processed MOZA caches remain inspection-only. #815 expanded live/acoustic acceptance remains open; retain independent identity/coverage/control gates. |
| 3. Diagnosis | #405/#442 closed; #422 `lap_dynamics.py` / `corner_attribution.py`, #615 shift cues. | Existing diagnostics; no parallel analytics rebuild. |
| 4. Coaching/debrief | #404/#675 closed; #423/#453/#687, `CoachRuntime.calibrate_from_driver_lap` / `Scheduler` reslot / `select_between_lap_advice`; #815 silent recorded replay #839, `voice.shadow_replay.build_shadow_replay`. | #815 acoustic NO_GO; #843 capture/routing/deadline software and distribution complete. #529 G3 human outcome remains separate. |
| 5. Race management | #406 closed; #416 and #615 `RaceStatusTracker`. | Wet/brake-temperature strategy depth remains unassigned. |
| 6. Setup/scientist | #407 closed; #417/#433/#659. C1 #749/#750/#751/#764 closed; #766/#770/#776/#800 and #812 receipt; `evaluate_experiment` / `run_scientist`. | Corrected flying-only/matched-margin acceptance, falsified outcome; no setup/pace-promotion claim. |
| 7. Progression | #403 closed; #419 `driver_progression.py`. | Longitudinal depth is an operator decision; no unknown-origin/assisted laps counted as human progress. |
| 8. Surfaces | Atelier #437/#444/#434/#445/#430/#446; #673 closed via #681 `hud_settings.lua`/`racing_line.lua`; #677 closed via #680 `persist.cpp`/`link_stats.cpp`/`screen_debug.cpp`; #381 closed via #690 `ProsodyShaper`; #531 A–F via #547/#590/#595/#615/#618. | #814 merged as `b513d05` (2026-10-13), `track_map.build_corner_comparison` / `lap_dynamics.corner_phase_boundaries`; #813 retains P7/operator valid-lap acceptance. Its [dated owner checkpoint](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6134453203) reports distribution verified; small ESP32 physical verification alone is [operator-waived](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6140089525), not verified. #819 records capture evidence; the [dated owner check](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6140184970) reported P7 disconnected. #804 retains separate verification. #531 G/H/I + broader proof, #86 smoke/photo, #117 hardware retain gates/dispositions. |
| 9. Review/data | #404 closed; #423/#453/#415; #815 offline Game Point review #836, `session_review.moza.build_moza_session_report` / `MozaOfflineOracle`. | Qualified native measurements; processed caches inspection-only and unsupported producer advice unavailable. Long-horizon dashboard depth remains unassigned. |
| Autonomy | #529 P1–P5 software; #674 CLOSED, #682 `environment_from_archives` / `plan_stint` / `meta_priors`. #812 separately records conservative retained-plant adoption and falsified original replay. | #529 OPEN, not-this-cycle. G1 pace unmet; G3 operator-gated. G2 repeatable 81.505/81.519 s evidence retained. |
| Enrichment | #534 A/B software #689/#692: `resolve_installed_car`, enriched session, `AcCopilotDataPlugin` lifecycle/replay. | #534 OPEN, not-this-cycle. No fresh live property proof; C→#117, dormant D, E documented options remain operator-owned. |

## Sequencing and dispositions

1. Continue #813's retained P7, live-electronics, operator-driven valid-lap/MAP and intentional-exit acceptance when the device is reachable and the human session is arranged. Small ESP32 physical verification alone is [operator-waived](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6140089525), not verified; the [dated owner check](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6140184970) reported P7 disconnected. #814 is merged and distribution is reported verified; #819 adds a capture receipt. The merge used an explicit operator review exception; no independent exact-head review is credited.
2. Coordinate evidence with #804 and #86 without merging or automatically closing distinct acceptance.
3. Continue #815's expanded Part D live/acoustic acceptance after shipped #834/#836/#839. #843 merged and its reviewed build was distributed; this is not audible acceptance. The bounded run independently stopped AC/sidecar after 360 s, but audio remains NO_GO: no located sync chirp, 90 microphone ADC backsteps and 5 loopback discontinuities. Ten anticipatory dispatches matched ten measured brake events with 2.303–3.302 s software lead, not acoustic completion. Require calibrated complete-phrase and suppression/truncation evidence for a live go decision. Preserve Track Titan, the existing voice engine and 160 canonical assisted-lap restrictions; no human/reference/progression promotion.
4. Preserve #627 block:C2 and not-this-cycle on #529/#531/#534/#401/#117/#86. No resumed rig, audio, SimHub or hardware work follows from this refresh.
5. Preserve #529's original cold-start G1 budget/pace and G3 human proof until an explicit scope decision; reference availability and C1 closure do not complete them.

## Invariant

This file is **THE durable pair** of #401's capability matrix (declared 2026-07-24). Update **both #401 and this file in the same reconciliation** when an owner changes state or a capability flips. `Project State.md` is downstream context, not part of the pair. Reconcile merged code and retained acceptance; delivered software is not deployment or human-outcome proof.
