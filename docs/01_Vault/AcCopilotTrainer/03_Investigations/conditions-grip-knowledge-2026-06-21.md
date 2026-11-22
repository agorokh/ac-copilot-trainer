---
type: investigation
status: active
created: 2026-06-21
updated: 2026-06-21
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/tyre-thermal-knowledge-2026-06-21.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/282
---

# Verified conditions→grip knowledge (for conditions_model.py)

Adversarially-verified research (4 lenses → red-team that corrected several over-claims). Inputs:
lap-archive `conditions{trackGripLevel, ambientTempC, trackTempC, weatherType}`. The corrections are
**load-bearing** — they make the model conservative on purpose:

- **`trackGripLevel` is the ONLY authoritative, persisted, cross-session-comparable scalar.**
  Normalize on it ALONE; fresh stock session ~0.95-0.96, rubbers UP toward ~1.0 (rubber-in is the
  main driver; base AC does NOT auto-drop it from temp/rain). Cross-band normalization is
  **APPROXIMATE** (scalar→laptime is nonlinear/car-specific) — prefer comparing laps in the same band.
- **AC exposes NO reliable track-temp→grip percentage.** Any `-x%/°C` figure is fabricated; the real
  curve is per-compound, mod-dependent, on *tyre* temp (not track temp), not in the API. Temperature
  is **qualitative/directional only** (cold → slower warm-up, grip-limited laps 1-2; hot → switches
  on fast, overheats sooner). No grip-multiplier number, ever.
- **Wet/snow ⇒ the slick temp/grip model is INVALID** — gate it off; coach compound + water
  management; never "build heat aggressively" (wets run cooler).
- **`trackTempC` / `weatherType` are nullable**; `weatherType` enum isn't standardized across base
  AC/CSP/Sol → match defensively (lowercase substring); null weather = "unknown", not "dry".
- `trackGripLevel` > 1.0 just means session config set grip above reference — NOT "polished track →
  lockup" (that mechanism is fabricated). Sane band ~0.70-1.05 → outside = investigate config/data.

Encoded in `tools/ai_sidecar/conditions_model.py` (regime gating + grip-band classification +
approximate trackGripLevel normalizer + qualitative temp coaching, all findings carrying an
`approximate` flag). Full research: session task `ww78qo452`. Deliverable 5 of the program (#282).
