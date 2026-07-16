---
type: investigation
status: active
created: 2026-07-16
updated: 2026-07-16
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/531
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-531-partd-live-vitals-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
---

# #531 Part D remainder + Part E — race.status, shift cues, audio_routing (PR #615)

PR [#615](https://github.com/agorokh/ac-copilot-trainer/pull/615) squash-merged as `de04860`
(2026-07-16). Parts delivered: **D remainder** (clean fuel/predicted-lap fields) + **E**
(shift cues, `audio_routing`, tier-2 lane wiring).

## What shipped

- **`race.status` topic** (sidecar-produced, ≤1 Hz, change-gated): `RaceStatusTracker`
  (`tools/ai_sidecar/race_status.py`) fuses `RaceManagementObserver.fuel_status()` (new
  ungated read) + Lua `delta`/`lap` topics. **Predicted lap anchors on the delta's OWN
  baseline** — the Lua delta now carries `reference_lap_ms` (= `state.activeReferenceLapMs`);
  prediction is suppressed without it, never mixed with the stint best (Codex catch).
- **Shift cues** (`tools/ai_sidecar/shift_observer.py`): `upshift` from the learned
  `shift_profile.lua` target riding the tick as `shift_rpm`(+`shift_rpm_source`), heuristic
  0.92×`rpm_max` fallback; `downshift` = conservative sustained-bog heuristic (labelled
  `bog_heuristic`). Register `calm`, once-per-gear-engagement + cooldowns.
- **`audio_routing`** on every cue: `urgent`/`critical` → `authoritative_pc`, `calm`/`alert`
  → `tablet_native` (`registers.audio_routing_for_register`; Part G re-derives from measured
  latency). **`coaching.voice` is ALWAYS `authoritative_pc`** — the tap fires post-playback,
  so a register hint there would invite tablet double audio.
- **Dash**: prefers sidecar fuel fields (client burn stays as `est` fallback), fills the
  design's `predicted` timing row (was in the frozen mock, never implemented), renders the
  §8 tier-2 micro-cue slot (`UPSHIFT ▲` … 4 s dwell, at most one).

## Durable rules confirmed

- **Shift cues never reach the PC voice** — vocabulary-gated at the subscribe seam; adding
  kinds to the vocabulary would invalidate the baked bank (`vocabulary_hash`), so new
  glanceable-only kinds stay out of `KINDS` deliberately.
- **Single-stream state must reset on producer release** — any new observer/tracker fed from
  the tick belongs in `_release_observer_feed()` too.
- **`session` frames are replayed to late subscribers** — a consumer must compare identity
  before dropping state (tracker `note_session`), never treat the frame itself as a change.
- Fuel-state `None` is ambiguous: channel-missing (keep) vs burn-reset-while-live (drop) —
  disambiguated with `channel_live` at the server tap.

## Review

6 Codex P2s, all real, all fixed in one batched round (`c6c7796`); threads replied with
evidence + resolved. Self-hosted daemon posted no review on either SHA (two full cooldowns) —
vacuous-absent path. resolve-gate: no substantive findings hanging.

## Verification state

- 131 focused tests + `make ci-fast` green; dash rendered against a live branch sidecar
  (:8799) with zero console errors and the honest WAITING states intact.
- **Live P7 pass rides the next rig session** (same session, task queued): restart the :8765
  sidecar from merged main, drive, observe fuel/predicted/shift-cue fields on glass + the
  still-unobserved TC/ABS intervention flash (PR #595 made it evidencable).
