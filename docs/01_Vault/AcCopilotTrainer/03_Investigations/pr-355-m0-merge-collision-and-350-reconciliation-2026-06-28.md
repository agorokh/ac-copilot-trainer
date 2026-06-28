---
type: investigation
status: active
created: 2026-06-28
updated: 2026-06-28
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/354
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
---

# PR #355 — M0 voice-wiring merge collision + #350 reconciliation (2026-06-28)

## Summary

`/autonomous-deliver 350` discovered #350's premise was **stale** and that `main` was **red**, fixed
the red, and reconciled #350. Net: the #350 **Lua producer (Part A) was already merged**; only the
**rig-gated Part B** remains.

## Two findings

### 1. #350 Part A already shipped in PR #342 (issue-body drift)
- #350 created `2026-06-28T15:35:52Z` claiming "no live producer; `git grep telemetry_tick src/` empty".
- **PR #342** (M0 thin slice) merged `2026-06-28T16:14:43Z` — **39 min later** — adding the producer
  `M.publishTelemetryTickIfDue` (`telemetry_publisher.lua:158`, 20 Hz, clamped `spline` + floored `lap`,
  `_finite` guards) **wired** at `ac_copilot_trainer.lua:2274`, with tests. `car.splinePosition` is the
  canonical normalized 0..1 field used throughout the trainer (== the issue's `normalizedSplinePosition`).
- So #350 Part A = DONE. Reconciled on the issue (comment, pasted evidence). Only Part B (operator hears a
  spline-anchored cue on the rig) remains — operator/rig-gated, not autonomously verifiable.

### 2. `main` was RED from a #342×#349 merge collision → fixed in PR #355 (#354)
- `build: failure @ 84b5698`. **#349** (`c477aee`) shipped `_publish_coaching_cues` + best-effort
  `_wire_voice`; **#342** (long-running branch) added `tests/test_server_observer_wiring.py` against the
  *older* names `_publish_observer_cues` / `_load_observer` (fail-fast `SystemExit`). Green alone; the
  merge left the test referencing dead symbols (AttributeError ×9) + a second defect: `_reset_external_state()`
  cleared peers + rate-limiter but **not** the single-producer globals `_observer_feed_peer`/`_observer_feed_warned`,
  so `test_voice_wiring.py`'s autouse reset leaked feed ownership → later producer rejected → empty cue /
  `voice.recv()` timeout (AssertionError reproduced on the **Linux CI runner** — not a local artifact).
- **Fix (PR [#355](https://github.com/agorokh/ac-copilot-trainer/pull/355), squash `27cb7100`, #354 CLOSED):**
  `_reset_external_state()` also clears the feed globals (correct on server (re)start/teardown); removed a
  duplicate `_observer` decl; test file targets `_publish_coaching_cues`, the stale `_load_observer`
  `SystemExit` tests replaced with best-effort `_wire_voice` tests (non-vacuous sentinels; builder coverage
  already in `test_realtime_observer.py`). **`build` green on `27cb7100`**; full suite `1513 passed, 0 failed`
  (Python 3.11). 3-agent adversarial pre-merge review (all approve).

## Lessons
- Two PRs green independently can red `main` at merge when one **renames** a symbol the other's new test
  references. Reconcile colliding long-lived branches against the *merged* API, not each branch's own.
- The fleet metered review bots (CodeRabbit, Sourcery, Gemini, Codex) were **all quota-limited / inactive**
  on this repo on 2026-06-28; only Qodo reviewed (clean). The self-hosted daemon App is not installed here.

## Follow-ups (separable, noted on #350)
- `external_protocol._validate_telemetry_tick` validates `spline`/lap **twice** (`external_protocol.py:332-338`
  & `:349-355`) — merge debris; harmless but redundant. Cleanup candidate.
- Producer hardcodes `lat_g=0, long_g=0` (`ac_copilot_trainer.lua:2278-2279`); inert for the observer (keys on
  spline/speed/brake) but a cheap completeness fix (CSP `car.acceleration`).
