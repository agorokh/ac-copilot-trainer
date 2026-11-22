---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-19
updated: 2026-06-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/244
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/racing-driver-and-controller-2026-06-17.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/csp-custom-ai-mmap-interface-2026-06-16.md
---

# Stanley steering from human profile — LIVE-VERIFIED on the rig (EPIC #154 Part G, #244)

**The steering wall is broken.** PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248)
(merged `88249bf`) Stanley controller, driven from the committed human profile
(`tests/fixtures/racing_human_profile_magione.csv`), drove car 0 around Magione via the carcsw
Custom-AI mmap with **no human**, and AC scored the laps **VALID** with full `lap`/`delta` coaching
telemetry flowing — the exact signal that was missing while PurePursuit understeered into INVALID
laps. Run on `AG_PC` (this session ran *on the rig*, so the cross-session "Mac can't reach the rig"
blocker was moot).

## What was observed (operator-grade)

- **Launch:** harness daemon `--launch-mode cm` + `autodrive_magione.cmpreset` → `POST /session/start`
  → `outcome=driving` first try (non-elevated CM-IPC; my shell was non-elevated). AC on track,
  trainer auto-loaded (coaching widget + track map + overlay all live).
- **Hijack:** `read_car_data()` non-None → CSP accepted Custom-AI manipulation. Confirms the
  `surfaces.ini` edit (below).
- **Baseline drive (merged defaults, `pace=1.0 brake_g=1.4`):** **3 valid laps**, AC
  `completedLaps` 0→3; best flying lap **iLast=106813 ms (1:46.8)**; max **207.6 km/h**; gears 1–6;
  peak brake 1.00; 25 brake events; **0 stuck/teleport**. Steering never saturated on the line
  (peak ~0.16 in corners) — no understeer wall.
- **Telemetry (sidecar WS tap):** over the run — `coaching.snapshot=3797`, **`delta=2935`** (live
  delta-to-reference, e.g. `delta_s=-0.012/-0.017/-0.028`), `tire_temps=1899`, `connection=379`,
  `session=3`, **`lap`** frames all `"valid": true`.
- **Reference capture:** the trainer wrote a schema-v1 lap archive per lap
  (`journal/laps/lap_*_2_106813_*.json`) and persisted `ks_porsche_911_gt3_r_2016__magione.json` —
  i.e. **an agent-driven Stanley lap became the trainer's coaching reference and later laps were
  coached against it.** This is the EPIC #154 L2/L3 throughline end-to-end.
- Screenshots inspected (`.scratch/part-g/stanley_*.png`): in-cockpit, 6th gear on the straight,
  car on the racing surface, coaching widget active.

## The residual: pace (honest)

Human reference laps (`.scratch/part-g/human_laps.csv`) were **~90.7 s / avg ~98.7 km/h** (relaxed
data-collection laps, max 228 km/h). The Stanley best clean lap is **106.8 s / avg ~83.5 km/h ≈ 85%
of human**. The issue's literal `avg ≳100 km/h` sub-bar is **not** met. A tuning pass (more
aggressive corner-exit throttle `throttle_scale=3.5 base_gas=0.10 traction_lift=0.45`, later braking
`brake_g=1.55`) **regressed** to 124.6 s — TC-off wheelspin/overshoot costs more than it gains, so
**the merged defaults are near the controller's stable optimum** for this car/track. Closing the
final ~15% is separable controller-sophistication work (use the human gas/brake trace directly, or
MPC), **not** a wall — and it touches `racing_driver.py` (the #244 file group), so it stays as
remaining Part-G scope on #244 rather than a new overlapping issue.

## Rig recipe used (reusable)

- `extension/config/new_behaviour.ini` → `[CUSTOM_AI] ENABLED=1` (already set).
- Track `content/tracks/magione/data/surfaces.ini`: `[SURFACE_0] WAV_PITCH=extended-0` (extended-
  physics trigger) + `[_EXTRA_PERMISSIONS]` `ALLOW_CUSTOM_AI_MANIPULATION=1`. Offline-hash only;
  restore from `surfaces.ini.bak-precustomai` when done. Confirmed authoritative vs the CSP doc
  `cup.acstuff.club/docs/csp/other-things/custom-ai`.
- Live driver: `.scratch/part-g/race_drive_stanley.py` (uses `RacingDriver.from_human_profile`);
  validity oracle = AC `completedLaps@132` + trainer `lap.valid`; tap = `.scratch/part-g/tap_logger.py`.
