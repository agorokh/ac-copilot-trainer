---
type: investigation
status: active
created: 2026-07-16
updated: 2026-07-16
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/531
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-531-parte-cues-fuel-2026-07-16.md
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/rig-physics-wedge-voice-wasapi-2026-07-16.md
---

# #531 Part F — COACH/MAP/STINT page depth (PR #618, 12 review rounds)

PR [#618](https://github.com/agorokh/ac-copilot-trainer/pull/618) squash-merged as `786f0b8`
(2026-07-16). COACH binds `session.review` (biggest gain, measured cause bars, priorities by
time lost); MAP renders REAL geometry from the new sidecar `track.map` topic (px/pz outline +
coach-aligned corners from `segment_corners`, spline-indexed live dot, pace-note queue); STINT
gains real I/M/O tread temps (`wheel_read` Tier-1 riding `tire_temps`) and a fuel plan with a
REAL race target (`session_laps_total` on the tick from `ac.getSession`). Durable
`tools/ai_sidecar/dash/dev_feeder.py` replaces the lost Phase-1 scratch feeder.

## The review gauntlet (12 rounds — the state-lifecycle onion)

19 Codex P2s + 2 daemon HIGHs + 7 MEDIUMs, all fixed or evidence-rebutted. The dominant theme:
**cached/replayed frame lifecycle** — every payload the sidecar caches for late subscribers
(`track.map`, `session.review`) needed an explicit identity contract on the client:
who clears it (identity change vs session_index-only vs stint re-arm vs first frame), who may
accept it (layout-exact when both qualified, base-track when one bare), and what a rejected or
failed frame must leave behind (full DOM reset, never residue). Codified in `identCompatible`
+ `resetMapDom` + `carTrackChanged`.

## Durable lessons

- **Every cached-replay topic needs a client identity contract up front** — retrofit cost here
  was ~6 review rounds. New sidecar-produced cached topics should ship with: accept-gate,
  clear-triggers, and failure-residue rules.
- **JSON finiteness is a wire contract**: one NaN/Infinity anywhere in a payload kills the
  whole frame at the tablet's `JSON.parse`. Filter at build time (outline AND metadata).
- **Daemon false positive rebutted with executed evidence**: it claimed Lua treats `0` as
  falsy (C/JS semantics); lupa-executed proof (`0 and 1 or 2 => 1`) posted on the PR. Lua's
  only falsy values are `nil`/`false`.
- Mid-review helper additions attract their own review tail (the session-laps cache took 3
  rounds alone: negative-cache → cross-session leak → 0-index FP).

## Follow-ups

- [#622](https://github.com/agorokh/ac-copilot-trainer/issues/622) — shared per-session key
  (session_uuid) across lifecycle `session` frames and `session.review`; plus the advisory
  track.map rebuild-broadcast if runtime re-wiring ever lands.
- **Rig verify pending** (blocked on #619 font-cache reboot): three pages on the P7 with a
  reference armed, `session_laps_total` live from CSP in a lap-count race, feeder-driven
  COACH/MAP against real archives.
