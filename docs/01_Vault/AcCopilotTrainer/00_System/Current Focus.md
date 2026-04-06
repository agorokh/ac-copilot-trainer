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

**Repo:** ac-copilot-trainer. **Issue #66 (P0 hotfix):** CSP textColored signature reversal + checkbox semantics + double-encoded em dash. Phase 5 was non-functional in-game until this fix.

**Branch:** `fix/issue-66-phase5-runtime-failures`. **PR #67** open.

**What this PR fixes:**
- All 66 `ui.textColored` calls reversed to text-first per CSP API
- `ui.checkbox` semantics fixed (returns CHANGED, not new value)
- Double-encoded UTF-8 em dash bytes corrected
- New `scripts/check_csp_ui_safety.py` static lint
- New `tests/test_lua_runtime_smoke.py` (11 lupa-based runtime tests)

**Issue #57 (Phase 5):** All 5 Parts merged but had this critical runtime bug. PR #67 will restore actual functionality.
