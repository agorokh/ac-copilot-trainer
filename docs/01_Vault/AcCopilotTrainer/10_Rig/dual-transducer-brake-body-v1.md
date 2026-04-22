---
type: state
status: superseded
superseded_by: single-bs-1-recovery-phase1r-v1.md
created: 2026-04-18
updated: 2026-04-18
supersedes: bass-shaker-bs1-balanced-v1.md
relates_to:
  - 10_Rig/_index.md
  - 10_Rig/single-bs-1-recovery-phase1r-v1.md
  - 10_Rig/srp-brake-bracket-v1.md
  - 10_Rig/haptics-thermal-failure-2026-04-18.md
  - 10_Rig/bass-shaker-bs1-balanced-v1.md
tags: [haptics, bass-shaker, simhub, bsv3, moza-srp, dual-transducer, superseded]
---

> **Superseded 2026-04-18 20:21** by [`single-bs-1-recovery-phase1r-v1.md`](single-bs-1-recovery-phase1r-v1.md).
>
> The Phase 1B evolution of this architecture destroyed the AliExpress 4 Ω / 25 W brake-pedal transducer through continuous-signal thermal failure (30 seconds of always-on RPMContainer + DecelerationGforceContainer content). Full write-up: [`haptics-thermal-failure-2026-04-18.md`](haptics-thermal-failure-2026-04-18.md).
>
> The dual-transducer target state remains valid — it is simply on hold until a Dayton TT25 (real 25 W continuous) replacement arrives. Phase 2A will resurrect this architecture node (or fork a new one) with safeguards: hardware volume ceiling on Douk knob, optional series fuse resistor, and a rule against more than one always-on container per under-rated transducer.

# Dual-transducer haptic architecture — body + brake, v1

Target haptic stack: Douk BS-1 on seat (R) + AliExpress 4 Ω 25 W on SRP brake (L). This node documented Phase 1A (mono-sum, no always-on) successfully, and Phase 1B's mono-plus rebuild (raised LP, boosted brake events, always-on RPM + DecelG) which ran for 30 seconds before the pedal transducer caught fire.

**The architecture idea is sound**; the driver choice was not. A properly continuous-rated transducer (Dayton TT25 or equivalent) would have survived Phase 1B. See recovery node and incident write-up for the forward path.

## Hardware inventory (Phase 1A / 1B target state)

| Role | Part | Spec | Location |
|------|------|------|----------|
| Body shaker | Douk Audio BS-1 | 50 W nom / 100 W peak, 6 Ω, F0 30 Hz, 20–200 Hz | Bolted under bucket seat shell |
| Pedal transducer (brake) | AliExpress 2-pack tactile transducer | "25 W", 4 Ω per unit (**peak rating, not continuous — see incident node**) | SRP brake pedal chassis via printed bracket |
| Pedal transducer (throttle) | NOT YET OWNED | — | Future — SRP throttle pedal, mirrored bracket |
| Amp (primary) | Douk 200 W stereo class-D (ASIN B0C7C7GD9R) | ~200 W, stereo, 4–8 Ω/ch | Fed from PCM2902 USB DAC |
| Amp (reserve) | AliExpress 50 W 2.0 BT 5.0 class-D | 2×25 W | Reserved for Phase 2 |
| USB DAC | PCM2902 (`VID_08BB&PID_2902`) | UAC 1.0 stereo | Name at time of writing: "Speakers (4- USB PnP Sound Device)" (Windows has since renumbered to "8-" — see Phase 1R node) |
| Pedal set | MOZA SRP with load cell brake | Upgraded from SRP-lite | Recent hardware change |

## Signal chain (as designed)

```
SimHub ShakeIt BSV3
        │
        ▼   (stereo OR mono, depending on phase)
PCM2902 USB DAC
        │
        ▼
Douk 200 W stereo class-D amp
        │
   ┌────┴────┐
 LEFT       RIGHT
   │         │
 SRP brake  BS-1 under
 transducer seat
```

## SimHub profile (Phase 1A reference — pre-failure)

Snapshot values from when this architecture was live. Kept as a historical reference only — the live profile now is Phase 1R (`single-bs-1-recovery-phase1r-v1.md`).

- Active profile: `AC Copilot - Dual Transducer (BS-1 seat + brake) Phase 1A`
- ProfileId: `f2c4bd6a-6b1a-4928-ba35-32ad42d04800`
- OutputManager `GlobalGain` = 75
- Channel `HighPassFilter` = 25 Hz, `LowPassFilter` = 120 Hz
- Profile `GlobalGain` = 60, `OutputMode` = 1 (Mono sum)

Enabled effects (13) in Phase 1A, gains as follows:

| Effect | Gain | Tier | Notes |
|--------|------|------|-------|
| ABSActiveEffectContainer | 85 | 1 (brake) | |
| WheelsLockContainer | 70 | 1 (brake) | |
| WheelsSlipContainer | 45 | 2 (brake) | |
| TractionLossContainer | 40 | 2 (brake) | |
| GearEffectContainer | 95 | 1 (body) | |
| WheelsVibrationContainer | 80 | 1 (body) | Curbs |
| RoadTextureContainer | 35 | 1 (body) | |
| ImpactEffectContainer | 100 | 1 (body) | |
| WheelsImpactContainer | 85 | 1 (body) | |
| JumpContainer | 95 | 1 (body) | |
| GearGrindingContainer | 55 | 2 (body) | |
| GearMissedContainer | 60 | 2 (body) | |
| TouchdownEffectContainer | 90 | 2 (body) | |

Phase 1B deltas (which triggered the failure, preserved here as a warning):

- Channel `LowPassFilter` 120 → 160 Hz
- Profile `GlobalGain` 60 → 65
- ABS 85 → 105, WheelsLock 70 → 100, WheelsSlip 45 → 70, TractionLoss 40 → 60
- **Newly enabled: `RPMContainer` @ 25** (always-on)
- **Newly enabled: `DecelerationGforceContainer` @ 40** (always-on)

The two newly-enabled always-on containers in combination with the mono-sum bus routing signal to both transducers and the under-rated pedal driver are what killed the pedal unit.

## Original phase roadmap (for historical context)

- Phase 1A: mono parallel, burst-only content. Worked; user reported pedal "gives almost zero data".
- Phase 1B: mono-plus rebuild addressing Phase 1A feedback. **Failed destructively.**
- Phase 1C: true stereo split via SimHub UI to learn `EffectToChannelsMapStore` format.
- Phase 2: throttle transducer + move pedal audio to reserve 50 W BT amp.

## Forward pointer

Current live state: `single-bs-1-recovery-phase1r-v1.md`.
Incident analysis: `haptics-thermal-failure-2026-04-18.md`.
Rebuild target (Phase 2A): will either revive this node or fork a new `dual-transducer-brake-body-v2.md` once the Dayton TT25 is installed with proper protections in place.
