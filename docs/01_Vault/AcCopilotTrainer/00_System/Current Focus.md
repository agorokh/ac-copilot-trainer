---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-06
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Branch:** `main` (`a1b2126`). Working tree clean, all feature branches deleted locally and on origin.

**Status:** Issue #57 (Phase 5 HUD redesign, Parts A-E) and Issue #66 (P0 CSP runtime hotfix) both **CLOSED and merged**. 195 tests pass. CI fully green (build, ruff, csp-api, csp-ui-safety, Sourcery, CodeRabbit, Cursor Bugbot).

**Next:** Awaiting user direction. Candidates:

- **In-game verification** of PR #67 hotfix - confirm Settings window renders readable labels (not raw rgb text), main HUD shows telemetry + active suggestion, checkboxes toggle correctly, em dash renders properly.
- **Part D tuning** across multiple cars/tracks (thresholds +5 / +4 / +6 / +/-0.15).
- **Part D Nordschleife** O(1) bucket-lookup performance verification (170+ segments).
- **Next epic** - Phase 6 (scope TBD) or Phase 4 (#19, deferred).
