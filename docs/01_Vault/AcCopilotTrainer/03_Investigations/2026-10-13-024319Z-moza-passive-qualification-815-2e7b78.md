---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-022537Z-backlog-applied-moza-815-ce1e22.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-015456Z-moza-backlog-research-9ed2f3.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# MOZA Part A: readable data, no qualified production source yet

GPT-6 Astra with Extra High effort ran the first passive qualification pass for #815.
This is a bounded negative finding; **Part A remains incomplete and Parts B-D have not started**.
All four artifacts permit passive inspection and the specified offline numeric comparison only.
Canonical import, live reference, human PB/progression, plant fitting and diagnostic-event use are false.
No simulator, hardware, voice, cloud account, opaque-resource decoder or production-source action occurred.

## Scope and repeatable evidence

The reader captured and hashed 193 real files: four selected view caches, four contextual JSON files,
and 185 direct children of the selected native journal. All were stable across rereads and end checks;
no native inventory change occurred. Parsing used those captured bytes. Four synthetic scratch cases
passed: stable input, changed bytes, changed bytes with restored mtime, and same-content replacement.
Windows path-stat/descriptor-fstat ctime differences initially caused a false refusal; the reader now
compares ctime within each API and common identity/size/mtime across APIs. The failed receipt is retained.
These are per-file stable captures, **not an atomic application snapshot**.

App context is installed Racing Lab 2.1.7 release; processed cache schema is tracecore.view.v1.
Installed version and current resource catalog do not establish the producer version/origin of older files.
No raw telemetry arrays, credentials or vendor model payloads were exported or committed.

## Candidate results

All 28 same-combo native candidates within +/-1000 ms were compared with identical freedoms.
Five even progress sections train diagnostic clock/steering fits; five odd sections supply comparisons.
No fitted spatial shift, spline shift or nonlinear time warp enters the trajectory score.

| MOZA view | Declared lap | Best held-out position / speed MAE | Result within tested candidates |
|---|---:|---|---|
| Spa/Huracan, 0ae7d595 | 161.793 s | 1.657 m / 11.385 km/h | No adequate match under frozen absolute bounds |
| Spa/Huracan, 46c09455 | 191.116 s | 0.157 m / 0.043 km/h | Exact-duration candidate ranks first; close alternatives remain ambiguous |
| Magione/Porsche, 89c1661a | 82.250 s | 1.608 m / 8.206 km/h | No adequate match under frozen absolute bounds |
| Magione/Porsche, d8fb59c3 | 101.956 s | 0.118 m / 0.030 km/h | Exact-duration candidate ranks first; close alternatives remain ambiguous |

For the slower views, runner-up/best ratios are 1.0614 and 1.0266 against a frozen exploratory 1.5
cutoff. This is an uncalibrated heuristic that excludes duration and clock from ranking. It neither
proves nor disproves shared recording identity. Odd sections also rank/select candidates, so are not
an untouched confirmatory test; processed/interpolated points may be correlated. This narrows the
previous preliminary same-lap inference: strong trajectory similarity is not cross-system provenance.

## Clock, steering and missing meaning

The exact-duration Spa candidate fits native-minus-MOZA time offset -7.422361 s with 3.151 ms
held-out MAE; affine slope 1.000003408 offers no material improvement. Unequal retained stationary
start windows (7.728 s MOZA versus 0.291 s native) support a different start-window hypothesis,
not an identified application cause. Native duration/coverage defects remain, with no repaired archive.
Magione fits +0.199503 s with 2.173 ms held-out MAE.

Signed MOZA-from-native steering slopes are 2.523235 Huracan and 1.251760 Porsche; left/right fits
differ and maximum held-out residuals exceed 14 MOZA units. Physical wheel/road-wheel/normalized
semantics, clipping and nonlinear behavior remain unsupported. No universal conversion is authorized.
Speed km/h, x-to-px/y-to-pz and pedal division by 100 have bounded empirical support for the close
trajectories. Neutral/reverse gears, transformation algorithm and raw sampling rate remain unknown.
MOZA and native track-length definitions differ; missing boundaries and repeated/backward distances stay visible.

All control authority is unknown. Native in_game and producer-valid flags do not establish human,
AI or shared control. Neither faster view is linked to an official AI reference. Actual content versions,
layout, assists, setup, weather, tyres and conditions remain unresolved. Cached driving events are
producer annotations; the evaluation snapshot has no completed summary. No reusable AI coaching logic,
Track Titan replacement, export API, voice-capability conclusion or redistribution permission follows.

## Artifacts and review

Local reproducible script and readable report: `.scratch/moza-qualification/passive/qualify.py` and
`report.md`; machine decisions: `qualification.json`; full method and caveats: `method.json` and
`method-interpretation.md`. `readset.json`, `native-inventory.json`, `comparison-metrics.json` and
`final-receipt.json` retain source/output hashes, candidate/exclusion records and verified unchanged
numeric scoring/use gates across the classification correction. Raw source data remains in place.

Independent Astra Extra High review is in `passive-review/review.md`. Its two interpretation fixes
were applied: distinguish inadequate fast candidates from ambiguous close candidates, and qualify
identity claims. No numeric scoring threshold was tuned after observing the results. This is an
independent evidence review, not product acceptance or a Council quorum. A fresh ac_copilot Tier-3
query succeeded and is retained in `passive/tier3-context.json`; no gate was bypassed.

Next evidence for Part A is trustworthy per-lap origin/controller/conditions and physical channel
semantics, or an explicitly recorded unqualified endpoint. Future integration must reuse merged #814's
measured reference/provenance, timing/coverage and canonical-corner gates. No live activation follows.
