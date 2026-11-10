---
type: index
status: active
memory_tier: canonical
created: 2026-06-30
updated: 2026-11-10
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/2026-11-10-185600Z-backlog-steward-ledger-snapshot-c4a91e.md
  - AcCopilotTrainer/03_Investigations/issue-627-c2-settled-2026-10-19.md
  - AcCopilotTrainer/03_Investigations/issue-534-simhub-plugin-install-2026-10-21.md
  - AcCopilotTrainer/03_Investigations/issue-86-device-capture-2026-10-19.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-23-074507Z-post-merge-pr934-815-run07-pass.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-072038Z-issue534-operator-gate-0ce53e.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-184420Z-issue529-retained-diagnostic-f793a1.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-27-070600Z-issue815-rendered-state-reconcile-274e004.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-10-185600Z-backlog-steward-reconcile-c4a91e.md
---

# Product roadmap

Canonical tracker: [ROADMAP umbrella #401](https://github.com/agorokh/ac-copilot-trainer/issues/401). This file is its durable state-consistency pair. **Shipped-state refresh 2026-11-10** (`/backlog-steward` run `c4a91e` at `main` `145c07a`), recording operator closing dispositions on [#815](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6777499356), [#534](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6777501131), and [#813](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6777498061), plus body refreshes on [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) and [#529](https://github.com/agorokh/ac-copilot-trainer/issues/529). Open backlog is now **4 issues**: active `#86`, `#529`, and `#401`, plus `#117` protected under `not-this-cycle` (with its decision 2C `#627` prerequisite settled on 2026-10-19).

## Current diagnosis

Longitudinal thin slices, Coach V2, condition-indexed thermal/grip gating (`#938` / [PR #940](https://github.com/agorokh/ac-copilot-trainer/pull/940) `274e004`), MOZA qualification & live voice/rendered-HUD engineering acceptance (`#815` / [PR #934](https://github.com/agorokh/ac-copilot-trainer/pull/934) `1deb45d`, [PR #944](https://github.com/agorokh/ac-copilot-trainer/pull/944) `d881fb9`), car-class resolver/SimHub 9.13.2 live readback (`#534` / [PR #914](https://github.com/agorokh/ac-copilot-trainer/pull/914), [PR #916](https://github.com/agorokh/ac-copilot-trainer/pull/916) `696292a`), and L0/L4/META layers have shipped.

- **#813 linkage auto-close DISPOSITIONED (2026-11-10, [#813 comment 6777498061](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6777498061)):** Closed 2026-10-15 via [PR #848](https://github.com/agorokh/ac-copilot-trainer/pull/848) linkage; owner formally accepted `#531` / [PR #849](https://github.com/agorokh/ac-copilot-trainer/pull/849) autonomous P7 evidence alongside `#814` (`b513d05`) and `#819`, waiving the separate human-driven P7 lap and automatic menu-exit stale transition.
- **#627 (Reliability / C2) CLOSED (2026-10-19, [PR #905](https://github.com/agorokh/ac-copilot-trainer/pull/905) `6574b15`, [settled C2 node](../03_Investigations/issue-627-c2-settled-2026-10-19.md)):** Settled after report schema v6 ([PR #877](https://github.com/agorokh/ac-copilot-trainer/pull/877)), `probe_only` ([PR #879](https://github.com/agorokh/ac-copilot-trainer/pull/879)), CLI-only Stable AC ([PR #884](https://github.com/agorokh/ac-copilot-trainer/pull/884)), and `journal/lap-metadata-index.json` + `frame_hitch.lua` ([PR #898](https://github.com/agorokh/ac-copilot-trainer/pull/898), closing [#897](https://github.com/agorokh/ac-copilot-trainer/issues/897)).
- **#534 (Car Enrichment Registry) CLOSED (2026-11-10, [#534 comment 6777501131](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6777501131)):** Parts A+B live-verified on SimHub 9.13.2 (`unknown` → `1` idle; `rear-engine-gt` → `1.15` on live 911 GT3 R @ Magione, [#534 comment 6330968961](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6330968961)). Part C (wind curve) remains owned by parked **#117** (`not-this-cycle`); Parts D (pedal haptics, `#119` dropped) and E (optional ShakeIt experiment) are formally dropped/deferred unless revived via a new issue.
- **#815 (MOZA Qualification & Consumers) CLOSED (2026-11-10, [#815 comment 6777499356](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6777499356)):** All 18/18 Part A–D clauses passed across Run 07 (`1deb45d`: `12/12` phrases complete, `±25.0 ms` timebase, `4773 ms` / `2000 ms` brake leads, byte-exact `audio.ini` restore) and Clause 38 rendered-HUD inspection (`d881fb9`: 14 HUD frames + `hud.png`). `human_live_qualification` remains `NOT_ESTABLISHED_BY_THIS_ENGINEERING_CAPTURE`: processed MOZA caches stay inspection-only and MOZA/legacy-unknown/AI-assisted records (`174` ledger entries) stay unpromoted.
- **#86 (ESP32 Rig Screen Phase-2 UI — OPEN):** Shipped simulator gate ([#858](https://github.com/agorokh/ac-copilot-trainer/pull/858)), native CSP Setup Exchange ([#862](https://github.com/agorokh/ac-copilot-trainer/pull/862)/[#875](https://github.com/agorokh/ac-copilot-trainer/pull/875), Spa browse→apply confirmed [comment 6255873976](https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6255873976)), PT 96-byte `PT_SETUP_NAME_MAX` wrapping ([#891](https://github.com/agorokh/ac-copilot-trainer/pull/891) `54801e6`), and LVGL framebuffer `screen_capture` ([#904](https://github.com/agorokh/ac-copilot-trainer/pull/904)/[#906](https://github.com/agorokh/ac-copilot-trainer/pull/906), Spa Copilot capture [comment 6260669420](https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6260669420)). Remaining: 5 Copilot render differences visual decision at the next rig session + pit-session `screen_capture` receipts for PT load and SE download→install→PT load at Spa (rebuild Game Point `16068f3` via `--build-exe` if using packaged launcher).
- **#529 (Alien Lap Platform — OPEN):** Retained McLaren@Magione diagnostic ([PR #937](https://github.com/agorokh/ac-copilot-trainer/pull/937) `00bf871`, `95.226 s`, `+27.33%`) surfaced `tools/lap_qualification.py:qualify_archive` blocking native harness `authority="ai"` archives on `use="plant_fit"`. `/roadmap-expansion` ([PR #939](https://github.com/agorokh/ac-copilot-trainer/pull/939) `469e2b5`, [slate](../03_Investigations/roadmap-expansion-2026-10-24.md)) defined `REX-20261024-01` (G1), `REX-20261024-02` (**CLOSED** in `#938` / `PR #940` `274e004`), and `REX-20261024-03` (G3 drill sequencer — `#938` and `#815` issue gates both closed; requires qualified human AC session archives and operator promotion).

## Vertical → status map

| Vertical | Shipped evidence | Retained owner / boundary |
|---|---|---|
| 0. Rig reliability | #626..#669, #726 (v4), #730/#809 finite scans, #876 (v5), #877 (20 s stall floor, v6), #879 (`probe_only`), #884 (CLI-only Stable AC), #898 (`lap-metadata-index.json` + `frame_hitch.lua`, closing #897), #871 HUD frames, #923 `rig_lock hold`. | **#627 CLOSED (2026-10-19)**, [PR #905](https://github.com/agorokh/ac-copilot-trainer/pull/905); #625 CLOSED (#725). Reopen on ≥ 20 s graphics pin with physics advancing on v6. Upstream `acc-extension-config#622` open. |
| 1. Telemetry/data | #402/#488/#897/**#815** closed; #415/#483/#497/#500/#503/#834/#863/#898; `qualify_archive` / `normalize_view`; canonical assisted-lap ledger `174` entries (#935/#937). | Shared qualification separates parsing from eligibility; `#529` owns the pending operator policy decision on native harness `authority="ai"` `use="plant_fit"`. |
| 2. References | #408/#353/**#815** closed; #418/#455 `sector_benchmark.py`; `tt_ingest`; #815 Run 07 acoustic & rendered-HUD PASS (`1deb45d`, `d881fb9`). | **#815 CLOSED (2026-11-10)** ([comment 6777499356](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6777499356)): processed MOZA caches stay inspection-only and MOZA/legacy-unknown artifacts remain unpromoted. |
| 3. Diagnosis | #405/#442 closed; #422 `lap_dynamics.py` / `corner_attribution.py`, #615 shift cues. | Existing diagnostics; no parallel analytics rebuild. |
| 4. Coaching/debrief | #404/#675/#854/#938/**#815** closed; #423/#453/#687/#839/#865/#868/#869/#872/#873/#934/#940/#944. | `#529` G3 human outcome + `#854` curvature corner fallback tracked under `REX-20261024-03` (`#938` & `#815` closed; consumes qualified human AC session archives). |
| 5. Race management | #406/#938 closed; #416, #615 `RaceStatusTracker`, [PR #940](https://github.com/agorokh/ac-copilot-trainer/pull/940) (`274e004`). | Condition-indexed thermal & wet grip gating shipped (`274e004`). |
| 6. Setup/scientist | #407 and C1 #749/#750/#751/#764 closed; #417/#433/#659/#766/#800/#812; native CSP Setup Exchange #862/#875 (Spa browse→apply confirmed 2026-10-18). | Corrected flying-only/matched-margin scientist acceptance (falsified outcome, not pace promotion). Runtime `setup.load` positive branch is operator-only (`ac.isCarResetAllowed()`, #466). |
| 7. Progression | #403 closed; #419 `driver_progression.py`. | Multi-lap drill locking & phase-space frontier targets scoped in `#529` `REX-20261024-03`; assisted/unknown-origin laps excluded from human progress. |
| 8. Surfaces | #430..#446 Atelier; #673/#677/#381/#531/#804/**#813** closed; Game Point #882/#884/#887 (`16068f3`)/#894; #86: #858/#862/#891/#904/#906. | **#813 dispositioned 2026-11-10** ([comment 6777498061](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6777498061)). **#86 OPEN**: 5 Copilot render differences decision + pit-session PT/SE `screen_capture` at Spa (rebuild Game Point `16068f3` if used). **#117 OPEN (`not-this-cycle`)**. |
| 9. Review/data | #404/**#815** closed; #423/#453/#415/#836 `build_moza_session_report` / `MozaOfflineOracle`. | Processed caches inspection-only; long-horizon dashboard depth unassigned (`R2` in [roadmap-expansion-2026-10-24.md](../03_Investigations/roadmap-expansion-2026-10-24.md)). |
| Autonomy | #529 P1–P5 software; #674 CLOSED (#682); #812 C1 receipt; #856 canonical turn names. | **#529 OPEN**: cold-start G1 unmet (`97.378 s` cold-start; `95.226 s` retained diagnostic, PR #937 `00bf871`). Pending operator calls: `authority="ai"` `use="plant_fit"` policy (`lap_qualification.py`), `REX-20261024-01` (G1), and human session selection for `REX-20261024-03` (G3). G2 repeatable `81.505/81.519 s` retained. |
| Enrichment | #534 A/B software #689/#692 + live SimHub 9.13.2 readback #914/#916 (`rear-engine-gt` → `1.15`). | **#534 CLOSED (2026-11-10)** ([comment 6777501131](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6777501131)): Part C owned by parked **#117** (`not-this-cycle`); Parts D & E dropped/deferred unless revived via a new issue. |

## Sequencing and dispositions

1. **#813 is CLOSED and DISPOSITIONED (2026-11-10, [comment 6777498061](https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6777498061)):** owner accepted `#531` / [PR #849](https://github.com/agorokh/ac-copilot-trainer/pull/849) autonomous P7 evidence alongside `#814` (`b513d05`) and `#819`, waiving the separate human-driven P7 lap and automatic menu-exit stale check.
2. **#86 remains active** (body refreshed 2026-11-10): next rig session decides the 5 Copilot render differences ([comment 6260669420](https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6260669420)) and captures pit-session PT setup load + SE download→install→PT load at Spa (rebuild Game Point `16068f3` if using packaged launcher).
3. **#815 is CLOSED (2026-11-10, [comment 6777499356](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6777499356))** on Part A–D engineering PASS (`1deb45d` + `d881fb9`); MOZA/legacy-unknown and AI-assisted records (`174` ledger entries) stay unpromoted.
4. **#627 C2 (2026-10-19) and #534 (2026-11-10, [comment 6777501131](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6777501131)) are CLOSED.** Preserve `not-this-cycle` on **#117** (owns former `#534` Part C wind curve; `#627` deferral prerequisite settled).
5. **#529 remains active** (body refreshed 2026-11-10): operator decisions govern `authority="ai"` `use="plant_fit"` eligibility (`tools/lap_qualification.py`), `REX-20261024-01` (G1), and qualified human session selection for `REX-20261024-03` (G3).

## Invariant

This file is **THE durable pair** of #401's capability matrix (declared 2026-07-24). Update **both #401 and this file in the same reconciliation** when an owner changes state or a capability flips. `Project State.md` is downstream context, not part of the pair. Reconcile merged code and retained acceptance; delivered software is not deployment or human-outcome proof.
