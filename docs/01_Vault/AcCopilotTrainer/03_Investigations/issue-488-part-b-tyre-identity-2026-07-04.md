---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-04
updated: 2026-07-04
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-488-part-a-tier2-csp-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/telemetry-capture-surface-for-ml-2026-07-03.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/488
---

# #488 Part B — Tyre identity & specs (PR #500, rig-verified)

PR [#500](https://github.com/agorokh/ac-copilot-trainer/pull/500) **MERGED** (squash
[`dd463fc`](https://github.com/agorokh/ac-copilot-trainer/commit/dd463fc)) — `/autonomous-deliver 488`.
Advances EPIC **#488 Part B**. Epic stays OPEN (Parts C, D remain).

## Delivered

Resolve the tyre **compound identity** + the **CAR-true optimal-temp window** instead of `tyre_model`'s
hard-coded generic per-compound bucket.

- **Live capture** (`lap_archive.lua` `tyres` header — header-only, byte-identical trace untouched):
  `longName` via `ac.getTyresLongName` ("Slick Medium (M)") + `optimalTempC` via
  `wheel.tyreOptimumTemperature` (the PERFORMANCE_CURVE peak the game itself uses). **No ACD needed** —
  a grounded improvement over the issue's ACD-centric framing.
- **`tools/ai_sidecar/tyre_specs.py`** — pure-stdlib `data.acd` reader. **Grounded correction: the ACD
  cipher is SUBTRACTION, not XOR** (aluigi/ZenHAX + `bovis/acd_extractor`); key = decimal-string of 8
  folder-name sub-algorithms indexed `% len(key)`; `-1111`/version container handling; Kunos bare
  `[FRONT]` == compound 0. `TyreSpec` (name, size, PRESSURE_STATIC/IDEAL, DX/DY_REF μ, curve-peak
  `optimal_temp_c`, VERSION), keyed `(car_dir, compound_index)`, bounded cache. Hermetic tests.
- **Feeds:** `tyre_model.analyze_tyres(optimal_temp_c=)` re-centers the window (asymmetric roll-off);
  `tyres_from_lap_archive` reads the live optimum + name, offline `car_data_dir` ACD fallback for
  pre-#488 archives; `setup_model.resolve_tyre_spec(setup, car_dir)`.

## Rig verification (911 GT3 R, Magione, `auto_drive --driver ggv`, 4 laps)

Fresh archive `9bf00c14_3` (valid): `tyres = {longName:"Slick Medium (M)", optimalTempC:95, name:"M",
compoundIndex:1}`. `tyre_model` on the real archive → compound label `"slick medium (m)"`, window
`(75,105)` = `_window_from_optimal(95)`; generic path only knows `"slick"` — Part B gives the real
identity. ACD verified against the real `data.acd`: compound 0 "Slick Soft" `optimal_temp_c` 70,
`PRESSURE_IDEAL` 26, `DX/DY_REF` 1.58, version 10.

## Grounded findings / caveats

- **Live vs ACD optimum diverge on a plateau curve**: live `tyreOptimumTemperature`=95 (Medium) vs the
  ACD first-peak heuristic=80. The `PERFORMANCE_CURVE` plateaus at peak grip; AC's live value is
  authoritative and the code **prefers it**. The ACD `optimal_temp_c` is a fallback approximation for
  pre-#488 archives — a possible refinement is plateau-center instead of first-peak (unverified; deferred).
- For the Medium compound the car-true window `(75,105)` coincidentally equals the generic slick bucket;
  the **identity** still differs, and the window moves for other optima (unit-tested).

## Review (6 hardening cycles — gemini, all legitimate for an untrusted-file parser)

case-insensitive `data/`+member lookup (HIGH); bounded `_ARCHIVE_CACHE` (Qodo); commented section
headers; non-finite INI guard (protects `_size_label`/`_parse_lut_pairs`); basename `.lut` resolution.
`make ci-fast` OK. Self-hosted daemon does not review this repo (gate vacuous).

## Remaining on EPIC #488

Part C (grain + serialization — `build_analytics.py` per-lap scalar + per-stint deg-slope, Parquet +
SchemaVer, docs), Part D (setup⟷outcome linkage + dynamic-vs-static deltas + setup-snap reliability).
