---
type: decision
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-07-01
issue: https://github.com/agorokh/ac-copilot-trainer/issues/368
relates_to:
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Intensity-expressive voice coach — tone reflects the situation (issue #368)

## Context

The phrase-bank voice coach ([[voice-coach-architecture-2026-06-28]]) was audible but failed the
race-coach bar: artificial, slow, "delayed fact narration" not an on-the-mark coach. Measured
baseline (macOS `say`, the old vocabulary): critical "brake" cues were **1466–1733 ms** — 3–4× the
race-usable budget; "Brake, turn seventeen" finished after the braking zone. Operator mandate: a
**frontier** real-time coach whose **tone reflects the situation** — intensity by directions/context,
"not just 'turn left'".

## Decision

**Intensity is a baked, content-addressed `register` dimension — not hot-path TTS.** Because baking
is offline, every cue is pre-rendered at a tone tier; the hot path stays jitter-free clip playback
(invariant: no live TTS). Tone is delivered with zero runtime cost.

1. **Three orthogonal axes.** `urgency` (info/prepare/act) drives the SCHEDULER only (priority,
   barge-in, verbosity). `register` (calm/alert/urgent/critical) drives the baked TONE only. The
   manifest key grew from `(kind, urgency, corner)` to `(kind, urgency, register, corner)`;
   `MANIFEST_VERSION=3` is the current schema after issue #381 added the four-tier ladder and
   persona/intensity metadata in `voice_signature`. `register` is in the `clip_id`, `ClipEntry`, and
   `vocabulary_hash`, so drift is still detected and `rank` (arbitration) stays urgency-only.
2. **Severity → register in the observer.** Each cue carries a continuous `intensity` scalar
   `s∈[0,1]` from real telemetry + the reference envelope (late_brake: zone-progress + closing speed
   above the apex target; brake_release: brake level past apex; apex_deficit: km/h deficit), quantized
   to a register with **Schmitt hysteresis** + a per-kind cap. The float never reaches the manifest
   (would explode the bank); it rides the Advisory for haptics/logs/the timing report.
3. **Terseness built into the key.** Anticipatory low-intensity cues carry the corner number
   ("Brake point, turn three"); the act tier is corner-less ("Brake.", "Brake!") → ≤450 ms. A stem
   carries a number iff it contains `{turn}`; that single rule bounds the bank (**46 clips**, was 126).
4. **Anticipatory firing.** The brake cue fires within a speed-scaled spline LEAD before the brake
   point, so the audio ONSET lands before/at the mark, not after (AC a). Lead derives from a
   configurable lap length, not a fabricated field.
5. **Prosody by DSP over any backend.** A deterministic per-register ffmpeg chain
   (tempo/pitch/loudness/compression/high-shelf) shapes the synthesis; `-bitexact` keeps file-byte
   sha reproducible run-to-run (gated cross-build by `voice_signature` = ffmpeg ver + prosody ver).
   Backends: **Kokoro-82M (Apache-2.0)** recommended for the rig; **macSay-expressive** for Mac
   dev/listen; **ToneBackend** stays stdlib/no-ffmpeg so CI bakes a register-distinct bank.
6. **New control points (braking-first slice):** `late_brake` (anticipatory, register-escalating) +
   `brake_release` (over-braking past apex while off-throttle). `throttle` was emitted live but
   dropped by `_normalize_frame` — now extracted. `turn_in`/hold/unwind/throttle/track_out/gear are
   the documented next slice (need steering/line grounding to stay honest).
7. **Issue #381 expressive ladder.** Canonical registers are now `calm`, `alert`, `urgent`, and
   `critical`; legacy `firm` producer input is normalized to `urgent` so old logs and advisory
   emitters do not go silent. The voice persona is explicitly project-authored:
   `race-engineer-original-v1`, license/source `project-authored; no unconsented real-person clone`.
   Every backend signature appends `race-engineer-original-v1+intensity2`, so a bank baked before the
   persona/intensity-chain bump is refused as stale.

## Reconciliation that mattered

The `realtime_observer.py:99` comment claiming the live `telemetry_tick` payload "does not yet carry
spline (needs #277)" was **STALE**. Live code proves otherwise: `telemetry_publisher.lua:212` emits
`spline` (and `throttle`) at 20 Hz; `external_protocol._validate_telemetry_tick` accepts `spline`
(0..1). So the mechanism works on the rig today — only audible verification at the wheel is rig-gated.
The stale comment was corrected. (A 5-agent design + adversary workflow had trusted the comment; live
`git grep` overturned it — the closing-reconciliation discipline.)

## Verification (off-rig, observed)

Acoustic measurement proves the headline rather than asserting it. Same word "Brake" across registers
(say-expressive bank): **calm 805 ms / −26.7 dBFS / 1874 Hz → urgent 428 ms / −22.9 dBFS → critical
407 ms / 1873 Hz** — monotonic shorter+louder+brighter = measurable urgency, all act cues ≤450 ms.
Issue #381 extends this to four baked tiers (`calm`/`alert`/`urgent`/`critical`); ToneBackend bakes
four byte-distinct register clips in CI. ffmpeg shaper is byte-deterministic run-to-run.
Timing-report harness + voice benchmark are durable tools (`tools/ai_sidecar/voice/{timing_report,
bench_voices}.py`). **Perceptual** naturalness ("sounds like an authoritative engineer") remains a
rig audit per AC d — not closed by CI.

## Deferred

Rig Kokoro bake + at-the-wheel audible audit; turn_in/hold/unwind/throttle/track_out/gear cues;
mid-pass calm→critical re-escalation barge-in (the dedup key already admits it); CM-launch parity
live harness mode.
