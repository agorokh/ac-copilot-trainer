# Telemetry Data Platform

Issue #402 adds the first longitudinal data layer on top of the immutable lap
archive corpus.

## Source And Derived Stores

Raw evidence remains the schema-v1 lap archive JSON under `journal/laps/lap_*.json`.
The Track Titan lake under `journal/tt/**` is also raw personal evidence. Analysis
code reads those files and does not edit them in place.

Derived stores:

- `journal/analytics.duckdb` or `journal/lake.duckdb`: disposable DuckDB lake built
  by `python -m tools.coaching_lake.build_analytics`.
- `journal/parquet/**`: optional columnar ML surface (Parquet) emitted from the lake
  with `--parquet`; partitioned `samples/`, single-file grains, and a `_schema.json`
  SchemaVer sidecar. Derived + disposable — rebuilt from the JSON corpus like the DuckDB
  file, never edited in place.
- `journal/driver/profile.json`: compacted driver profile roll-up built by
  `python -m tools.ai_sidecar.driver_profile`.
- `journal/tt/index.json` and `journal/tt/sessions_index.json`: derived Track Titan
  indexes rebuilt by the ingest tooling.
- `journal/tt/**/curriculum_lapN.json`: optional derived Track Titan harness
  curriculum built from retained `coaching_lapN.json` advice. Curriculum files are
  not raw TT evidence and are not included in the raw TT content index. Retention
  dry-runs show derived curricula as cascade deletes when their paired
  `coaching_lapN.json` source is pruned; pin/keep markers are honored.

## Track Titan Derived Artifacts

Build an M0 reference archive from retained full-lap TT reference windows:

```bash
python -m tools.tt_ingest reference --discover-lake --session-key <session> --lap <n> --output journal/tt_ref.json
```

Build an M-TT3 harness curriculum from retained per-corner advice:

```bash
python -m tools.tt_ingest curriculum --discover-lake --session-key <session> --lap <n> --output journal/tt/<game>/<car>/<track>/<session>/curriculum_lap<n>.json
```

The curriculum artifact preserves TT diagnosis keys, time loss, phase/highlight
spans, and segment timing as objective rows. It is derived from the write-once
services evidence; keep the raw `last_session_lapN.json` and `coaching_lapN.json`
files as the indexed source of truth.
Scratch/debug copies may be written under `.scratch/`; they are outside the TT
lake lifecycle and should be regenerated after source pruning.

## Sessions And Stints

Build the lake:

```bash
python -m tools.coaching_lake.build_analytics --lap-dir journal/laps --db journal/analytics.duckdb
```

The lake now includes:

- `sessions`: one row per `session_uuid`, with lap counts, valid lap counts, best
  lap, median lap, consistency, and the PB lap UUID.
- `stints`: contiguous blocks inside a session. The current offline archive does
  not carry a first-class tyre-set id, so `setup_hash` is the deterministic tyre-set
  proxy until capture grows a real tyre-set field.

Reports:

```bash
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report sessions
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report stints
```

## ML Grain — Per-Lap Features + Stint Degradation (issue #488 Part C)

Intra-lap traces cannot express degradation — a slow, per-stint process. The build adds two
ML-shaped grains on top of the star schema so `compound × laps_on_set` becomes the primary
segmentation key.

- **`lap_features`** — one row per lap. Curated scalar reductions of the dynamic channels:
  per-wheel tyre core temp (avg/max/end), inner−outer tread gradient, hot pressure (avg + in-lap
  rise), tyre wear (end + Δ), brake-temp peak, wheel load, running camber, and a frictional-energy
  proxy `Σ|slipRatio|·load·dt`; plus car-level g-g envelope, slip exposure, thermal-window
  residence, and the time-grid (`sample_dt_ms_median`, `trace_hz` — derived from the retained
  `eMs` channel). It also carries the **confound metadata** every ML segmentation needs:
  `compound`, `tyre_set_key`, `laps_on_set`, `is_new_set`, `out_lap`, `in_lap`, `is_dirty`,
  `cold_pressure_*` (from the setup snapshot), `ambient_temp_c`, `track_temp_c`, `grip_level`, and
  `fuel_corrected_lap_ms`.
- **`stint_deg`** — one row per stint. `deg_slope_ms_per_lap` = the OLS slope (DuckDB `regr_slope`)
  of **fuel-corrected** laptime vs `laps_on_set` over valid, non-out/in laps, with `deg_r2` and
  `n_laps_in_fit`; plus `deg_slope_raw_ms_per_lap` (uncorrected), `wear_rate_pct_per_lap`, and
  `thermal_window_residence_pct`. A fit over fewer than two representative laps is **NULL**
  (undefined), never NaN.

**Tyre-set age** is derived, not read — AC exposes no per-physical-set serial to Lua, so
`laps_on_set` counts laps since the last stint boundary (a tyre-set **or** setup change), `out_lap`
is the first lap on a set, and `in_lap` is the last lap of a stint that is followed by another
stint in the session (the deterministic pit-in proxy).

**Fuel correction** subtracts a documented, configurable prior — `fuel_corrected_lap_ms =
lap_ms − fuel_effect_s_per_kg × 1000 × fuel_mass_start` (default `0.03` s/kg, override with
`--fuel-effect`). It is a transparent modelled penalty, not a within-stint regression (fuel and
age are collinear within a no-refuel stint); degradation is the residual slope after removing it.

```bash
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report degradation
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report lap-features
```

## Setup ⟷ Outcome Linkage (issue #488 Part D)

Join **static setup** ⟷ **dynamic response** ⟷ **outcome** so ML (and the operator) can attribute a
setup knob to the car's behaviour and the laptime:

- `setup-vs-dynamic` — for each captured setup param value, the average dynamic response
  (`core_temp`, `tyre_energy`, thermal residence) and the average laptime.
- `dynamic-static-delta` — the gap between what you dialled in and what the car did: running camber
  vs set `CAMBER_*`, and hot running pressure vs the cold set `PRESSURE_*`.
- `setup-coverage` — the setup-snapshot **reliability** check: the fraction of laps that actually
  captured setup params (the historical `setup_params = 0` data-quality point). Also surfaced as
  `setup_coverage_pct` in the `summary` report.

```bash
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report setup-vs-dynamic
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report dynamic-static-delta
python -m tools.coaching_lake.build_analytics --db journal/analytics.duckdb --report setup-coverage
```

## Parquet ML Surface + SchemaVer

Keep the immutable per-lap JSON as the raw landing and DuckDB as the interactive engine, but emit an
additive, columnar **Parquet** surface for training/query:

```bash
python -m tools.coaching_lake.build_analytics --lap-dir journal/laps --db journal/analytics.duckdb --parquet
# or a custom dir: --parquet journal/parquet
```

Every grain is written under `journal/parquet/` — the big `samples` grain hive-partitioned by
`track_id`/`car_id`, the small grains as single files — plus a `_schema.json` sidecar recording the
**SchemaVer** (`MODEL.REVISION.ADDITION`, currently `1.1.0`) and grain row counts. `lake_meta` in the
DuckDB file carries the same version. Read the surface back with
`tools.coaching_lake.read_parquet_surface(out_dir, grain)`, which uses DuckDB `union_by_name` so an
older Parquet generation (fewer columns) still loads after the schema grows additively.

## Driver Profile

Update the local profile:

```bash
python -m tools.ai_sidecar.driver_profile --lap-dir journal/laps --driver-id local-driver
```

The profile preserves:

- `preferences`: operator/runtime preferences for future driver-model work.
- `focus_corners`: remembered track/corner focus lists.
- `session_rollups`: compacted per-session summaries.
- `personal_bests`: PB ledger by car/track/layout.
- `consistency`: cross-session consistency roll-ups by car/track/layout.

Because retention can remove old raw laps, `profile.json` is a compacted roll-up,
not a purely disposable view. Re-running the builder merges current archive roll-ups
with existing historical session roll-ups.

## Retention

Plan retention first:

```bash
python -m tools.coaching_lake.retention \
  --lap-dir journal/laps \
  --tt-dir journal/tt \
  --profile journal/driver/profile.json \
  --max-lap-files 1000 \
  --max-tt-files 5000
```

The CLI is dry-run by default. Add `--apply` only after inspecting the plan.

Protected files are never selected for deletion:

- lap archives whose `lap.is_pb` is true
- imported/generated reference archives
- lap UUIDs present in the profile PB ledger
- files with adjacent `.pin` or `.keep` sidecar markers
- unreadable lap archives
- Track Titan derived index files

Retention deletes whole files only; it never rewrites raw JSON in place.

## Streamed CSV Bridge

External tools can consume stable analysis CSV from stdout:

```bash
python -m tools.lap_archive_export --output - journal/laps > exports/laps.csv
```

When `--output -` is used, CSV rows go to stdout and the summary line goes to stderr
so downstream tools receive a clean stream. MoTeC-shaped CSV still writes to a file
because it performs a bounded pre-scan for header statistics.
