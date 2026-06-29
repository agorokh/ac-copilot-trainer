---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/01_Decisions/curated-setup-as-data-platform-entity-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Curated setup ↔ data-platform hash bridge (verified, as shipped)

How a **curated** setup (authored, version-controlled) joins to **driven** laps in the coaching
lake and the experiments store — the trap a naive bridge falls into, and how `tools/setup_catalog`
avoids it. Verified by an adversarial data-platform review + an end-to-end join test.

## The single join key is the Lua djb2 canonical hash

The driven-lap `setup.hash` is produced in `src/ac_copilot_trainer/modules/setup_reader.lua`:

1. `canonicalSetupString` — for every `{section,key,value}` harvested by `readIniSnapshot` (**raw
   string** values, **all** keys incl. `CAR.MODEL`, `__EXT_PATCH.VERSION`), build
   `"<SECTION>|<KEY>=<value>"`, **sort**, join with `";"`.
2. `digestSetup` — djb2 (`h=5381; h=(h*33+byte) mod 2^32`), formatted `%08x` → **8 lowercase hex**.

`lap_archive.lua` writes it as `setup.hash`; the lake copies it verbatim into `laps.setup_hash` /
`setup_params.setup_hash`; `setup_optimizer.record_from_lap_archive` adopts it as the experiment
key. One key bridges **both** stores.

## The trap (a naive registrar returns ZERO rows, silently)

Fingerprinting a curated setup with `setup_optimizer._stable_hash` **cannot** match the driven hash:

- **Algorithm/length:** `_stable_hash` is sha1/16-hex; the driven hash is djb2/8-hex. Can't collide.
- **Dead fallback:** `record_from_lap_archive` does `setup.get("hash") or _stable_hash(...)`. Real
  archives ALWAYS carry the Lua hash, so the sha1 branch is dead — the store key is always djb2.
- **Projection/value-type:** `digestSetup` hashes **all** keys as **raw strings** (`"66"`);
  `_numeric_params` keeps only finite floats (`66.0` → JSON `66.0`). `"66"` ≠ `66.0`; float
  formatting (`66` vs `66.0`, `27.5` vs `"27.5"`) compounds it.
- The lake's `setup_params.setup_hash` is the same djb2 string, so a sha1 joins neither store.

The failure is invisible — an empty join reads as "not driven yet", not "broken".

## How `tools/setup_catalog` resolves it (as shipped)

- `registrar.canonical_hash` **reimplements the Lua djb2 over the raw-string canonical form**,
  pinned by a known-answer test (`djb2_8hex("a") == "0002b606"`) + an independent re-impl
  cross-check, so the curated hash equals the driven hash for the same file bytes.
- **Robust join, not a hash bet:** `catalog_join_sql` matches on `canonical_hash` **OR** the setup
  *name* embedded in `laps.setup_path` (hash-independent, always present) — so an AC re-materialize
  byte-miss does not zero the join. `tests/...::test_catalog_joins_simulated_driven_lap` proves a
  lap with `setup.hash = canonical_hash(file)` returns the catalog row.
- Naming: deliberately `setup_catalog`, not `setup_library`, to avoid colliding with
  `setup_library.lua` (which matches by NAME/path by design). The catalog adds *content* identity.
- Deploy is **opt-in** (`--deploy`), refuses non-rig hosts and never clobbers operator files.
- `assets/setups/**` is fine under data-immutability (that invariant guards `journal/` raw paths).

## Honest caveat + future hardening

The driven hash is over the *live* `setup.ini` AC re-materializes; if AC normalizes/adds sections it
may not byte-match (hence the name/path fallback). The robust long-term fix (review recommendation):
centralize the projection in `setup_model.canonical_hash(snapshot)` and recompute it on the lake side
into its own column, so optimizer/lake/registrar share one function — eliminating Lua↔Python drift.
