---
type: handoff
status: active
created: 2026-10-25
updated: 2026-10-25
issue: https://github.com/agorokh/ac-copilot-trainer/issues/938
pr: https://github.com/agorokh/ac-copilot-trainer/pull/940
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-25-045500Z-issue401-roadmap-reconcile-469e2b5.md
---

# #938 post-merge: condition-indexed capability envelope and thermal grip gate for CoachRuntime

[PR #940](https://github.com/agorokh/ac-copilot-trainer/pull/940) merged into `main` as `274e004` from vetted head `431e463` (author vendor `google`). Issue [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938) (`REX-20261024-02`) is closed.

## Delivered

- **Condition-indexed capability interval & evidence-quality gate (`tools/ai_sidecar/coaching_runtime.py`)**:
  - Replaced the flat `_GRIP_CEILING_G = 1.55` assumption with a three-mode capability gate (`condition_indexed`, `ggv_denominator_only`, `baseline`) backed by the combo's `GGVModel` (`tools/ai_sidecar/ggv_fit.py`).
  - `_derive_combo_ggv` fits `ggv_from_telemetry` from measured accelerometer channels (`ref_lap.accg_lat` / `ref_lap.accg_long` persisted in `accG_lat` / `accG_long` trace columns) rather than kinematic path-curvature `lat_g`, falling back to `_default_ggv_model()` (`1.55 g` lateral / `1.60 g` brake) when measured accelerometer channels are absent or unread.
  - Separated corner-entry combined braking + turn-in utilization (`max_entry_grip_used`, accumulated only across `spline <= r.apex_spline` against `(ay / ay_max(v))^n + (ax_brake / ax_brake_max(v))^n`) for `EARLY_BRAKE` from speed-indexed lateral utilization (`max_lat_grip_used` against `ay_max(v)`) for `SLOW_APEX`.
  - Wired `analyze_tyres` (`tyre_model.py`), `analyze_conditions` (`conditions_model.py`), and brake thermal thresholds (`race_management.py`) strictly as eligibility/abstention gates (never uncalibrated numerical friction multipliers) for both pass-exit diagnosis and `PRIME` anchor crossings (`tyre_temp_cold`, `tyre_temp_overheat`, `tyre_temp_critical`, `brake_temp_overheat`, `brake_temp_critical`, `wet_regime`, `grip_envelope_saturated`).
  - `PRIME` anchor crossings inspect both current-frame utilization and `last_pass_capability` so an already-armed corner abstains on saturated laps without spending lap speech budget; gated passes pass `valid=False` to `CoachingLedger.record_pass` so existing ledger state is held without emitting false `"Good."` confirm cues.
  - Per-pass capability diagnostics (`evidence_quality` in `{"full", "kinematic_only", "thermal_only", "missing"}`, `max_grip_used`, `max_lat_grip_used`, `max_entry_grip_used`, `ineligible_reason`) are recorded in `CoachRuntime.last_pass_capability`, and `cue_suppress_reason` is sanitized to `[a-z0-9_]+` for `/health`.
- **Telemetry & archive producer parity (`tools/ai_sidecar/telemetry_source.py`)**:
  - `ticks_from_archive` propagates per-wheel `tyre_temps_c` and `brake_temps_c`, measured `accG_lat` / `accG_long` (skipping all-zero unread SHM sentinel columns), and `conditions` metadata (`trackGripLevel`, `trackTempC`, `ambientTempC`, `weatherType`, `tyreCompound`, `optimalTempC`).
  - `stream_live` maps and reads `PHYSICS_MAP_BYTES` (`512` bytes) from `acpmf_physics` to unpack `tyreCoreTemperature[4]` (`@152`), `airTemp`/`roadTemp` (`@288`/`@292`), and `brakeTemp[4]` (`@348`), plus `tyreCompound` from `acpmf_graphics` (`GFX_BYTES = 256`), while rejecting `bool`, `NaN`, and `±inf` across all scalar and per-wheel channels.
- **Bounded 8-lap discriminating replay experiment (`tests/test_coaching_runtime.py`, `tests/test_telemetry_source.py`)**:
  - Replayed 8 recorded laps across 2 sessions (`bmw_e30` street `~1.05 g` + `mclaren_mp412c_gt3` slick `~1.50 g`, covering cold out-laps, warmed flying laps, overheat/wet conditions, and combined-entry saturation) through `(a)` baseline `1.55 g`, `(b)` denominator-only `GGVModel.ay_max(v)`, and `(c)` `condition_indexed`, achieving `>= 80%` unsupported-cue suppression (`100%` out-of-window `PRIME` suppression) and `>= 70%` valid in-window cue retention.

## Post-merge classification & verification

- `scripts/post_merge_classify.py`: `No post-merge classification flags for these paths.`
- Verified on merged `main` (`274e004`): `make ci-fast` passed (`5299 passed`, `87.62%` total coverage) and 46 targeted `test_coaching_runtime.py` + `test_telemetry_source.py` tests passed.

## Remaining / Follow-ups

- None for #938. Lua producer (`src/ac_copilot_trainer/`) and SimHub profiles were intentionally untouched per scope boundary.
