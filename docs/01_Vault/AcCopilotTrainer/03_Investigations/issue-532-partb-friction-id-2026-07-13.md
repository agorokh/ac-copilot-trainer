---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/532
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-532-plant-id-handshake-2026-07-12.md
---

# #532 P1 Part B — per-combo friction-ID plant (uncertainty-aware GGVModel)

**Epic:** #529 (P1). Child #532. **PR [#551](https://github.com/agorokh/ac-copilot-trainer/pull/551) MERGED** (squash `155aac6`, 2026-07-13), auto-closing **#552** (layout key). Part A (handshake constants) shipped in PR #535.

## Goal

Replace the single hardcoded `generic_gt3_ggv()` on the `--driver ggv` path with a **per-combo `GGVModel` machine-measured in-sim**, safe-envelope-blended against the generic prior — so a genuinely different car drives on its own friction envelope while the reference 911 GT3 R never regresses.

## What shipped (`ggv_profile.py`, `plant_id.py`, `auto_drive.py`)

- **Friction capture:** `HandshakeController` samples `(speed_kmh, accg_lat, accg_lon)` from the physics accG channel across the probe drive, each row `source`-tagged (`brake_probe` / `accel_sweep` / passive), plus one **active brake-at-speed probe** (firm straight-line braking — never a lateral push, which spins the GT3, live-disproven #259/#244).
- **Fit (reuse):** `ggv_profile.ggv_from_telemetry` — no duplicated fit. `source`-tagged probe rows may qualify a bin at a lower sample count and their percentile is preferred when stronger, so the WOT / brake-probe samples are **not diluted** by passive cruising.
- **Safe-envelope blend (`blend_ggv_safe`):** lateral **pinned to the prior** (both ceiling and floor — a conservative AC-valid drive never reaches the lateral limit, so a measured value below prior is a *lower bound*, not a weaker car; `k_aero_lat`=0). Ellipse exponent pinned to the prior (its boundary needs limit-reaching data). Braking / drive accel adopted **only where a `supported_longitudinal` overlay confidently exceeds the prior across its observed speed support** (tapered to the prior at the edges), so an under-measurement never lowers the plant.
- **Persistence + consumption:** artifact schema v2, keyed `car + track + layout + setup` (layout added in-merge, #552); `plant_ggv_model` resolves the identified `GGVModel`; `GGVModel.from_dict` / `__post_init__` reject non-finite / non-positive `ellipse_n`/grip so a corrupt artifact falls back to the generic plant instead of crashing.

## The live-caught regression (why operator-grade verification mattered)

The first live Magione handshake exposed a bug the off-sim tests could not: the pace-0.8 probe drive fits `mu_lat≈1.17 g`, and the initial blend **trusted** that measured-below-prior value. But the 911 GT3 R genuinely reaches **~1.5 g** at Magione (#244) — 1.17 is an under-measurement from gentle driving, so driving that plant would carry less corner speed and **regress the reference car**. Fix: pin lateral + ellipse to the prior; braking/drive may only *raise* the plant where a supported overlay exceeds the prior. The operator then hardened this in-merge with the `source`-tagged / tapered `supported_longitudinal` overlay + a stronger fit-validity/coverage provenance.

## Verification

- **Off-sim:** full Part B suite green on merged `main` (`make ci-fast` OK).
- **Live (rig, AG_PC, 2026-07-13) — merged code `155aac6`:** the handshake fit a **valid ggv block from 5968 real Magione friction rows** (`ggv_ok=true`), blended to `blend_source={lateral:prior, brake:prior, drive:prior}` → **no regression by construction** for the reference car. Probes passed; persistence was correctly vetoed only because `acs.exe` crashed mid-drive (`sim_dead`). Evidence: `.scratch/harness-evidence/532b-handshake-merged/report.json`.
- **Cross-check (pre-merge core `b2c7ef4`):** independent handshake persisted a Magione artifact with `mu_lat=1.5 == prior` (regression check PASS), 1718 rows.
- **Operator (filesystem, #553):** `save`/`load_plant_artifact` produced 3 distinct layout-keyed files.
- **Closed-loop full-lap A/B (identified vs generic lap time): COMPLETE (2026-07-13).** Generic (`--use-plant off`) **108.447 s** vs identified (`--use-plant auto`, `plant artifact loaded (identified friction plant)`) **107.781 s** — 0.67 s faster → **no regression** (lap-to-lap variance; the merged identified plant == prior on every curve). Both AC-valid, `sim_dead=False`. Evidence: `.scratch/harness-evidence/532b-ab-generic/` + `532b-ab-identified2/`. Posted to [#532](https://github.com/agorokh/ac-copilot-trainer/issues/532#issuecomment-4957006398).
- **CORRECTION:** the earlier "rig-gated, needs a reboot" note was **wrong** — the flakiness was a **stale Content Manager instance** (re-issuing the `acmanager://` URL reaches the same stale CM), not the plant and not a reboot. Root-caused + fixed in **#558 / PR #559** (`2cfd662`): the harness now restarts CM on a cached-session / persistent-stall mismatch so the next launch cold-starts fresh. See [[issue-558-cm-restart-launch-reliability-2026-07-13]].

## Follow-ups (separable)

- **Slip-saturation / limit-reaching lateral pass** — the only safe way to *lower* the lateral plant for a genuinely weaker car (capture `wheelSlip`, gate lowering on saturation). Deferred; recorded in the artifact's measured lower-bound provenance.
- Online yaw-rate-vs-utilization derate (Council self-healing-plant idea) — separable controller work.
