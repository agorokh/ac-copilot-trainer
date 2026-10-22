---
type: handoff
status: active
created: 2026-10-22
updated: 2026-10-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
pr: https://github.com/agorokh/ac-copilot-trainer/pull/925
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-22-214522Z-post-merge-pr923-815-run03.md
---

# #815 acoustic analyzer joins on the monotonic clock (PR 925)

[PR 925](https://github.com/agorokh/ac-copilot-trainer/pull/925) merged as `78e1fe9` from
vetted head `2c97581` (author vendor anthropic). The final round was clean on cursor,
antigravity and grok. Grok's earlier HIGH finding (dispatch `t_mono_ms` "unwired") was
disproved: `VoiceDispatch` stamps `time.monotonic()`. Its robustness half became the
`dispatch_monotonic_stamped` gate. Grok's MEDIUM was answered with a test of the CLI
`analysis_incomplete` NO_GO path. CI was green; 128 local tests passed.

## Why

Windows Time slews the rig's wall clock, which moved 37.4 ms against monotonic over seven
minutes in run 03. As built, the old 10 ms wall/monotonic gate failed any capture over ~2 min.

## Contract now

`live_acceptance` scopes and joins on `mono_ms` / `t_mono_ms` and reports `timebase:
monotonic`. Events use `onset_ms` / `earliest_ms` / `completion_ms`. `play_chirp` records
`t_dac_mono_ms`. A legacy wall-only chirp converts via `chirp_monotonic_anchor` (local offset
within ±1 s, spread as uncertainty). `wall_clock_drift` is diagnostic only.
`monotonic_timebase_valid` requires complete stamps, an increasing interval, an ordered wire
and sub-ms callback stamps, which rejects GetTickCount64 (Python < 3.13 on Windows).

## Observed

Run 03 was re-analysed through the installed rig checkout (`analysis-monotonic-78e1fe9.json`).
The timebase qualifies at ±28.3 ms, with slope disagreement 1.0 ms (was 8.0 ms with wall joins).
19/19 phrases sit inside calibration, located 17–29 ms after dispatch. It is still NO_GO:
phrases are masked by AC on the shared stereo channels (loopback complete 5/19), and there
was no `act` cue. Old-bytes gate failures are expected; details are on
[#815](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6352822566).
The temporary rig worktree was removed.

## Next action (#815 open)

Operator: separate voice from game audio (5.1/7.1 rear channels with AC on the front, or AC
on another output). Then one bounded run via the composed procedure (#923). Timebase and
anchor gates are no longer blockers on this rig. Fan-out: none created.
