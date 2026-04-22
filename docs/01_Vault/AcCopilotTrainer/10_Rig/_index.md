---
type: index
status: active
created: 2026-04-18
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - 00_Graph_Schema.md
---

# 10_Rig — physical rig configuration

Knowledge nodes for the physical simulator rig: seat / shakers / motors / wheelbase / pedals / audio chain. Separate from the AC Copilot Trainer app — this vault holds the rig config because the trainer app reads telemetry from the same simulator and the whole stack is the source of truth for the simracing copilot.

## Nodes

### Active state

- [esp32-jc3248w535-screen-v1.md](esp32-jc3248w535-screen-v1.md) — **Active (Phase 1 SHIPPED 2026-04-21).** Guition JC3248W535 ESP32-S3 3.5" touchscreen on the rig as a keyboard-free control panel. Firmware lives at `firmware/screen/` (PlatformIO + Arduino_GFX 1.4.7 — not LovyanGFX; LVGL deferred to Phase 2). Board joins `AHOME5G`, runs stable WS retry loop; immediate unblock is sidecar external-bind + token in gh [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81).
- [single-bs-1-recovery-phase1r-v1.md](single-bs-1-recovery-phase1r-v1.md) — **Active.** Single-transducer recovery profile (Phase 1R). BS-1 under seat on right channel only, mono-sum, RPMContainer @ 25 for engine thrum. Pedal-side mount empty pending Dayton TT25 replacement. Audio device rebound to "Speakers (8- USB PnP Sound Device)" after Windows renumbered the PCM2902 endpoint on replug.
- [srp-brake-bracket-v1.md](srp-brake-bracket-v1.md) — Bolt-on 3D-printed bracket to mount the brake-pedal transducer to the MOZA SRP chassis. Currently sits empty; reusable when TT25 arrives. Parametric OpenSCAD + Python/trimesh regen.

### Incident write-up

- [haptics-thermal-failure-2026-04-18.md](haptics-thermal-failure-2026-04-18.md) — **Resolved.** Voice-coil thermal failure of the AliExpress 4 Ω / 25 W brake-pedal transducer 30 seconds into Phase 1B. Root cause: always-on containers (`RPMContainer` + `DecelerationGforceContainer`) on a peak-rated driver with no continuous-power spec. Includes durable lessons before any future haptic profile change.

### Superseded (kept for history)

- [dual-transducer-brake-body-v1.md](dual-transducer-brake-body-v1.md) — Superseded 2026-04-18 by Phase 1R after the pedal transducer destroyed itself in Phase 1B. Documented the dual-transducer architecture target; will be reincarnated as a Phase 2A node once the TT25 is mounted.
- [bass-shaker-bs1-balanced-v1.md](bass-shaker-bs1-balanced-v1.md) — Original single-shaker config. Superseded by the dual-transducer node in the morning, then circumstantially relevant again after the Phase 1B failure but with key differences (RPM enabled, audio device renumbered). Phase 1R is its conceptual successor.

## Related system

- See `00_System/Architecture Invariants.md` for the trainer app architecture.
- Rig-specific invariants should be added under `00_System/invariants/` when they solidify.
