---
type: decision
status: active
memory_tier: canonical
created: 2026-06-27
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/pr-207-motec-reference-import.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
---

# Strategy: Track Titan as a swappable "coaching oracle" (implemented 2026-06-28, PR #334)

**Status: IMPLEMENTED** — landed in PR [#334](https://github.com/agorokh/ac-copilot-trainer/pull/334)
(`32c86e9`, 2026-06-28): `tools/ai_sidecar/coaching_oracle.py` (`CoachingOracle` + pure
parser/advisory mapping + pragma-guarded `TrackTitanScreenOracle`), `tools/ai_sidecar/tt_overlay_ocr.ps1`
(native `Windows.Media.Ocr`), `tests/test_coaching_oracle.py` (14 tests, 98% cov), pyproject
`package-data`. Grounded in [[track-titan-telemetry-extraction-feasibility-2026-06-27]] + Gemini
council + web research.

**Bot-review hardening (6 rounds — durable learnings for any screen-OCR provider):** prefer an English
OCR engine (`TryCreateFromLanguage('en-US')`, fall back to user-profile) so non-English Windows profiles
don't misread; cap the upscaled crop to `OcrEngine.MaxImageDimension`; dispose the `SoftwareBitmap` +
`IRandomAccessStream` in `try/finally` or the capture file stays locked and cannot be deleted; return a
guaranteed-flat `string[]` (PowerShell's unary-comma `,@(...)` idiom nests the array in JSON); gate
advisories on a real post-lap debrief (live HUD labels like `BRAKE`/`THROTTLE` must not mint advice) and
bound the debrief regex to a 2-line window; resolve the helper via `Path(__file__)` and ship it as
`package-data` for wheel installs; exit non-zero when both OCR passes fail so the caller returns `None`
rather than a misleading empty snapshot.

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
- **No redistribution, no automation at scale or on others' behalf.** Never redistribute TT content
  (TT bans setup redistribution); never automate the cloud API at scale, for third parties, or in any
  shared/deployed service. Never copy/log/transmit plaintext Cognito tokens into tracked files or logs.
- **Personal own-account export is permitted** (operator decision 2026-06-28; issue
  [#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)). Scoping clarification superseding the
  original blanket "never automate the cloud API with the user's token": exporting the **operator's own**
  session data from their **own** TT account for **personal, local** coaching use — via the same
  Cognito/`vulcan` path the official desktop app uses, on the same machine — is treated as **self
  data-portability**, not the prohibited at-scale / third-party automation that carries the ToS/CFAA
  exposure. Constraints still bind: tokens are personal secrets (read from env or the gitignored lake,
  **never** logged or committed); retained raw data stays under the gitignored `journal/tt`; nothing is
  redistributed; this is single-operator, local-only. Implemented by `tools/tt_ingest`
  (PR [#359](https://github.com/agorokh/ac-copilot-trainer/pull/359), #353 M-TT0).
- Honesty invariant holds: an imported/borrowed reference slower than the driven lap is never shown as a target.

## Open questions
ws:9121 frame schema · is the pro pedal trace numeric or curve-only · is Garage 61 a cleaner AC pro-line
source · can `.acreplay` be parsed locally to make us fully self-sufficient.
