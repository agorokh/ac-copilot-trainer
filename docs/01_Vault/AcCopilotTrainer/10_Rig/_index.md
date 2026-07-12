---
type: index
status: active
created: 2026-04-18
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - 00_Graph_Schema.md
---

# 10_Rig — physical rig configuration

Knowledge nodes for the physical simulator rig: seat / shakers / motors / wheelbase / pedals / audio chain / ESP32 touchscreen dashboard. Separate from the AC Copilot Trainer app code — this vault holds the rig config because the trainer reads telemetry from the same simulator and the whole stack is the source of truth for the simracing copilot.

## Nodes

### Epic

- [physical-rig-integration-epic-59.md](physical-rig-integration-epic-59.md) — **OPEN.** Umbrella issue #59 for the full hardware peripheral roadmap: Arduino UNO (fan / OLED / seat vibration motors / pedal haptics) + ESP32 touch dashboard + Dayton BST-1 shaker + salvaged Xbox controller motors. Pin map + architecture diagram + BOM + thermal lessons + per-phase completion status.

### Active state

- [esp32-jc3248w535-screen-v1.md](esp32-jc3248w535-screen-v1.md) — **Active. PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) MERGED 2026-04-22.** Guition JC3248W535 ESP32-S3 3.5" touchscreen. Firmware at `firmware/screen/` (Arduino_GFX 1.4.7 + ArduinoWebsockets). End-to-end working over Windows Mobile Hotspot: device authenticates with `X-AC-Copilot-Token`, emits `{v:1,type:"action",name:"toggleFocusPractice"}` every 10 s. Phase-2 LVGL + touch reader + Figma UI is next.
- [single-bs-1-recovery-phase1r-v1.md](single-bs-1-recovery-phase1r-v1.md) — **Active.** Single-transducer recovery profile (Phase 1R). BS-1 under seat on right channel only, mono-sum, `RPMContainer @ 25` for engine thrum. Pedal-side mount empty pending Dayton TT25 replacement.
- [wheel-per-car-rotation-ffb-2026-07-12.md](wheel-per-car-rotation-ffb-2026-07-12.md) — **Active. 2026-07-12.** MOZA R3 + KS wheel. Per-car steering rotation fixed (base 900→1080, AC `LOCK=1080`, "auto-adjust scale to match car's steer lock" ON). Per-car FFB gain already built-in via `cfg/user_ff.ini` (partially hand-tuned); feel is automatic from physics. Candidate: harness-driven `finalFF` clipping calibration per car.
- [audio-5.1-positional-engine-2026-07-12.md](audio-5.1-positional-engine-2026-07-12.md) — **Active. LIVE-VERIFIED 2026-07-12.** Added rear speaker pair on a USB C-Media CM6206 5.1 card; fixed "only front playing" (endpoint was Stereo → set Windows to **5.1 Surround**, now 6ch `0x60F`). AC/FMOD inherits the OS layout (no in-AC toggle). Harness drive + WASAPI-loopback per-channel probe confirms rear-engine 911 (surround/front 0.959) vs front-engine M3 GT2 (0.803) — layout-dependent localization, realistic ~1.5 dB shift.
- [srp-brake-bracket-v1.md](srp-brake-bracket-v1.md) — 3D-printed bolt-on bracket for the brake-pedal transducer on MOZA SRP. Currently empty; reusable when TT25 arrives.

### Incident write-up

- [haptics-thermal-failure-2026-04-18.md](haptics-thermal-failure-2026-04-18.md) — **Resolved.** Voice-coil thermal failure of the AliExpress 4 Ω / 25 W brake-pedal transducer 30 s into Phase 1B. Root cause: always-on containers on a peak-rated driver.

### Superseded (kept for history)

- [dual-transducer-brake-body-v1.md](dual-transducer-brake-body-v1.md) — Superseded 2026-04-18 by Phase 1R after the pedal transducer destroyed itself. Will be reincarnated as Phase 2A when the TT25 is mounted.
- [bass-shaker-bs1-balanced-v1.md](bass-shaker-bs1-balanced-v1.md) — Original single-shaker config. Superseded by the dual-transducer node, then conceptually succeeded by Phase 1R.

## Related system

- [physical-rig-integration-epic-59.md](physical-rig-integration-epic-59.md) for the full hardware roadmap
- [`00_System/glossary/rig-network.md`](../00_System/glossary/rig-network.md) for all addresses / SSIDs / tokens
- [`01_Decisions/dashboard-visual-design-figma.md`](../01_Decisions/dashboard-visual-design-figma.md) for the Phase-2 UI design source
- See `00_System/Architecture Invariants.md` for the trainer app architecture
