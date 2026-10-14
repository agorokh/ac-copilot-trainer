# Tablet voice endpoint + audible-latency harness

**Status:** Active
**Owns:** the remote coaching-audio endpoint and the end-to-end audible-timeliness harness. Current native-audio/microphone acceptance belongs to [#531](https://github.com/agorokh/ac-copilot-trainer/issues/531) Parts G/I; closed #511/#381 are implementation history.
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
5. Leave **Observe PC audio (normal)** selected and tap **TAP TO ARM AUDIO**.
   PC dispatches are displayed without being played a second time. PC WASAPI remains the
   authoritative critical-cue device until the actual native+wired P7 acoustic gate passes.
6. Status pills show WS/audio/clip state; the big tile shows the last dispatched cue.

### Native measurement probe (#531 Part G)

Select **Fully native measurement probe (wired)** before arming. Fully's JavaScript interface
must be enabled for the trusted localhost page. The installed Fully version must expose
`getInternalAppSpecificStoragePath`, `writeFileBase64`, `playSound`, `stopSound` and
`isWiredHeadsetOn` ([official API](https://www.fully-kiosk.com/en/#websiteintegration)).
The page checks each downloaded WAV against its manifest SHA-256 and caches it under Fully's
own app-specific `ac-copilot-voice/` directory using the content hash as its filename.
Critical dispatches request `fully.playSound(file:///…, false, 3)` only while a wired earpiece
is reported. Other probe registers use WebAudio. Missing bridge, hash mismatch, cache-write
failure or removed earpiece is an explicit unavailable result, never a production-route change.

For an isolated bench, silence the PC coaching output (or inject a silent playback in the
existing test seam) so the microphone cannot mistake PC speech for tablet output. Keep the
PC sync-chirp speaker audible and position the wired earpiece next to the tablet microphone.
The probe label is deliberately **UNMEASURED**. `voice.echo.t_play_ms` is a request timestamp,
including for Fully; only matched acoustic evidence can satisfy the latency gate. Restore
normal observation and PC output after the probe. This release does not automatically
promote a tablet to the production critical route.

### Opt-in microphone upstream (#531 Part I)

Tap **START MIC** on the endpoint. The page requests microphone permission explicitly and
checks the effective `getSettings()` processing flags, requiring echo cancellation, automatic
gain and noise suppression to be off. AudioWorklet streams PCM16 mono at its actual context
sample rate through the existing USB-loopback WS. No microphone audio is played back locally.
The red **MIC LIVE** state and **STOP MIC** button remain visible. Capture automatically ends
after 180 seconds, on page hide/exit, track mute/end, context suspension or WS loss/backpressure.
Reconnection never rearms it.

Only a local `voice` peer explicitly sending `voice.mic.subscribe` receives chunks; the
sidecar does not persist, cache, or broadcast PCM to dashboards, Lua, remote peers or its
dispatch/echo history. Pre-subscription audio is discarded. The recorder rejects sequence or
sample gaps, duplicates, rate/identity changes, stream end, timeout and disconnect. A new run
needs a new output directory; prior WAV evidence is never overwritten. Audio is personal
local evidence and must not be committed or uploaded.

No WiFi is involved — `adb reverse` carries the socket over the cable, which sidesteps both
the mesh cross-AP TCP block and the tablet's 2.4 GHz/CGNAT limitation (#511).

## Runbook — audible-latency measurement (#381)

The harness records the room via the tablet mic, anchors the recording to the PC wall clock
with start/end chirps (5→15 kHz, DAC-stamped via PortAudio callback), matched-filters each
dispatched clip's own waveform out of the recording, and reports
`audible_latency_ms = acoustic onset − dispatch stamp` per cue with P50/P95/max.

Start the harness, then tap **START MIC** within 30 seconds. For Part G's gate use the native
probe with a **wired earpiece**, positioned so the microphone hears it. A speaker-only test
can exercise capture but does not satisfy wired-path acceptance.

```powershell
# bench burst — full path, no sim needed (voice.demo cues through the real scheduler)
python -m tools.ai_sidecar.voice.audible_latency run `
  --bank $env:AC_COPILOT_VOICE_BANK --out-dir .scratch\audible-latency `
  --burst 12 --capture browser --require-native-wired

# passive capture — operator drives; no autonomous-driving permission is implied
python -m tools.ai_sidecar.voice.audible_latency run `
  --bank $env:AC_COPILOT_VOICE_BANK --out-dir .scratch\audible-latency-drive `
  --observe-seconds 60 --capture browser
```

Artifacts land in `--out-dir`: `room_capture.wav`, `dispatches.json`, `echoes.json`,
`chirps.json`, `capture.json`, `audible_latency.json` + `audible_latency.md` (per-cue table + assertions).
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
- `--capture scrcpy --scrcpy <exe>` retains the legacy recorder for compatible devices;
  scrcpy crashes on this P7 and is not the default proof transport.
