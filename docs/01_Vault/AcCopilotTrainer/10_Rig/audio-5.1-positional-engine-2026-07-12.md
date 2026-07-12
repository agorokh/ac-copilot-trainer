---
type: investigation
status: active
created: 2026-07-12
updated: 2026-07-12
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
---

# 5.1 positional engine audio — front/rear by car layout (LIVE-VERIFIED 2026-07-12)

**Goal:** a rear-engined car (911) should be heard from the **rear** speakers, a
front-engined car (M3 GT2) from the **front** — using an added rear speaker pair.

## Hardware

- **USB 5.1 card = C-Media CM6206** (`USB\VID_0D8C&PID_0102`), Windows endpoint `5.1 Speakers`.
  Jacks: green=front (FL/FR), black=surround (SL/SR), orange=center/sub (**empty** — 4-speaker rig).
- **Bass Shakers = TI PCM2902** (`USB\VID_08BB&PID_2902`) — a **separate** stereo USB DAC,
  untouched by this work. (SimHub ShakeIt → amp → Dayton BST-1, see epic #59.)

## Root cause of "only front playing"

The CM6206 endpoint was configured **Stereo**: `DeviceFormat = 2ch, channelMask 0x3 (FL,FR)`.
Windows only fed the front jack; the black surround jack got nothing. Speakers/wiring were fine
(rear pair verified working on the mobo card).

## Fix

Sound (`mmsys.cpl`) → 5.1 Speakers → **Configure → 5.1 Surround** → Finish.
Endpoint now **6ch, `physicalSpeakers = 0x60F`** (FL FR FC LFE SL SR — side surround).
Center/sub left checked in the wizard but jacks are empty; Windows folds center into the fronts.

## Propagation to Assetto Corsa

AC/FMOD **inherits the OS speaker layout** — there is **no in-AC 5.1 toggle** and CSP has no
device/channel selector. Requirements: (1) 5.1 card is the **default** playback device (it is),
(2) AC **launched fresh** after the Windows change (FMOD reads speaker mode once at init).

## Live verification — harness drive + WASAPI loopback

`auto_drive --car … --track spa --driver ggv` + a WASAPI-loopback per-channel RMS probe
(`PyAudioWPatch`) on the `5.1 Speakers` endpoint. Car identity confirmed via `acpmf_static`.

| Car (layout) | FRONT FL,FR | SURROUND SL,SR | surround/front |
|---|---|---|---|
| 911 GT3 R (**rear**) | −24.3 dBFS | −24.6 dBFS | **0.959 (−0.4 dB)** |
| M3 GT2 (**front**) | −19.9 dBFS | −21.8 dBFS | **0.803 (−1.9 dB)** |

**Conclusion:** 5.1 fully propagates (all 6 channels active, distinct — not a fake upmix), and
engine layout shifts the front/rear balance as designed: the rear-engined car pushes ~1.5 dB
more relative energy to the rear than the front-engined car. The effect is **realistic/subtle**,
not "all-front vs all-rear" — surround channels also carry ambient (tyre/road/reverb).

## Tooling note

Probe lives in session scratch (`loopback_probe.py`, PyAudioWPatch + numpy). Audio localization
is **out of scope** for the harness CI oracles (`18_Autonomous_Harness.md`, false-green KPI) — it
is the live arm's job. **Candidate to promote** to `tools/ac_harness/audio_probe.py` (issue-first)
so per-car audio-layout checks compose on the harness like HUD/telemetry do.
