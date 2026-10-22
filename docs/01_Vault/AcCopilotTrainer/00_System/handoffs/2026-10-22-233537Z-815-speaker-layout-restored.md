---
type: handoff
status: active
created: 2026-10-22
updated: 2026-10-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/10_Rig/speaker-endpoint-replug-restore-2026-10-22.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-22-223617Z-post-merge-pr925-815-monotonic.md
---

# #815: rig 5.1 speaker layout restored after a USB replug

At the operator's request, the CM6206 speaker endpoint was restored. The card had moved to a
new USB instance and Windows created a stereo endpoint. The restore set 6ch 0x60F, physical
speakers 0x603 and the name `Rig Speakers - Front and Rear` through `IPolicyConfig`, copied
from the old endpoint's registry entry. The before state was exported first. Readback matched,
PortAudio shows 6 channels, and the per-channel mic probe confirms front L/R, redirected
center, silent LFE, and loud rear L/R. Details and the method:
[speaker-endpoint-replug-restore](../../10_Rig/speaker-endpoint-replug-restore-2026-10-22.md).

## Open

- **Voice-only rear speakers are not established.** No AC or CSP stereo setting exists, and
  AC/FMOD follows the 5.1 OS layout, so game audio will also reach SL/SR. The operator must
  choose a separation (or accept shared rears) before the next bounded run, which pins voice
  to channel map `[5, 6]`.
- The restore script is rig-local scratch. A canonical tool or a Game Point preflight that
  flags a 2-channel voice endpoint would stop this recurring; that is not built.
- AC `audio.ini` `DRIVER_NAME` still names the old `(3- …)` endpoint (falls back to default).

#815 stays open; its two live clauses are unchanged. Fan-out: none created.
