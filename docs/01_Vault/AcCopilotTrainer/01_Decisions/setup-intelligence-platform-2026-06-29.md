---
type: decision
status: draft
memory_tier: canonical
created: 2026-06-29
updated: 2026-06-29
relates_to:
  - AcCopilotTrainer/01_Decisions/curated-setup-as-data-platform-entity-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/curated-setup-hash-bridge-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
---

# Decision (DRAFT): Setup Intelligence Platform (SIP)

**Status: proposed — pending operator go-ahead + the storage-ambition call (see Open decisions).**

## Context (operator directive, 2026-06-29)

Car setups are a *core* part of coaching. The target is a **frontier, enterprise-grade Setup
Intelligence Platform**: model the *entire* setup (everything Pocket Technician exposes), interconnect
**setup × tyre/compound × conditions × track × measured outcome**, and close the loop so the autonomous
harness drives N setups itself, measures real results, attributes them, and learns *what actually works*
— not a-priori physics, not a JSONL in a folder.

## Honest correction to my earlier framing

The storage foundation is **better than "a scratch file" but the intelligence on top was under-built.**
The analytical store is already a real **DuckDB lakehouse** (`tools/coaching_lake`, verified: 213 laps /
702 corners / 375k samples, 46s idempotent rebuild) with a `laps/corners/setup_params/samples` star and
a `setup-effect` flagship query. The JSONL registries (`setup_catalog`, `setup_optimizer`) are
**append-only catalog/experiment indices** DuckDB reads natively — not the store of record. My
`setup_catalog` is one correct brick (the verified djb2 identity bridge). What's missing is the platform.

## The four real gaps (the actual work)

1. **No per-car setup SCHEMA.** `setup_model.from_spinners()` *receives* `{min,max,step}` from
   `ac.getSetupSpinners()` and **throws them away**; `_BASE_SPECS` is a hardcoded ~25-section subset. We
   cannot enumerate the full spinner space, decode clicks→engineering units, or validate candidates for
   an arbitrary car. (Directive #1.)
2. **`setup_params = 0`.** The rig doesn't snapshot the setup at archive time, so every setup×outcome
   join is structurally ready but data-starved.
3. **No Tier-B channels archived.** `wheelSlip / wheelsPressure / tyreCoreTemp` are live-mmap only →
   tyre/condition attribution is inferred, not measured.
4. **No read/WRITE surface + open loop.** No `getSetupSpinners`/`setSetupSpinnerValue` anywhere — the
   harness can drive but cannot *change* a setup. The optimizer→harness→lake loop is unwired.

## Decision

Build SIP **on the existing lakehouse** in 5 phases. Three versioned, hash-keyed entities:
**CarSetupSchema** (NEW — full per-car spinner space w/ ranges/units/steps/`displayMultiplier`/linked
groups), **SetupInstance** (EXTEND — keep raw `.ini` as immutable interchange + ACC-style *dual* raw-
click **and** engineering values, reuse the verified `canonical_hash` identity), **Experiment/DrivenResult**
(EXTEND — setup driven under a first-class **condition_bucket** = compound × air-band × track-band ×
grip × wet/dry, with lineage for A/B sweeps).

**The differentiator:** a closed **autonomous setup-sweep loop** generating *original* empirical data.
No competitor automates this — Trophi.ai = technique-only ("the technique your setup can't teach"),
Track Titan = cloud pro-setup auto-install, Garage61 = community-corpus filtering, VRS = bundled
setup+telemetry. Generating our own data is also the **IP-defensible** path (their ToS ban setup
redistribution).

**Steal:** ACC's dual click+engineering representation; `getSetupSpinners()` as the schema oracle;
condition-bucket as a first-class key; VRS's "bundle setup *with* the reference lap that proves it";
SE's RSA machine-signing for harness-upload anti-abuse; Bayesian opt + Latin-hypercube DoE seeding.

## Roadmap (rig-gated work is the critical path)

- **P0 — Schema capture:** `setup_reader.lua::snapshotSpinners` → versioned `car_setup_schema` asset;
  fix `from_spinners()` to keep ranges; range-aware `ParamSpec`. *(rig-gated; parallel to all)*
- **P0b — Populate `setup_params` + Tier-B:** snapshot setup at archive time; decode clicks→engineering
  in `build_analytics`; persist `wheelSlip/tyreCoreTemp`; promote compound + condition_bucket. *(the #1
  unlock — zero empirical value until this ships; front-load it.)*
- **P1 — Write surface:** `setup_control.lua` `applyCandidate` (schema-validate → write → read-back
  confirm) + WS `getSchema/applySetup/confirmSetup`; `auto_drive` gains an injectable `apply` seam.
- **P2 — Close the loop:** constrain `suggest_next_setup` to schema ranges + DoE seeding; loop driver
  propose→apply→drive N→archive→`compare_setups` (Welch A/B within one condition_bucket)→next;
  `experiments` lake fact.
- **P3 — Attribution + coaching:** condition-bucketed setup-effect (aero-vs-mechanical speed binning via
  `setup_knowledge`); coach cites measured corpus + bundled reference lap; findings → Tier-2 → Tier-3.
- **P4 — Scale-out (DEFER):** Parquet-on-object-store / Tier-3 sync; optional GP surrogate. Only when
  single-host volume is a real constraint.

**Positioning:** reuse/extend — almost nothing superseded. `coaching_lake` (core), `setup_model`
(fix `from_spinners`), `setup_knowledge` (the attribution brain, as-is), `setup_optimizer` (constrain +
DoE), `setup_catalog` (the identity bridge), `auto_drive` (add apply seam).

## Open decisions (operator)

1. **Storage ambition / "and beyond":** stay single-host embedded DuckDB now vs. build a cloud/fleet
   tier. **Recommendation: defer** — the lake isn't the bottleneck; empty `setup_params` is.
2. **First move:** start P0+P0b (the schema + capture unlock) vs. bank the strategy only. P0b is
   rig-gated, so it needs work driven on the actual rig.
3. Surrogate fidelity (stdlib RBF now vs GP later); schema-capture cadence; DoE lap budget.

## Provenance

Multi-agent investigation (real PocketTechnician/SetupExchange source on disk; Trophi.ai / Track Titan /
Garage61 / VRS / iRacing-ibt / ACC-JSON / Bayesian-opt literature) → architect synthesis. Caveat: the
adversarial-critic pass degenerated (placeholder output) and the PT structured-output agent failed after
reading the source; the design's own risks/open-decisions + operator judgment substitute for the missing
critique. Workflow `wf_a924cbdd`.
