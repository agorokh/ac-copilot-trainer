# Tablet voice endpoint + audible-latency harness

**Status:** Active
**Owns:** the remote coaching-audio endpoint (issue [#511](https://github.com/agorokh/ac-copilot-trainer/issues/511) Part D) and the end-to-end audible-timeliness measurement (issue [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) verification).
**Protocol reference:** [12_WS_Sidecar_Protocol.md](12_WS_Sidecar_Protocol.md) § Tablet voice endpoint.

## Why

The in-ear coach's hot path is proven off-sim (emit→dispatch asserted in CI), but "how timely
is it *in the ear*" needs a real room: WS hop + endpoint audio stack + speaker→ear. The rig PC
has no microphone; the 7" Android dashboard tablet (PRITOM P7, #511) provides both halves over
one USB cable — its **mic** becomes the PC's room capture (scrcpy), and its **audio jack**
becomes the coaching output (earpiece), which also separates coaching from PC-speaker
engine/game noise.

## Architecture (one paragraph)

The sidecar's `VoiceCoach` playback is wrapped in a dispatch tap
(`tools/ai_sidecar/voice/dispatch.py`): every clip the scheduler actually dispatches is
broadcast as a `coaching.voice` frame stamped `t_wall_ms` at dispatch. The tablet opens
`http://127.0.0.1:8765/tablet/voice` (reached over `adb reverse`), preloads every bank clip
into WebAudio buffers, plays each `coaching.voice` frame (seq-based barge-in, silent-loop HAL
keep-warm), and reports `voice.echo` timestamps back. The tablet never re-arbitrates cues —
the PC scheduler stays the single arbiter (pre-baked-bank + one-arbiter invariants hold).

## Runbook — coaching in the earpiece (operator)

1. Tablet plugged into the rig PC via USB, USB debugging ON (one-time "Allow" tap).
2. On the PC (adb from `Google.PlatformTools` winget package):

   ```powershell
   adb reverse tcp:8765 tcp:8765
   ```

3. Start the sidecar with voice configured as usual (Game Point launcher or harness;
   `AC_COPILOT_VOICE_BANK` + `AC_COPILOT_REFERENCE_ARCHIVE`).
4. On the tablet open `http://127.0.0.1:8765/tablet/voice` (Chrome or Fully Kiosk start URL).
5. Plug the earpiece into the tablet, tap **TAP TO ARM AUDIO** once.
6. Drive. Status pills show WS/audio/clip state; the big tile shows the last spoken cue.

No WiFi is involved — `adb reverse` carries the socket over the cable, which sidesteps both
the mesh cross-AP TCP block and the tablet's 2.4 GHz/CGNAT limitation (#511).

## Runbook — audible-latency measurement (#381)

The harness records the room via the tablet mic, anchors the recording to the PC wall clock
with start/end chirps (5→15 kHz, DAC-stamped via PortAudio callback), matched-filters each
dispatched clip's own waveform out of the recording, and reports
`audible_latency_ms = acoustic onset − dispatch stamp` per cue with P50/P95/max.

For the measurement run play the tablet on its **speaker** (the mic must hear the cues);
switch to the earpiece for the operator run.

```powershell
# bench burst — full path, no sim needed (voice.demo cues through the real scheduler)
python -m tools.ai_sidecar.voice.audible_latency run `
  --bank $env:AC_COPILOT_VOICE_BANK --out-dir .scratch\audible-latency `
  --burst 12 --scrcpy <path-to-scrcpy.exe>

# drive mode — passive window while the autonomous harness (18_Autonomous_Harness.md) drives
python -m tools.ai_sidecar.voice.audible_latency run `
  --bank $env:AC_COPILOT_VOICE_BANK --out-dir .scratch\audible-latency-drive `
  --observe-seconds 300 --scrcpy <path-to-scrcpy.exe>
```

Artifacts land in `--out-dir`: `room_capture.wav`, `dispatches.json`, `echoes.json`,
`chirps.json`, `audible_latency.json` + `audible_latency.md` (per-cue table + assertions).
Exit code 0 iff the clock map anchored, every dispatched cue was acoustically located, and
act cues (+ stated systematic uncertainty) fit the 450 ms budget.

### Honesty notes

- The chirp anchor carries the PC output-path estimate; the report states the systematic
  uncertainty (±15 ms with DAC stamps, ±60 ms without) rather than hiding it.
- Cross-device clocks are never subtracted: tablet-clock intervals (`t_play − t_receive`) and
  server-clock intervals (echo RTT) are reported separately.
- An unmatched cue is a FAILED assertion, not a dropped row — silence must never read as
  timely.

## Known limits (v1)

- The tablet page assumes a no-token loopback WS (the `adb reverse` deployment); a token gate
  on a non-loopback bind would need a page-side token input (browser WS cannot set headers).
- WebAudio output latency on the P7 is measured, not assumed; if the drive-mode median audio
  stack exceeds ~150 ms or σ > 40 ms, the fallback is Fully Kiosk's native player (council
  recommendation, 2026-07-11).
- scrcpy audio capture needs Android 11+ (P7 is Android 13 Go).
