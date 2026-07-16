---
type: investigation
status: active
created: 2026-07-16
updated: 2026-07-16
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/619
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-602-portaudio-fixed-layout-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-596-pit-stall-sim-death-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-531-parte-cues-fuel-2026-07-16.md
---

# Rig unplayable: voice-armed sidecar wedges AC physics at go-live (#619)

Operator report 2026-07-16 ~10:00: AC loads, renders one frame, world never moves; wheel/pedals
"feel" alive; tablet blank. **Not** focus-pause, **not** the tablet dashboard, **not** content.

## Ground truth

Shared-memory probe (`.scratch/freeze_probe.py`): `acpmf_physics.packetId` **stops** while
`acpmf_graphics.status` stays `AC_LIVE`. Three consecutive harness launches wedged at packetId
**7507 / 7512 / 7528** — a fixed go-live init point, not a random flake. Operator session wedged
at 9511. FMOD errors at load in `log.txt`. No crash dumps (clean hang).

## Discriminator

Kill the **voice-armed** sidecar (rtmixer six-channel pinned WASAPI on the USB Sound Device —
the #602/PR #606 fixed-layout negotiation, live on the rig since the previous night) → bare
no-voice sidecar → **first clean launch of the day**: full lap 133.755 s, RENDERING verdict,
zero retries. Every wedge that day ran WITH the voice stream held.

## Durable lessons

- **"Frozen picture + live FFB" ≠ render/focus problem** — read `acpmf` first: physics
  STAGNANT + status LIVE is the sim-death/wedge class. The probe script is reusable.
- A wedge at the **same packetId across launches** pinpoints a fixed init-sequence blocking
  call — that determinism is diagnostic gold, not noise.
- The worsening #596 launch flake (2/6 → 2/3 → ~100%) tracked the **voice/audio work
  timeline**, not the dashboard work. Reconcile flake trends against WHAT ELSE runs on the box.
- FMOD/WASAPI endpoint contention can stall AC's **physics** thread, not just audio.
- MOZA/SimHub reading hardware directly makes inputs "feel alive" while the sim is dead —
  do not trust pedal feel as a sim-liveness signal.

## Rig state left behind (mitigation)

- :8765 sidecar runs **WITHOUT voice** (tablet OK; in-ear voice coaching OFF).
- **Do not re-arm voice on the rig until #619 is root-caused** — the Game Point launcher's
  standing flags would re-enable it on next start.
- Evidence kept: `.scratch/acs_wedged_2564.dmp` (4.2 GB full dump of a wedged instance —
  thread-stack analysis pending), harness PASS bundle `20260716T175827Z_*`.

## Follow-ups (tracked in #619)

Dump stack analysis → name the blocking module; voice engine to shared-mode/lazy/AC-aware
stream lifecycle; harness preflight canary for held output streams; Lua `telemetry_tick`
should gate on `externalHelloAcked` (reconnect-storm spam, minor, noted in #619).
