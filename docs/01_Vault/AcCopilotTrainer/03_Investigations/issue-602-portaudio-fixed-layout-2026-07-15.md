---
type: investigation
status: verified
memory_tier: canonical
last_updated: 2026-07-16T01:45:00Z
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/10_Rig/audio-5.1-positional-engine-2026-07-12.md
---

# Issue #602 — PortAudio fixed-layout recovery

## Outcome

PR [#606](https://github.com/agorokh/ac-copilot-trainer/pull/606) fixes the rig voice
failure caused by opening the selected Windows WASAPI endpoint as a one-channel stream. The
phrase bank is mono/48 kHz, while `5.1 Speakers (USB Sound Device)` reports six output channels
and rejects one- and two-channel streams with PortAudio `-9998`. It accepts a six-channel stream.

The playback backends now probe supported output widths, open the smallest compatible layout,
and route mono phrases to front-center channel 3 when the negotiated device has at least three
channels. The health endpoint and Game Point status expose backend, selected device/host API,
bank channels, stream channels, device maximum, and channel map. Failure details preserve the
same fields plus remediation environment variables.

## Evidence

- Device: `5.1 Speakers (USB Sound Device)` on `Windows WASAPI`, maximum six output channels.
- Phrase bank: mono, 48 kHz.
- Negotiated layout: `1ch bank -> 6ch stream/6ch max map=[3]`.
- Game Point showed `VOICE ENABLED` with that layout while the sidecar was healthy and the screen
  was connected.
- A real `Brake!` phrase was dispatched through the live rtmixer stream and captured from the
  selected speaker's WASAPI loopback. The phrase waveform matched on channel 3 with score 1.0;
  channels 1, 2, 4, 5, and 6 were silent.
- Focused regression suite: 153 passed.
- Default-device latency chirps negotiate the selected PortAudio layout instead of assuming mono.
- Sounddevice expansion preserves every source channel for multichannel banks.
- Stereo-only endpoints duplicate mono to channels 1 and 2 in both rtmixer and sounddevice.
- Legacy injected Playback objects degrade to empty output metadata when the optional property is
  missing, invalid, or raises; voice initialization stays enabled.
- Full parity: 2,972 passed, 113 skipped, 87.60% coverage, `ci-fast: OK`.
- The verification launcher was stopped afterward; no Game Point window or port 8765 listener
  remained.

## Memory substrate

The mandatory Tier-3 prefetch was attempted before code changes. The configured substrate was
unreachable, so the repository hook recorded an allow-policy degraded stamp in
`.scratch/.last_memory_query.missing` (streak 1/3). No memory-gate bypass was used. Tier-2 vault
context supplied the session substrate.

## Resume

PR #606 is **merge-ready** on `7eec481`: required CI green, GraphQL threads resolved,
resolve-gate clean, and the current-SHA daemon cursor HIGH on sounddevice `index` was
replied-invalid with 0.5.1 source evidence. Merge through the normal maintainer workflow.
No additional rig reproduction is required unless the selected output device or host API
changes.
