---
type: investigation
status: active
created: 2026-06-16
updated: 2026-06-16
relates_to:
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# PR #207 — MoTeC CSV imported reference laps

Closed [#79](https://github.com/agorokh/ac-copilot-trainer/issues/79) on 2026-06-16 as squash [`0c637e3`](https://github.com/agorokh/ac-copilot-trainer/commit/0c637e3bf3f648e75b40e6b760ceff097ac9a241).

## What landed

`tools/import_motec/` is a stdlib-only CLI:

```bash
python -m tools.import_motec <input.csv> --car <car_id> --track <track_id> [--layout <layout>]
```

It scans MoTeC-style CSV headers for distance/spline, speed, throttle, brake, steering, gear, lap, and optional position/time channels. It normalizes speed/pedal/steering units, splits multi-lap CSVs by lap column, computes elapsed milliseconds from a time channel or by distance/speed integration, resamples to 2000 schema-v1 trace rows, and writes compact lap archive JSON under `journal/laps/`.

Imported records use:

- `schema_version = 1`
- `source = "imported"`
- `import_format = "motec_csv"`
- `lap.is_pb = false`
- `lap.is_valid = true`
- trace fields `["spline","speed","eMs","throttle","brake","steer","gear","px","py","pz"]`

## Runtime activation

The trainer setting `useImportedReference` defaults OFF and is stored in per-key `ac.storage`. The Settings UI exposes **Prefer imported reference over local PB**, a status line, and an **Open reference laps folder** button.

When enabled, `persistence.bestImportedReference(car, sim)` scans `journal/laps/lap_*.json` for matching imported MoTeC laps and picks the fastest valid car/track match. `persistence.chooseImportedReference(localBestMs, importedRef, enabled)` only activates it when there is no local PB or the imported lap is faster. Activation sets the realtime `state.bestLapTrace` / `bestSortedTrace` path, re-derives braking points, track segments, and corner features, and marks `activeReferenceSource="imported"`.

Persistence keeps the local in-game PB snapshot separate (`localBestLapTrace`, local brake points, local segments, local corner features). If an imported reference is active, `persistPayload()` writes the local snapshot, not the imported trace. A new local PB restores the local snapshot before mutation, then refreshes imported-reference selection so a faster local PB wins and a still-faster import remains active.

## Verification

- Local `make ci-fast PYTHON=.venv/bin/python` passed: `890 passed, 74 skipped`, coverage 80.58%, bandit/policy/CSP checks green.
- GitHub checks on PR #207 were green: `build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot. Sourcery was rate-limited/skipped.
- GraphQL `reviewThreads` returned no unresolved threads after the cooldown.
- Artifact CLI smoke wrote a 2000-sample imported schema-v1 lap JSON from a sample CSV.

## Gotchas

- CSP/Lua host callables can appear as userdata/cdata. JSON helper guards now use nil checks plus `pcall` instead of `type(JSON.parse) == "function"` so the same path works under CSP and `lupa` tests.
- Imported laps are reference candidates, not PB records. Do not persist them as local `bestLapTrace` or update `bestLapMs` from import data.
- `io.scanDir` scanning is scoped to `journal/laps/lap_*.json`; non-MoTeC/imported or mismatched car/track records are ignored.
