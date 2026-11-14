---
type: investigation
status: active
created: 2026-06-30
updated: 2026-06-30
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Roadmap.md
---

# PR #410 Racing Atelier design package (2026-06-30)

## Status

PR [#410](https://github.com/agorokh/ac-copilot-trainer/pull/410) is **MERGED** on
[`d669b19`](https://github.com/agorokh/ac-copilot-trainer/commit/d669b19c001e79b751ad625599a82c32e9ce38f8)
(`feat/issue-400-racing-atelier-design`). Issue
[#400](https://github.com/agorokh/ac-copilot-trainer/issues/400) is **CLOSED** as of
2026-06-30T19:19:19Z.

## What shipped

- Canonical Racing Atelier handoff package at `docs/10_Development/design/racing-atelier/`.
- Render-target gate at `docs/10_Development/design/racing-atelier-renders/`.
- Retired AG Porsche Academy components removed from `docs/10_Development/design/components/`.
- Design README now points agents to the Racing Atelier source of truth.
- Review hardening: offline/CDN warnings for prototypes and Google Fonts; `support.js`
  prototype boot messages now target `document.referrer` origin when possible instead of always
  using wildcard `"*"`.

## Verification

- `gh pr checks 410 --watch=false`: `build`, `Canonical docs exist`, `conformance`, `classify`,
  and `score` passed; `guard-and-automerge` skipped as expected.
- `python -m pytest tests/test_design_conformance.py`: `21 passed` (pytest cache warning only;
  access denied writing `.pytest_cache`, not a test failure).
- `python scripts/post_merge_classify.py --pr 410`: no post-merge classification flags.
- ZIP reconciliation against `C:\Users\arsen\Downloads\Racing Atelier-handoff (1).zip`: the repo
  contains all 95 package files. Eight hashes match exactly; 80 differ only by CRLF/LF checkout
  normalization (`core.autocrlf=true`); the real text drift is the intentional security/offline
  hardening in `project/readme.md`, `tokens/fonts.css`, and the four template `support.js` files.
  One binary drift remains for `templates/track-atlas/.thumbnail`, matching the reviewed PR state.
- Browser proof: served `docs/10_Development/design/racing-atelier/project/` on temporary
  `http://127.0.0.1:55072/`, loaded `ui_kits/game_point`, `ui_kits/ingame_hud`, and
  `ui_kits/esp32_rig` in the in-app browser. Observed carbon backgrounds, brass corner brackets,
  brake/lift/clear signal colors, square borders, segment bars, and delta blocks. Console output
  contained only the known Babel CDN warning, which is now documented by the package warning.

## Reconciliation notes

The user-provided ZIP is the raw export, not the reviewed final state. Do **not** overwrite the repo
with that ZIP wholesale: it would remove the offline/CDN and `postMessage` hardening from PR #410.
If future work consumes the prototypes, preserve those mitigations or regenerate them from a safer
local prototype pipeline.
