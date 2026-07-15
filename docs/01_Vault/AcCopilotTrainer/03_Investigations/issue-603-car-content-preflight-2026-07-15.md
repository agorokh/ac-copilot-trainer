---
type: investigation
status: complete
memory_tier: canonical
created: 2026-07-15
updated: 2026-07-15
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/tier3-consumer-repoint-drift-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/csp-telemetry-and-acd-grounding-2026-07-04.md
---

# Issue #603 — damaged AC car content preflight

## Delivered

PR [#607](https://github.com/agorokh/ac-copilot-trainer/pull/607) merged as
[`123a577`](https://github.com/agorokh/ac-copilot-trainer/commit/123a5774f1657ab5426ae4f90f759e844c7af800)
and closed issue #603. Before any Content Manager/AC launch, `auto_drive` resolves the selected car
from `--car` or a preset and validates the source AC will use:

1. packed `data.acd` when present, otherwise unpacked `data/`;
2. readable root `lods.ini` with at least one `[LOD_n]` section;
3. safe `.kn5` references whose files exist and are non-empty.

A fatal row writes the normal evidence bundle with `stage=preflight`, `launched=false`,
`drive=null`, `attempts=[]`, classification `non_drive_preflight_failure`, and both
`counts_as_drive_run=false` and `counts_as_sim_death=false`. Preset-only runs retain the effective
car ID in the report and safe default evidence-directory tag.

## Review hardening

- Generic ACD keying/unpacking moved out of tyre code into `tools.ac_content`.
- `CarDataSource` gives packed content launch precedence, exposes the same flat case-insensitive
  member contract for packed/unpacked forms, caches one packed decode, and reads only requested
  unpacked files.
- Malformed UTF-8/BOM presets become actionable preflight evidence instead of crashing early.
- Nested packed members cannot alias root names; inline `;`/`#` comments on LOD `FILE=` values are
  accepted.
- Tyre specs consume the same source resolver and load only `tyres.ini` plus explicitly referenced
  LUTs.

The final local parity run passed **2,980 tests, 113 skipped, 87.60% coverage**. Required Actions
checks and the machine resolve-gate were green; all paginated GraphQL threads were resolved. After
the final ten-minute cooldown, the self-hosted reviewer had no current-SHA review; per the canonical
anti-hang rule, successfully resolved head + completed cooldown makes absence non-blocking.

## Observed merged-main evidence

- `python -m pytest tests/test_ac_content.py tests/test_tyre_specs.py
  tests/test_ac_harness_auto_drive.py -q` → **222 passed**.
- Real `bmw_m3_gt2` packed archive at Magione → `preflight ok`, exit 0.
- Real damaged `ks_porsche_911_gt3_r_2016` → `[car_data]`, exit 2 before launch; report carries the
  explicit non-drive classification and both denominator exclusions.
- A real dual-source Cayman had different packed/unpacked payloads; the accessor selected packed
  content and did not mask its unreadable renamed-tune payload with the inactive unpacked folder.

The Porsche files remain damaged on disk. That is now an actionable rig-maintenance condition, not
a harness timeout: verify stock files in Steam or reinstall the mod in Content Manager, then rerun
`--preflight-only` before any drive. Post-merge classification reported no code migration, new
environment variable, dependency, or workflow action.

## Memory state

The Tier-3 tool was not exposed in this Codex session and the canonical manual prefetch still maps
to the retired AG_PC consumer endpoint. Work proceeded from the Tier-2 vault subgraph without a
gate bypass. Workstation-ops #1551 remains the owner of the consumer repoint; see
[[tier3-consumer-repoint-drift-2026-07-15]].
