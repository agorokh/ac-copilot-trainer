---
type: decision
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/03_Investigations/curated-setup-hash-bridge-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/porsche-911-gt3r-magione-balanced-setup-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
---

# Decision: curated car setups are first-class data-platform entities

## Context

Car setups will be a **VERY important part of coaching** (operator directive, 2026-06-28). Until
now a setup only entered the data platform once it was *driven* (lakehouse `setup_params` is empty —
`setup_params=0` — until the #345 capture lands), and authored setups lived only as transient files
in the user's AC folder: not version-controlled, not reviewable, not queryable.

## Decision

Make a curated setup a first-class entity with three parts:

1. **Asset library** — version-controlled curated INIs at
   `assets/setups/<carID>/<track>/<name>.ini`. Reviewable, diffable, deployable; the source of truth
   distinct from the user's transient AC folder. (Not under data-immutability, which guards
   `journal/` raw paths.)
2. **`tools/setup_catalog` registrar** — parses the INI via `setup_model`, computes the **rig-faithful
   djb2 `canonical_hash`** (the same key driven laps carry — see
   [[curated-setup-hash-bridge-2026-06-28]]), plus a meta-independent `tunable_hash` and the semantic
   `by_category` projection, and **upserts** a JSONL catalog at `assets/setups/_catalog/registry.jsonl`.
3. **Catalog ↔ lake join** — `catalog_join_sql` LEFT-JOINs the catalog onto `laps` on
   `canonical_hash` OR setup-name-in-`setup_path`. DuckDB reads the JSONL natively, so **no lakehouse
   schema change** is required; every curated setup gets driven-lap count + best time, NULL until driven.

## Why this shape

- One **content identity** (the djb2) bridges both the lake and the experiments store without a new
  column; the name/path fallback makes the join robust to AC re-materializing `setup.ini`.
- Deploy to `%AC_USERDATA%/setups/...` is a **separate, opt-in** action (`--deploy`), never implicit
  on registration, and refuses non-rig hosts — so registration is safe on any machine.
- Reuses `setup_model` / `setup_knowledge` (the verified GT3 brain), so coaching can cite *why* a
  curated value is what it is, not just *that* it differs.

## Consequences / follow-ups

- First entity registered: the Magione 911 GT3 R balanced fast-race setup
  ([[porsche-911-gt3r-magione-balanced-setup-2026-06-28]]).
- **Future hardening** (review rec): centralize the projection as `setup_model.canonical_hash` and
  recompute it on the lake side into a column, so optimizer/lake/registrar share one function.
- Naming reconciled: `setup_catalog` (content identity) coexists with `setup_library.lua`
  (BEST-by-name matcher) — they key on different things by design.
