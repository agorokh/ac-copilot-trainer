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
- `journal/driver/profile.json`: compacted driver profile roll-up built by
  `python -m tools.ai_sidecar.driver_profile`.
- `journal/tt/index.json` and `journal/tt/sessions_index.json`: derived Track Titan
  indexes rebuilt by the ingest tooling.

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
