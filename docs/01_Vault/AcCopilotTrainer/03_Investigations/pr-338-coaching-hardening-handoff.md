---
type: investigation
status: archive
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/333
relates_to:
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
---

# PR #338 — CoachingOracle Qodo round-6 hardening (#333)

**Delivered** (squash-merged `f8d010e`, 2026-06-28): post-merge follow-up to [#334](https://github.com/agorokh/ac-copilot-trainer/pull/334) (`32c86e9`).
Addresses round-6 Qodo findings that landed on the final #334 SHA but were not included in the squash merge.

## What shipped

- `get_coaching()` None-on-failure: catch `AssertionError`; replace `assert` in `debrief_to_advisories` with early return.
- OCR debrief marker accepts spaced variants (`post lap debrief`).
- `_coerce_lines` drops nested `None` (no literal `"None"` strings).
- `tt_overlay_ocr.ps1`: bounded WinRT `Await` (10s/op, cancel on timeout) + stale capture cleanup; Python timeout 110s.
- Parse/helper failure logging via `logger.warning`.
- CI verification evidence in `docs/10_Development/14_Coaching_Oracle.md`.

## Verification

- `pytest tests/test_coaching_oracle.py` — 19/19 pass (includes default timeout regression).
- GitHub CI green (`build`, `conformance`, `Canonical docs exist`).
- `/resolve-pr` converged after main merge conflict resolution; resolve-gate clean.
