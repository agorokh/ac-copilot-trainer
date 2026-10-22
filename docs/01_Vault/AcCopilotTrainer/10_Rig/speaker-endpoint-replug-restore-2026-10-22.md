---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-22
updated: 2026-10-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/10_Rig/audio-5.1-positional-engine-2026-07-12.md
  - AcCopilotTrainer/10_Rig/_index.md
---

# Rig speaker endpoint: why a USB replug loses the 5.1 layout, and how it was restored

## Cause

The rig speakers are a C-Media CM6206 (`USB\VID_0D8C&PID_0102`). The card has 4 speakers on
the green (front L/R) and black (surround L/R) jacks; the orange center/sub jack is empty.
Windows keys an audio endpoint's configuration to the **USB device instance**, which includes
the port path. Moving the card to another USB port creates a **new endpoint**. That endpoint
gets stereo defaults (2ch, mask 0x3) and the generic name `Speakers (N- USB Sound Device)`.
The old endpoint stays in the registry as *not present* (state 4), so nothing is deleted,
but the surround jack goes silent.

On 2026-10-22 the card moved from instance `7&29562685` (endpoint `{9b3aa088…}`) to
`7&20100F45` (endpoint `{d4985d3d…}`).

## Configuration to restore (copied from the old endpoint)

| Property | Value |
|---|---|
| Device format | WAVEFORMATEXTENSIBLE 6ch, 48 kHz, 16-bit PCM, mask `0x60F` (FL FR FC LFE SL SR) |
| Mix format | 6ch, 48 kHz, 32-bit float, mask `0x60F` |
| PhysicalSpeakers `{1da5d803…},3` | `0x603` (FL FR SL SR: the 4 real speakers) |
| FullRangeSpeakers `{1da5d803…},6` | `0x60F` |
| Name `{a45c254e…},2` | `Rig Speakers - Front and Rear` |

Equivalent manual path: `mmsys.cpl` → the card → **Configure → 5.1 Surround**, with center and
subwoofer unchecked, then rename the device.

## How it was restored (2026-10-22, autonomous, at the operator's request)

The endpoint's registry key was exported first (rig
`.scratch/moza-qualification/live-acceptance/speaker-layout-20261022/endpoint-d4985d3d-before.reg`).
`speaker_layout.py` in the same folder then calls the same `IPolicyConfig` API the Sound
control panel uses: `SetDeviceFormat` plus `SetPropertyValue`, run as the normal user with no
service restart. It copies the values above from the old endpoint's registry entry, and its
`read` mode is a dry run. The readback matched exactly, and PortAudio now lists
`Rig Speakers - Front and Rear (4- USB Sound Device        )` with 6 output channels.

A per-channel chirp at the PCM2902 mic (`channel-probe.json`) gave these results:

| Channel | Result |
|---|---|
| 1, 2 (front) | Audible |
| 3 (center) | Audible at about the average of the fronts; Windows redirects it with no center speaker |
| 4 (LFE) | Silent |
| 5, 6 (surround/rear) | Loudest at the driver (prominence 32–34) |

Voice belongs on channel map `[5, 6]`.

## Still true after the restore

- AC/FMOD follows the Windows layout, and no AC or CSP stereo setting exists (the 2026-10-22
  search of `audio.ini` and the CSP configs found none). With 5.1 restored, AC also writes game
  audio to SL/SR, as the July note and #815 run 02 loopback measured. Voice-only rear channels
  need a separate decision.
- AC's `audio.ini` `[SETTINGS] DRIVER_NAME` still names the old `(3- USB Sound Device)`
  endpoint. AC falls back to the default device, which is this same card.
- Endpoint configuration is per port: keep the card in this USB port, or rerun the restore
  after a move.
