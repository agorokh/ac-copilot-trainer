---
type: handoff
status: active
created: 2026-10-23
updated: 2026-10-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
pr: https://github.com/agorokh/ac-copilot-trainer/pull/930
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-23-020054Z-815-run05-ac-volume-acoustic-criterion.md
---

# #815: reverb-aware phrase completeness merged; run 05 is 19/19 complete

[PR 930](https://github.com/agorokh/ac-copilot-trainer/pull/930) merged as `3e9732a` from the
vetted head `662f573` (author vendor anthropic).
- Round 1: antigravity raised 2 MEDIUM findings, both adopted. The interval exclusion now runs
  on the reverb-aware verdict through `apply_completeness`, and located cues carry the
  evaluator's reason.
- Rounds 2 and 3: antigravity and grok found 0 findings. The cursor lens hit its quota.
- Required checks were green. There is no merge queue and no final-event findings gate.

One CI failure came from a test tolerance: a 4-sample completion offset on Linux FFT rounding.
The bound is now 0.2 ms.

## The criterion

The design was council-reviewed before implementation:
- Mistral: no.
- Kimi and Perplexity: yes, with changes.
- Codex and ChatGPT timed out; Gemini and Grok were unavailable.

How it works:
1. A leave-one-out room response is fitted over the run's other phrases.
2. Each phrase gets one signed ±10 ms alignment.
3. Each phrase is split into 6 equal-speech-energy segments, scored after subtracting the
   predicted echo of earlier speech.
4. Each score is converted to a z value against a local null of 300 cue-free offsets.

A phrase passes only when the room model and all segments reach z ≥ 6. The criterion fails
closed with fewer than 5 other phrases or less than 10 s of null material. The dry 40 ms rule
remains only as the `dry_blocks_complete` diagnostic, and the result is ANDed with the
loopback proof.

**Gotcha:** `find_onset` ranks |correlation|. In the rig cabin it put 5/19 run-05 onsets on an
inverted lobe about 1.7 ms away. Any signed comparison against a fitted model must re-align
first.

## Proved state (installed rig checkout `3e9732a`, normal analyze path)

Run 05 (AC −19.8 dB) is **19/19 complete**. Room-model z is 47–78, the minimum segment z is
8.3, and the timebase is qualified at ±26.3 ms. Run 04 (AC at full level) is 11/19, with
masking.

Real-data controls with the production function (run 05 / run 04):
- truncation caught 19/19 and 18/18;
- ghost cues passing: 0/21 and 0/21.

Masked run-04 verdicts near z = 6 move between 11 and 13/19 with the null draw.
Evidence: [#815 comment](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6357940165).

## Remaining acceptance (#815 stays open; clause 36 unchecked)

Brake cues finish too close to the braking point. Minimum lead was:
- 349 ms at T1 on lap 0;
- 796 ms at T1 on lap 1;
- 3136 ms at the final corner.

The requirement is 1200 ms. Dispatch to onset is 18–23 ms, so the shortfall is cue
scheduling, not audio. No `act` cue fired, so `act_latency_budget` cannot pass. Re-analyzing
old bytes also loses the immutable-input and corner-target gates, because of later merges and
ledger appends. A fresh bounded capture on the current build is needed after any
lead-time change.

Rig: the primary checkout was fast-forwarded to `3e9732a`. Temporary worktree `ac815-reverb`
was removed; control evidence is preserved under
`.scratch/moza-qualification/live-acceptance/reverb-criterion-proto/`. No AC process or 8765
listener is left. Fan-out: none created.
