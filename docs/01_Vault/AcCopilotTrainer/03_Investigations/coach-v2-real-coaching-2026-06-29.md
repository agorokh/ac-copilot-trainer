---
type: investigation
status: active
created: 2026-06-29
updated: 2026-06-29
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/coach-cue-track-misalignment-2026-06-29.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Coach v2 — from telemetry-transcriber to real coaching (2026-06-29)

## Why
Operator (experienced driver) judged the coach "completely useless": it was a POST-HOC delta
REPORTER — "T1: carried 22 km/h under the best lap" spoken AFTER the corner, a number you can't act
on. Real coaching diagnoses your *one* mistake and tells you what to DO, *before* the action point,
paced like a race engineer. A council deliberation (gemini/perplexity, mistral timed out) produced
the hardening plan. Branch `feat/coach-v2-real-coaching`.

## What shipped (all tested + committed)
- **Diagnosis** `coaching_diagnosis.py`: `classify_root_error(cand, ref)` → ONE root, earliest in the
  causal chain (brake→trail→apex→throttle) so we coach the CAUSE not the symptom. `severity()` grades
  the margin → register (firm/critical) + intensity.
- **Ledger** `coaching_ledger.py`: pass-to-pass state machine — hysteresis (no speech on one noisy
  lap), lap budget (≤4, biggest losses), assess laps (watch first), acknowledge-once-then-silence,
  regression re-arm. Carries the magnitude register from the diagnosing pass to the next-lap PRIME.
- **Runtime** `coaching_runtime.py`: live engine — per-pass technique accumulation, diagnose on exit,
  fire **PRIME** at a pre-computed reference anchor (brake/turn-in/apex), live **SAVE** "Brake!",
  **CONFIRM** "Good." once on a fix. Reference signatures derived with the same accumulation as the
  live path so a driver ON the reference → NONE (no false coaching).
- **Audible** `voice/vocabulary.py` + re-baked Kokoro am_fenrir+radio bank (`coach-bank-kokoro-v2`,
  58 clips): verb-first imperatives + firm/critical tiers; v2 advisories resolve + speak.
- **Grip-gate (honest)**: suppress "carry more"/"brake later" at the lateral-grip ceiling, driven by
  the **`lat_g`** channel (REQUIRED by the telemetry_tick contract → LIVE-ACTIVE with the real
  producer). We did NOT fabricate grip from v²·κ — the Magione reference itself corners at 1.40–1.56 g
  (it is AT the limit), so such a gate could never fire honestly.
- **Server**: `AC_COPILOT_COACH_V2=1` wires the runtime as the cue producer in place of the legacy
  observer; thresholds env-tunable (`AC_COPILOT_COACH_ASSESS_LAPS/_HYSTERESIS/_LAP_BUDGET`).

## How it's proven (council DoD)
- **Deterministic E2E** `tests/test_coaching_e2e.py` (council P0 gate): a perturbation engine injects
  KNOWN errors at KNOWN corners over a multi-lap stint and asserts the right phrase at the right
  anchor with the right pacing/magnitude — 14 scenarios, <2.5 s, no clock/IO. **518 tests pass** across
  coaching+voice.
- **Live placement** (earlier real auto_drive laps): v2 cues fired correctly placed from real
  telemetry (SAVE at T3/T5; PRIMEs at T2/T4/T5 anchors); zero legacy-cue leakage.
- **LIVE AUDIBLE** (deterministic telemetry replay → running sidecar, `.scratch/replay_telemetry.py`):
  injected early-brake at T4 → diagnosed `early_brake`, graded **critical** (gross), fired @0.6108
  (exact brake anchor 0.610), and the voice coach **dispatched `early_brake.prepare.critical.generic`**
  to the rig headset. Full chain telemetry→diagnosis→grading→anchor→spoken, verified.

## Gotcha worth keeping
The autonomous auto_drive reliably completes only ~1 lap (spins/stalls at pace; barely moves at
cruise), so cross-lap PRIMEs can't be captured live by the car. Use the **telemetry-replay harness**
(`.scratch/replay_telemetry.py`) against a FRESH sidecar (stale runtime state suppresses cues) for a
deterministic live-audible proof.

## Next slice (council P5/P4/P6, not yet done)
- **P5** lead-time: split `_DEFAULT_LEAD_S` into prepare/act tiers + clamp a PRIME out of the prior
  corner's window.
- **P4** lock/wheelspin SAVE cues ("Easing!"/"Squeeze!") — now feasible since `lat_g`/slip channels
  exist in the contract.
- **P6** session arc: live "Focus T3" / "Again." escalation (the ledger's `refocus`/`focus_corner`
  hooks are built but unspoken).
