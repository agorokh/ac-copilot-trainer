---
type: investigation
status: resolved
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/543
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/issue-532-plant-id-handshake-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/issue-532-partb-friction-id-2026-07-13.md
---

# #543 — uncertainty-aware plant identification

**Issue [#543](https://github.com/agorokh/ac-copilot-trainer/issues/543) CLOSED by PR
[#564](https://github.com/agorokh/ac-copilot-trainer/pull/564)** (squash
[`3193e1b`](https://github.com/agorokh/ac-copilot-trainer/commit/3193e1b), 2026-07-13).

## Shipped contract

- `python -m tools.ac_harness.auto_drive --identify-plant` is the single automated driving path:
  it launches AC, runs designed brake/traction probes, completes thermal cohorts, fits the GGV
  envelope, persists the combo-qualified plant artifact, and emits a machine-readable report.
- Friction observations carry tyre-state uncertainty rather than collapsing every sample into one
  scalar. The persisted model has measured brake/drive support by speed and thermal state, explicit
  confidence bounds, conservative lookup behavior outside support, and setup/car/track/layout
  identity gates.
- Probe rows are isolated by a current-run nonce and accepted only with a complete thermal cohort.
  Archive attribution additionally requires the requested combo and stable setup snapshot hash, so
  stale or cross-combo laps cannot silently satisfy identification.
- Lua telemetry/archive handling now preserves late graphics counters, validates callable/direct
  scalar surfaces, and keeps physics sampling alive when optional graphics reads fail.

## Automated-harness proof on the real simulator

- Identification report:
  `.scratch/harness-evidence/20260713T235324Z_ks_porsche_911_gt3_r_2016_magione/report.json`.
  PASS: two laps, 4,984 m, 141.5 km/h, zero recoveries, strict pipeline green.
- The run collected 431/431 nonce-attributed probe rows and 4,000 friction rows. Both selected cold
  laps had 100% coverage, 99.95–100% stability, and 6.18–6.57 °C wheel spread. The resulting model
  contains 30 uncertainty bins, including nine measured brake and eight measured drive bins.
- The artifact was observed at
  `Documents/Assetto Corsa/plant_id/ks_porsche_911_gt3_r_2016__magione.json`.
- A second automated consumer run loaded the identified plant and completed a real 122.990 s lap at
  199.8 km/h with zero recoveries. Its auxiliary WebSocket tap missed the connection heartbeat, so
  that report's strict-pipeline bit is correctly false; this does not weaken the strict identification
  run or the observed plant load.
- Final verification: 243 focused tests passed; `make ci-fast` passed with 2,715 tests, 113 skipped,
  and 87.30% coverage. GitHub build/docs/conformance passed, all review threads resolved, and the
  resolve gate was clean after the mandatory cooldown.

## Durable lesson

Plant identification is an experiment, not a passive lap scrape. Provenance must bind each probe and
thermal cohort to the current automated run, combo, layout, and setup snapshot. Consumers should use
measured support conservatively and preserve uncertainty instead of extrapolating false precision.
