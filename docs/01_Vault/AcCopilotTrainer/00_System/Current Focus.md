---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-07
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Branch:** `main` (`72be94d`). Working tree clean, all session feature branches deleted locally and on origin.

**Status:** Issue #57 (Phase 5 HUD redesign Parts A–E), Issue #66 (P0 CSP runtime hotfix), Issue #69 (visual design match), and **Issue #72 (Phase 5 HUD rebuild — live-frame engine + bundled fonts + FIXED_SIZE windows + always-visible tiles)** are all CLOSED and merged. PR #73 was the last merge (`72be94d`). 186 tests pass. CI fully green (build, ruff, csp-api, csp-ui-safety, Sourcery, CodeRabbit, Cursor Bugbot).

**Single open gate:** in-game smoke test of PR #73 on Vallelunga + Porsche 911 GT3 R. The persistence file already has 7 brake points + 7 corner features + 13 segments + a 2000-sample best lap trace, so the live-frame engine should fire on the very first frame after `tryLoadDisk` runs — no fresh-session lap required.

**Next:**

- **In-game smoke test** of PR #73 (top priority) — confirm both windows render with proper Figma layout, BRAKE NOW / PREPARE TO BRAKE / CARRY MORE SPEED / EASE OFF fire from live-frame inputs, and FIXED_SIZE recovers the 132×456 saved geometry while still allowing drag.
- **Threshold tuning** in `realtime_coaching.lua` if the test reveals the 50/100 m + ±8 km/h bands are off.
- **Next epic selection** after the smoke test passes (Phase 6 TBD or Phase 4 #19).
