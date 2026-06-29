---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-29
updated: 2026-06-29
issue: https://github.com/agorokh/ac-copilot-trainer/issues/368
relates_to:
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Issue #368 voice coach — merge contention with a concurrent steward (2026-06-29)

## Summary

`/autonomous-deliver 368` (ultracode) shipped the intensity-expressive voice coach (PR
[#371](https://github.com/agorokh/ac-copilot-trainer/pull/371)) — see
[[voice-intensity-register-2026-06-28]]. During PR resolution a **concurrent fleet steward was
live-editing the same worktree/branch**, producing a chaotic mid-merge state. This node records the
contention + the recovery so the next agent does not re-walk it.

## What happened

1. My session committed the #368 implementation (`940d754`) and addressed the first 7 bot findings
   (uncommitted).
2. A steward sweep **stashed my WIP** (`resolve-pr-371-review-fixes`), then started
   `git merge origin/main` — which had **independently shipped a parallel voice subsystem**:
   an anticipatory `brake_prepare` cue (`_lead_spline_fraction`, `track_length_m`,
   `_BRAKE_PREPARE_LEAD_S`) + a pyttsx3 **server TTS** path (`_wire_voice`, `_Pyttsx3VoiceCoach`).
   That overlapped my register/intensity/anticipatory work → real conflicts in
   `realtime_observer.py`, `bake.py`, `test_voice_bake.py`, `pyproject.toml`.
3. I aborted the half-broken merge once (it re-ran), then **stopped fighting** when I detected the
   steward editing `pyproject.toml` *between my read and write* (duplicate `launcher` extra). The
   steward then **committed a clean integration** itself: `3bd4f41 fix(voice): address PR 371 review
   findings` + a merge commit, and pushed. `make ci-fast` green.

## Resolution / what's true now

- The overlap is reconciled into **one** brake-cue path keyed on `register` (anticipatory =
  calm/prepare heads-up at the brake-point spline with `detail.lead_s`; at/past the point =
  severity-driven firm/critical escalation). `server._wire_voice` prefers the bank coach and falls
  back to the pyttsx3 TTS coach. Observer uses main's `_lead_spline_fraction` + my
  `_brake_cue`/`_brake_severity`/`_brake_release`/`brake_cue_rank` escalation.
- Round-2 codex findings fixed in `382b090`: critical→firm **barge-in** (register tie-break in the
  scheduler), **wrap-aware** lead window (`_in_arc`, first corner bp≈0), `has_braked` latch when
  braking in the lead, WS `CueArbiter` act-escalation **cooldown bypass**.

## Learnings (durable)

- **Two autonomous processes on one git worktree corrupt each other.** Symptoms: a stash you didn't
  create (`git stash list`), `MERGE_HEAD` you didn't start, files changing *between your read and
  write*. Detect early (`git status`, mtimes, stash list) and **do not race** — committing your work
  makes it durable (a stash sweep cannot undo a commit), and yielding to a competent steward beats a
  clobber war. Serializing concurrent sessions is an operator call.
- **Reconcile against live `origin/main` before assuming your feature is net-new.** Main had shipped
  overlapping voice work while #368 was in flight; the closing-reconciliation discipline (pasted
  `git show origin/main:…` greps) surfaced it before I baked a wrong merge.
- The earlier stale-comment trap repeated in miniature: `realtime_observer.py:99` claimed the live
  payload lacked `spline`; `telemetry_publisher.lua:212` proves it emits spline+throttle at 20 Hz.

## Follow-ups

- At-the-wheel audible audit of the Kokoro rig bank (rig-gated; off-rig measured + a demo WAV were
  delivered). Deferred cue taxonomy: turn_in/hold/unwind/throttle/track_out/gear.
