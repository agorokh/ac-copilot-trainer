---
type: decision
status: draft
memory_tier: canonical
created: 2026-06-27
updated: 2026-06-27
relates_to:
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/pr-207-motec-reference-import.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
---

# Strategy: Track Titan as a swappable "coaching oracle" (proposal, 2026-06-27)

**Status: draft / proposal** (not yet built). Grounded in
[[track-titan-telemetry-extraction-feasibility-2026-06-27]] + Gemini council + web research.

## Decision (proposed)
Do **not** treat Track Titan (TT) as a runtime data source. Treat it as an **external oracle** behind a
small `CoachingOracle` adapter, with providers `OurCoach` (always-on), `TrackTitan` (screen|ws), and a
future `Garage61(api)`. The harness + rig screen consume the interface, never TT directly. Rationale: for
AC, TT supplies **no new raw signal** — only pro ghost lines + an AI opinion. So extract *opinion + lines*,
not data we already own, and never hard-couple to a closed, auto-updating app.

## Two cheap wins (do first)
1. **Pro ghost → reference.** Acquire a pro reference line (overlay capture or ghost-mapping), convert to a
   schema-v1 imported reference, let **#207's faster-than-PB gate** activate it. Never overwrites the real PB.
2. **TT as referee.** Diff TT's per-corner time-loss against our `corner_attribution` on the same lap; log
   divergences as autonomous-harness fixtures → an *external* ground truth for the false-green KPI.

## Then (gated)
- **ws:9121 — RESOLVED via live capture (2026-06-27, 11,091 frames):** the read-only tap works
  (`ws://localhost:9121/` + Origin, register `{"type":"overlay-initialisation"}`, MessagePack), but it carries
  **only live telemetry** (`overlay-data` + lap/session lifecycle). **TT's coaching/reference NEVER appears on
  the ws** — it is computed cloud-side and rendered in the overlay. So the ws tap gives **no new signal for AC**
  (we already read the same shared memory). **Conclusion flip: screen-capture/OCR of the overlay (or the cloud
  API) is the PRIMARY tap for the coaching — NOT the ws.** Tools: `.scratch/tt_ws_tap.ps1`,
  `.scratch/ac_drive*.py`. Full evidence: [[track-titan-telemetry-extraction-feasibility-2026-06-27]].
  Residual: confirm with a *valid* lap (magione + `RacingDriver.from_human_profile`).
- **Self-evolution:** wire TT corner verdicts into the harness reward (localize controller mutations to the
  offending corner) and into a **personalized human curriculum** (biggest recurring TT-flagged mistake →
  targeted on-rig drill). The human curriculum is the project's actual end goal.

## Coaching extractor — POC BUILT + VERIFIED (2026-06-27)
The `TrackTitan / overlay_screen_ocr` provider is real: `.scratch/ocr_extract_tt.ps1` captures the screen,
3x-upscales a crop of TT's overlay debrief widget, OCRs via **native `Windows.Media.Ocr`** (zero deps;
tesseract absent), and emits structured coaching JSON (`.scratch/tt_coaching.json`): `suggestion_state`,
`debrief_text`, `focus_areas`, `delta_gainloss_s` (3-decimal filter excludes tyre psi), `lap_times_s`,
`tyre_compound`. Verified on a live debrief frame — near-perfect: *"Post-lap debrief … Full throttle only
0% of lap — focus on earlier power application."* Insight: full-screen OCR garbles stylized text; an
**upscaled region crop** OCRs cleanly. **Productionize** as a calibrated Python module behind a
`CoachingOracle` interface (region config per overlay layout, contrast preprocessing, debrief→advisory
mapping) via `/orchestrate` (issue → PR).

## Guardrails
- **Never** copy/log/transmit the plaintext Cognito tokens in `config.json`; **never** automate the cloud
  API with the user's token (most ToS/CFAA-exposed). Personal, local use only; nothing redistributed
  (TT bans setup redistribution).
- Honesty invariant holds: an imported/borrowed reference slower than the driven lap is never shown as a target.

## Open questions
ws:9121 frame schema · is the pro pedal trace numeric or curve-only · is Garage 61 a cleaner AC pro-line
source · can `.acreplay` be parsed locally to make us fully self-sufficient.
