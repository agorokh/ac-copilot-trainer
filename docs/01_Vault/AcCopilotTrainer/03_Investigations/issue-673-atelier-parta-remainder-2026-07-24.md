---
type: investigation
status: active
created: 2026-07-24
updated: 2026-07-24
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/673
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# #673 Racing Atelier Part-A remainder — delivered

## Outcome

PR [#681](https://github.com/agorokh/ac-copilot-trainer/pull/681) MERGED
[`333ef93a9`](https://github.com/agorokh/ac-copilot-trainer/commit/333ef93a9a39742c2926d2d6f2af35c47cc95eb1)
(2026-07-25T06:45:49Z). Issue #673 CLOSED.

## What shipped

- `hud_settings.lua` — all palette colors from `design_tokens` (brass/chalk/mute/clear/lift).
- `racing_line.lua` — `speedColor` / `speedColorCache` endpoints from clear/lift/brake HEX.
- `coaching_overlay.lua` — deleted unwired cyan panels; re-tokenized `drawMainWindowStrip`.
- Conformance lock in `tests/test_hud_design_tokens.py` (surfaces require tokens; ban `rgbm(0.…)`).

## Verification observed

- `make ci-fast` green locally; hosted CI `build` / policy / conformance SUCCESS on head SHA.
- Lupa stub draw of Settings: title=`brass` `#C8983E`, section=`chalk`, label=`mute` (`VERIFY_OK`).
- Grep: no numeric `rgbm(\d` on the four Atelier surfaces; all `require("design_tokens")`.
- In-sim Settings/`WINDOW_2` chrome not photographed this session (no live AC harness run);
  token→draw path proven via the same lupa recording pattern as `test_hud_atelier_card`.

## Notes

- Tier-3 `ac_copilot` LightRAG endpoint was unreachable; session used memory-bypass rationale + vault.
- Self-hosted reviewer absent after cooldown (vacuous); no blocking reviewThreads.
