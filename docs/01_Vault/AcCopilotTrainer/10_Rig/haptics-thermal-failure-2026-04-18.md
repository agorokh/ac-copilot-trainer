---
type: incident
status: resolved
created: 2026-04-18
updated: 2026-04-18
relates_to:
  - 10_Rig/_index.md
  - 10_Rig/dual-transducer-brake-body-v1.md
  - 10_Rig/single-bs-1-recovery-phase1r-v1.md
tags: [haptics, bass-shaker, thermal-failure, postmortem, lessons-learned, phase-1b]
---

# Incident — AliExpress 4 Ω / 25 W brake-pedal transducer voice-coil failure

**Date**: 2026-04-18
**Affected component**: AliExpress 2-pack "25 W" tactile transducer, one unit, bolted to MOZA SRP brake pedal chassis.
**Amp**: Douk 200 W stereo class-D (ASIN B0C7C7GD9R), left channel.
**Source profile at time of incident**: SimHub ShakeIt BSV3 `AC Copilot - Dual Transducer (BS-1 seat + brake) Phase 1B`.
**Outcome**: Voice coil shorted. Visible smoke after ~30 seconds of driving. Unit is non-functional and not safely reconnectable.
**Confirmed failure mode**: DC resistance measured at 0.6–0.7 Ω on a 200 Ω multimeter range. Healthy 4 Ω voice coil would read ~3.0–3.6 Ω DC. Turn-to-turn winding short — former overheated, enamel insulation cooked through, adjacent copper turns now fused.

## Sequence of events

1. Phase 1A (dual-transducer, mono-sum, body-tuned filter, no always-on containers) deployed earlier the same day. User drove and reported three complaints: left (pedal) channel "gives almost zero data", missing engine vibration at standstill, right (seat) channel feels good for road + gears.
2. To address the complaints, Phase 1B was designed as a "mono-plus" rebuild:
   - Raise shared LP filter 120 → 160 Hz for more small-transducer reach.
   - Boost brake-side effect gains (ABS 85 → 105, WheelsLock 70 → 100, WheelsSlip 45 → 70, TractionLoss 40 → 60).
   - **Enable `RPMContainer` at gain 25** (engine presence — always-on continuous signal).
   - **Enable `DecelerationGforceContainer` at gain 40** (continuous brake-proportional rumble — always-on).
3. Phase 1B deployed to live SimHub. User drove for ~30 seconds. Smoke reported from left transducer.
4. User powered off, disconnected, measured. Resistance 0.6–0.7 Ω confirmed short.
5. Rollback executed to Phase 1R (single-BS-1 recovery, no pedal-channel content). See `single-bs-1-recovery-phase1r-v1.md`.

## Root cause

**Continuous-signal duty cycle × peak-rated driver = thermal runaway.**

Phase 1A's effect set gave the pedal transducer only burst-only signals (ABS, WheelsLock) — effectively near-zero duty cycle during steady-state driving. That's why the user reported "almost zero data" in Phase 1A and why the unit had survived the Phase 1A session without issue.

Phase 1B added two always-on containers (`RPMContainer` and `DecelerationGforceContainer`) to a **Mono sum** bus that was routed to both transducers in parallel. This changed the pedal-channel duty cycle from ~0 % to effectively ~100 % — continuous audio-frequency signal every second the game was running. Under continuous load, the voice coil has no cooling window. The AliExpress unit's advertised "25 W" is almost certainly a peak / music-signal rating; real continuous handling for small flat-puck tactile transducers in that price class is typically 8–12 W. The Douk 200 W amp happily delivered the demanded signal power, and continuous dissipation exceeded the coil's real thermal budget. The coil former reached enamel break-down temperature, adjacent turns shorted, and the remaining partial coil section then drew excessive current and produced visible smoke.

The BS-1 on the right channel saw the same signal but survived because it is rated 50 W nominal continuous, 100 W peak — 5–10× the real continuous budget of the AliExpress unit. Same bus, same signal, wildly different thermal margin.

## Contributing factors

- **Underspecified component**: the AliExpress product page gave one "25 W" number with no distinction between RMS / continuous / peak / music-signal. No F0, no impedance curve, no thermal curve.
- **No hardware volume ceiling**: the Douk volume knob was not limited. Nothing physical prevented full 200 W output into a 4 Ω load.
- **No under-load burn-in**: Phase 1B went straight from deployment to driving. No idle test at realistic volume to observe for >1 minute.
- **No series current-limiting**: nothing on the left speaker leads to act as a sacrificial fuse.
- **Testing bias**: Phase 1A had run without issue, so Phase 1B inherited the implicit assumption that "the transducer can take SimHub content". Phase 1A's content was ~0 % duty cycle — that assumption was load-specific and did not generalise to always-on content.

## Corrective actions

### Immediate
- Left transducer unplugged from amp. Do not reconnect — 0.7 Ω near-short on a 200 W class-D amp risks amp output-stage damage and further heating of the damaged coil.
- Phase 1B rolled back. Phase 1R deployed: single BS-1 on right, no pedal-channel content, RPM kept at 25 (safe on BS-1), DecelG disabled for clean baseline.
- Amp health verified by: BS-1 on right channel still functions normally after the event → Douk's short-circuit / thermal protection behaved as designed.

### Planned (Phase 2A rebuild, pending Dayton TT25)
- **Replace transducer with Dayton TT25-8 or TT25-16** (~$25–30 from Parts Express/Amazon). True 25 W continuous, 19 mm voice coil, published spec sheet. De facto standard for sim pedal transducers.
- **Hardware volume ceiling**: mark Douk volume knob at ~40 % max with physical tape or nail polish. Backstops both channels.
- **Software rule**: **no more than one always-on container on any transducer whose continuous rating isn't documented**. On the pedal channel specifically, treat always-on content as opt-in per component.
- **Burn-in protocol**: after any profile that adds always-on content, test under real load for ≥1 minute before walking away. Feel the transducer body by hand — hot to touch → back off.
- **Optional belt-and-suspenders**: 4 Ω 5 W wirewound resistor in series on the pedal leads as sacrificial fuse. If the coil ever shorts again the resistor cooks first and the amp sees 4 Ω instead of 0. ~$2 from Digi-Key.

## Durable lessons (read before every haptic profile change)

1. **"25 W" on AliExpress transducers ≠ continuous rating.** Assume peak/music-signal advertising. Real continuous handling is typically a fraction.
2. **Duty cycle is more dangerous than peak amplitude.** Burst-only effects (ABS, Lock, Impact) have built-in thermal idle. Always-on effects (RPM, DecelG, LateralG, RoadTexture at high gain) stack into continuous dissipation.
3. **Mono sum routes every enabled effect to every transducer.** When there are N transducers with different thermal budgets on one mono bus, the **smallest** transducer sets the ceiling, not the largest.
4. **Change one variable at a time and burn-in for at least a minute.** Phase 1B changed six things simultaneously. Any single one might have been fine; stacked, they exceeded a thermal threshold nobody had measured.
5. **Hardware protection is cheap and forgiving.** Volume-knob ceiling, series resistor, and a physical short-circuit fuse collectively cost under $5 and buy huge safety margin against software mistakes.

## Files / artefacts

- Pre-incident profile (Phase 1A): `ShakeITBassShakersSettingsV2.backup.20260418-194211.json` (42 888 bytes)
- Incident-triggering profile (Phase 1B): `ShakeITBassShakersSettingsV2.backup.20260418-202120-pre1R.json` (41 548 bytes — this was the live state when smoke appeared)
- Recovery profile (Phase 1R, live): `ShakeITBassShakersSettingsV2.json` (41 542 bytes)
- Build scripts: `_workscratch/build_phase1b.py`, `_workscratch/build_phase1r.py`

## Related nodes

- `dual-transducer-brake-body-v1.md` — superseded architecture node; describes the target state Phase 1B was trying to achieve.
- `single-bs-1-recovery-phase1r-v1.md` — current live state after rollback.
- `srp-brake-bracket-v1.md` — the bracket (undamaged, reusable for the TT25 replacement).
