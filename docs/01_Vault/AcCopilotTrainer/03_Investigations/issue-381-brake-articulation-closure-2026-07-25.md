---
type: investigation
status: resolved
memory_tier: canonical
created: 2026-07-25
updated: 2026-07-25
issue: https://github.com/agorokh/ac-copilot-trainer/issues/381
pr: https://github.com/agorokh/ac-copilot-trainer/pull/690
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-381-intensity-verification-2026-07-03.md
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Issue #381 — critical Brake articulation accepted and guarded (2026-07-25)

Issue #381 is closed. PR
[#690](https://github.com/agorokh/ac-copilot-trainer/pull/690) merged as squash
[`f8c0ccc`](https://github.com/agorokh/ac-copilot-trainer/commit/f8c0ccc08c23c844286f6fd4bbf8524b90b89938)
at 2026-07-26T02:18:10Z.

## Operator finding and acceptance

The required baked A/B listen exposed a real defect that duration and spectral summaries had not:
the intensity3 critical `Brake!` sounded cut off at the end. The WAV container itself was not
truncated; it ended at zero with trailing quiet. The synthesis-speed plus prosody-tempo stack had
compressed the final consonant until it was perceptually incomplete.

The final intensity5 critical production WAV was played through Windows' default
`5.1 Speakers (USB Sound Device)`. The operator replied **"good"** after the corrected replay.
That is the explicit listening acceptance required to close #381.

## Delivered contract

- Kokoro base speeds: calm `0.95`, alert `1.26`, urgent `1.28`, critical `1.25`.
- The shaped `Brake` action cue must be `<=450 ms` for alert, urgent, and critical.
- The operator-calibrated `am_fenrir` critical clip must have audible energy extending through
  `360 ms`, measured in 5 ms RMS windows against a `-45 dBFS` floor.
- The articulation floor is voice-scoped, not treated as a universal phoneme-duration claim.
  Other Kokoro voices retain the action ceiling and remain available to the benchmark.
- Enforcement runs from `bake_bank()` after final mono PCM16 normalization. It does not run inside
  `KokoroBackend.synthesize()`, so `bench_voices` can still measure and report a failing voice.
- `INTENSITY_CHAIN_VERSION = 5`; stale intensity3/4 banks fail the signature gate.

## Real artifact evidence

Bank:
`C:\Users\arsen\Projects\ac-copilot-trainer\.scratch\coach-bank-kokoro-fenrir-v5-intensity5-articulation-20260725`

Signature:
`kokoro:am_fenrir+ff8+race-engineer-original-v1+prosody2+intensity5`

- Manifest valid; 76 clips.
- Alert / urgent / critical Brake duration: `432.6 / 412.9 / 409.9 ms`.
- All 76 approved-bank clips pass the post-normalization policy.
- The original intensity3 clip is rejected: its last audible 5 ms window ends at `330.0 ms`.
- The approved critical clip is byte-identical to the clip the operator heard.

## Verification and review

- Focused voice suite: 59 passed.
- `make ci-fast`: 3479 passed, 73 skipped, 87.15% coverage; Bandit and policy checks clean.
- Hosted CI on `3b5cbf99eb3fe6667ac621df8edcab038683ce0b`: build, conformance, and canonical-doc checks pass.
- Final exact-SHA Codex review: no major issues.
- Three review threads were addressed with real-bank evidence and resolved.

## Operational boundary

Issue #627 remains open, so this closure does **not** enable the bank in Game Point or claim a live
at-wheel voice session. The issue #381 acceptance contract was the baked production-clip listen;
live in-ear re-arm remains intentionally deferred until the rig launch freeze gate is cleared.
