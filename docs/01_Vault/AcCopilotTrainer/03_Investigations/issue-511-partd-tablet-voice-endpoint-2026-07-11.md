---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-11
updated: 2026-07-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/511
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-381-intensity-verification-2026-07-03.md
  - AcCopilotTrainer/01_Decisions/usb-serial-screen-transport-2026-07-02.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #511 Part D — tablet coaching-audio endpoint over USB + #381 audible-latency harness

## What shipped (PR #519, merge `fb54b9d`, 2026-07-12 UTC)

The 7" PRITOM P7 becomes the in-ear coaching surface: earpiece on the tablet separates
coaching from PC-speaker game noise (operator directive 2026-07-11), and its mic becomes the
rig's room capture for the #381 "how timely" proof.

- **`coaching.voice` topic** — post-scheduler dispatch broadcast (`DispatchTapPlayback` in
  `voice/dispatch.py` wraps the real playback; clocks stamped BEFORE backend play). The
  tablet mirrors exactly what the coach speaks — one arbiter, zero client-side re-arbitration.
- **Sidecar HTTP** (same port as WS): `/tablet/voice` self-contained WebAudio page,
  `/voice/manifest.json`, `/voice/clips/<file>` (percent-decoded, exact-match manifest
  allow-list), `/voice/dispatches` + `/voice/echoes` ring buffers. Non-loopback clients need
  the WS token when one is configured; loopback (USB) passes untokened.
- **`voice.echo`** (tablet timestamps; cross-device clocks never subtracted) and
  **`voice.demo`** (loopback-only synthetic advisory through the REAL scheduler — bench
  entrypoint).
- **`tools.ai_sidecar.voice.audible_latency`** — scrcpy mic capture, DAC-stamped 5–15 kHz
  chirp clock-sync (start+end, drift-assertion), matched-filter onsets using each clip's own
  waveform, per-cue dispatch→audible latency + P50/P95/max vs the 450 ms act budget.
- Runbook: `docs/10_Development/19_Tablet_Voice_Endpoint.md`.

## Key findings (durable)

- **USB `adb reverse tcp:8765` kills the tablet networking problem** — same move as the
  ESP32 [[usb-serial-screen-transport-2026-07-02]]: no hotspot, no mesh cross-AP block, no
  CGNAT. `make_token_check` exempts loopback, so the browser (which cannot set WS headers)
  connects cleanly. Tooling: winget `Google.PlatformTools` + `Genymobile.scrcpy` 4.0
  (`--audio-source=mic-unprocessed --audio-codec=raw --record-format=wav` = PC-side room
  capture with no tablet app).
- **Matched-filter earliest-instance selection is subtle**: global argmax cross-assigns when
  the same clip sounds twice in one window; naive earliest-region gets fooled by periodic
  tone-clip correlation ramps (±1 template length) and chirp −13 dB sidelobes. Shipped rule:
  walk back from argmax to earlier candidates only if separated >1 template length AND
  ≥0.6× the max score. Reproduced synthetically before fixing.
- **Measurement honesty rails**: dispatch stamps pre-play (sounddevice stream-open bias);
  ring buffers filtered to the chirp-bounded window; missed end chirp fails
  `clock_map_drift_corrected`; burst asserts `all_burst_cues_dispatched`; unmatched cue =
  FAIL. Stated systematic uncertainty ±15 ms (DAC-stamped) / ±60 ms.
- **Review yield**: 3 bot rounds (1 cursor HIGH: URL-encode contract; 5 Codex P2s; 1 cursor
  MEDIUM whose literal fix would have broken arm-before-serve ordering — fixed at the correct
  lifecycle point instead) + an 18-agent adversarial workflow (11 confirmed findings, incl.
  all three measurement-validity HIGHs). The workflow caught what bots didn't: false-PASS
  bias vectors in the harness itself.

## Verified (observed)

- 117 focused tests green; `make ci-fast` OK (2481+); ruff clean.
- Live smoke on the real stack (sidecar from branch, intensity3 bank): all routes 200,
  traversal 404, `voice.demo` → real rtmixer dispatch on the USB Sound Device →
  `coaching.voice` broadcast (seq/duration/t_wall) → CUE-ECHO `rtt_ms=0.9`.

## What remains (staged, one physical tap away)

The tablet shows the adb "Allow USB debugging" dialog — the ONLY blocker for the hardware
half. When tapped: `adb reverse tcp:8765 tcp:8765` → open `http://127.0.0.1:8765/tablet/voice`
→ tap ARM → `audible_latency run --burst 12` → `auto_drive` (Magione + 911 GT3 R, reference
staged at `.scratch/coach-demo/reference.json`) with `run --observe-seconds 300` → evidence
on #381. Operator's A/B listen then runs through the tablet earpiece.
