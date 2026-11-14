---
type: decision
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/340
relates_to:
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# Voice coach architecture — pre-rendered phrase bank + urgency scheduler (issue #340)

## Context

The realtime pipeline already produces structured `Advisory{kind, urgency, message}` cues
(`tools/ai_sidecar/realtime_observer.py`) that render as **on-screen text** in the CSP HUD (#277,
closed/live-verified). A driver cannot read text mid-corner, so that channel is dead while driving.
This decision records the design of the **voice output layer** that consumes the *same* advisory
stream and **speaks** it — the "in-the-ear coach" north star from
[realtime-coaching-architecture-2026-06-22](realtime-coaching-architecture-2026-06-22.md).

> Note: the issue body referenced this node and a `.scratch/voice-coach-research-2026-06-28.md`
> dossier as "full traceability", but neither was ever committed (the `.scratch/` path is
> gitignored/per-worktree). This node now *is* the canonical decision record; the architecture below
> is reconstructed from the issue body + the council/research summary embedded there.

## Decision

**Pre-rendered PHRASE BANK, not live TTS in the hot path.** A GT3 at 250 km/h covers ~21 m in
300 ms; live-TTS jitter would land cues *after* the braking zone. The advisory vocabulary is
**bounded** (`kind` × `urgency` × universal corner number), so a baked clip bank gives deterministic,
jitter-free, sub-50 ms, zero-GPU playback while AC saturates the GPU. This mirrors CrewChiefV4
(clip-bank-first; TTS only as out-of-vocabulary fallback, deferred here).

Module `tools/ai_sidecar/voice/` (shipped v1):

- **`vocabulary`** — the bounded `(kind, urgency, corner 1..20 + generic)` phrase set; the ONE
  advisory→wording source. `vocabulary_hash()` content-addresses it so wording drift is *detected*.
- **`manifest`** — content-addressed `(kind, urgency, corner) → clip` map (`vocabulary_hash` +
  per-clip sha256 + `voice_signature`). The **only** advisory→audio mapping; nothing hardcodes
  wording→file in Python (no redundant-code drift between HUD and voice).
- **`resolver`** — `resolve(advisory) → Utterance` (v1 whole-clip lookup; v1.1 number-splicing hides
  behind this same signature). `Advisory` (semantic) and `Utterance` (rendered) are separate types.
- **`scheduler`** — urgency arbitration (act > prepare > info) on a dedicated thread: barge-in,
  per-pass dedup, TTL/staleness drop, per-kind cooldown. `act` is exempt from cooldown/TTL/dedup
  delay. Pure `process_pending(now)` core → fully unit-testable with injected clock + playback.
- **`playback`** — `Playback` protocol + pure `resolve_output_device(name, host_api)` (pins the
  headset, never the haptic USB-DAC) + lazy `RtMixerPlayback`/`SoundDevicePlayback` + a recording
  double. `numpy`/`sounddevice`/`rtmixer` are lazy-imported **here only**.
- **`config`** — verbosity levels (off/low/normal/high) + per-kind cooldown — the "how chatty" lever.
- **`bake`** — offline render of the bounded vocabulary → WAV + manifest. `ToneBackend` (stdlib,
  CI/verification), `PiperBackend` (production neural voice), `MacSayBackend` (macOS dev).
- **`engine`** — `VoiceCoach.from_bank(...)`; `subscribe(advisory)` is the in-process seam the
  telemetry loop feeds. Degrades to a logged no-op (never a wrong clip) on stale/invalid manifest.

## Consequences / invariants honored

- **Stdlib core stays dep-free** — audio deps behind the new `voice` extra, lazy-imported in
  `playback`/`bake` only; `make ci-fast` runs with no audio hardware (resolver/scheduler/manifest
  fully unit-tested via injectable playback + clock).
- **Local-only real-time path** — cloud excluded from the hot path (flaky rig hotspot); any cloud
  debrief is deferred and must fail closed to local.
- **Own headset endpoint** — voice never collides with the haptic USB-DAC (re-resolve by name +
  host-API on every startup; PortAudio indices drift on USB replug).
- **Reuse the seam** — the voice consumer subscribes to the same `Advisory` objects the HUD renders;
  a future RL/agentic coach emits advisories onto the same bus, never raw audio into the clip path.

## Deferred (v1.1+)

Runtime number-fragment splicing of dynamic values; live per-utterance TTS + OOV fallback; cloud
between-lap debrief; per-track corner-**name** clips; audio ducking; any in-sim Lua change.
**Final on-rig live verification with the operator at the wheel is rig-gated** → follow-up. This
landed the off-sim-testable engine (latency asserted in CI, target ≤ ~150 ms emit→dispatch).
