---
type: state
status: active
created: 2026-04-26
updated: 2026-04-26
supersedes: single-bs-1-recovery-phase1r-v1.md
relates_to:
  - 10_Rig/_index.md
  - 10_Rig/single-bs-1-recovery-phase1r-v1.md
  - 10_Rig/dual-transducer-brake-body-v1.md
  - 10_Rig/srp-brake-bracket-v1.md
  - 10_Rig/haptics-thermal-failure-2026-04-18.md
tags: [haptics, bass-shaker, simhub, bsv3, dual-transducer, tt25, phase-2a, stereo-routing]
---

# Dual-transducer Phase 2A — BS-1 (seat) + Dayton TT25 (brake pedal)

Active haptic stack as of **2026-04-26 21:56**. Replaces single-BS-1 Phase 1R after the user installed a Dayton TT25 on the SRP brake bracket as the proper replacement for the AliExpress unit that died in Phase 1B (see `haptics-thermal-failure-2026-04-18.md`).

**Why this works where Phase 1B didn't**: TT25 is a purpose-built sim-racing tactile transducer with an honest 25 W continuous rating (not peak/music marketing). Plus we now have per-effect channel routing via SimHub's `EffectToChannelsMapStore` matrix, so ambient content (RPM, RoadTexture) stays on the seat-side BS-1 while the pedal-side TT25 only sees burst-event effects.

## Hardware inventory

| Role | Part | Spec | Location |
|------|------|------|----------|
| Body shaker | Douk Audio BS-1 | 50 W nom / 100 W peak, 6 Ω, F0 30 Hz, 20–200 Hz | Bolted under bucket seat shell, wired to amp **RIGHT** (Ch2) |
| Pedal transducer | **Dayton Audio TT25** | 25 W continuous (honest), 19 mm voice coil | Bolted to MOZA SRP brake pedal via printed bracket, wired to amp **LEFT** (Ch1) |
| Amp | Douk 200 W stereo class-D (ASIN B0C7C7GD9R) | ~200 W, 4–8 Ω/ch, both channels in use | Under rig; physical knob ceiling at ~70 % |
| USB DAC | PCM2902 (`VID_08BB&PID_2902`) | UAC 1.0 stereo | Currently `Speakers (7- USB PnP Sound Device)` — Windows has renumbered prefix several times across replug events; OutputId GUID is the stable identifier |
| Pedal set | MOZA SRP with load cell brake | — | bracket from `srp-brake-bracket-v1.md`, reused from the AliExpress mount |

## Signal chain

```
SimHub ShakeIt BSV3 (Phase 2A profile, OutputMode=1 mono-sum + per-effect matrix routing)
        │
        ▼
PCM2902 USB DAC (Speakers (7- USB PnP Sound Device))
        │
        ▼
Douk 200 W stereo class-D amp (~70 % knob)
        │
   ┌────┴────┐
 LEFT       RIGHT
 Ch1        Ch2
   │         │
   ▼         ▼
TT25       BS-1
brake      under
pedal      bucket seat
```

## SimHub profile

- **Active profile**: `AC Copilot - Dual Transducer (BS-1 seat + TT25 pedal) Phase 2A`
- **ProfileId**: `f2c4bd6a-6b1a-4928-ba35-32ad42d04800` (renamed Phase 1A → 1B → 1R → 2A)
- **File**: `C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json` (50 827 bytes)
- **Pre-deploy backup**: `ShakeITBassShakersSettingsV2.backup.20260426-215503-pre-phase2a-rename.json` (50 819 bytes)
- **Generators**: `tools\patch_phase2a_enable_stereo.py`, `tools\patch_phase2a_rename_and_tier2.py`

### Channel & profile settings

| Setting | Value | Notes |
|---|---|---|
| `ChannelsSettingsV3[0].Name` | `Speakers (7- USB PnP Sound Device)` | Latest after Windows renumbered |
| `ChannelsSettingsV3[0].OutputId` | `{0.0.0.00000000}.{c3969864-70a5-4354-8804-b23cc46c6eab}` | Stable identifier |
| `HighPassFilter` / `LowPassFilter` | 25 Hz / 120 Hz | Channel-level, BS-1 body band — TT25 happy in this band too |
| `OutputManager.GlobalGain` | 75 | Unchanged from Phase 1T |
| Profile `GlobalGain` | 84.67 | User UI adjustment |
| Profile `OutputMode` | 1 (Mono sum) | Matrix overrides apply per-effect even in Mono mode |
| Stereo `MapsStore` | `0;1;80;Left;;\|1;1;100;Right;;\|...` | TT25 channel biased to 80 vs BS-1 at 100 (power balance) |

### Enabled effects (10) and per-effect channel routing

Channel naming: **Ch1 = LEFT = TT25 pedal**, **Ch2 = RIGHT = BS-1 seat**.

| Effect | Gain | Routing | Aggregation | Tier / role |
|---|---|---|---|---|
| ABSActiveEffectContainer | 100 | Ch1 only | All | Tier 1 — pedal-authentic ABS pulse |
| WheelsLockContainer | 50 | FrontLeft→Ch1, FrontRight→Ch2 | per-wheel split (default) | Tier 1 — non-ABS lock-up |
| WheelsImpactContainer (curbs) | 100 | Ch1 @ 60 % + Ch2 @ 100 % | All | Tier 1 — curbs felt at both pedal (60%) and seat (full) |
| ImpactEffectContainer (collisions) | 100 | Ch1 + Ch2 | All | both — collisions felt everywhere |
| GearMissedContainer | 61 | Ch1 + Ch2 | All | both — fumbled-shift punch |
| GearEffectContainer | 94 | Ch2 only | All | seat — engaged shift thump |
| RPMContainer | 22 | Ch2 only | All | seat — engine thrum |
| RoadTextureContainer | 10 | Ch2 only | All | seat — ambient road feel |
| **WheelsSlipContainer** (NEW Tier 2) | 70 | FrontLeft→Ch1 @ 96, FrontRight→Ch2 | per-wheel | grip warning |
| **TractionLossContainer** (NEW Tier 2) | 60 | Left→Ch1, Right→Ch2 | L/R split | whole-car slide |

### Disabled (kept off)

`WheelsVibrationContainer`, `DecelerationGforceContainer` (the original killer effect from Phase 1B fire — TT25 can take it but holding for now), `TouchdownEffectContainer`, `JumpContainer`, `FlightsWingsLoadContainer`, `RPMSoundEffectContainer`, `WheelsSpinAndLockContainer`, `TCActiveEffectContainer`, `LateralGforceContainer`, `AccelerationGforceContainer`, `SpeedContainer`, `LocalizedSpeedContainer`, `WheelsRumbleContainer`, `CustomEffectContainer`, `GearGrindingContainer`.

## EffectToChannelsMapStore — format documented 2026-04-26

JSON path: `OutputManager.ChannelsSettingsV3[0].EffectToChannelsMapStore.{ContainerType}.{Aggregation}.MapsStore`

String format: `idx;enabled;gain;name;;|idx;enabled;gain;name;;|...` where idx 0 = Left = Ch1, idx 1 = Right = Ch2, idx 2–7 = unused (only stereo wired).

Aggregation values seen: `All`, `Front`, `Rear`, `Left`, `Right`, `FrontLeft`, `FrontRight`, `RearLeft`, `RearRight`. Matches each container's `AggregationMode`.

**Now automatable from JSON.** Future Phase 2B+ tweaks can be patched directly without UI walkthrough.

## Operational rules carried forward

1. **Always close SimHub before JSON edits** — `feedback_simhub_patch_workflow.md`. SimHub caches profile state and overwrites disk on startup/save.
2. **Effects need both routing AND IsEnabled=true.** Setting matrix routing alone does not make an effect fire. Effect-level IsEnabled toggle in Effects Profile tab is the master switch.
3. **OutputMode=1 (Mono sum) does not disable matrix overrides.** Per-effect routing applies in mono mode too. We tried OutputMode=0 (true stereo) but SimHub round-tripped to 1; the routing works fine either way.
4. **Power budget on TT25**: 25 W honest continuous. Current load (burst events + curbs at 60 %) averages well under 5 W. ~5× headroom remaining. Verified cool to touch after 2 laps post-deploy.
5. **Hardware ceiling on Douk knob**: ~70 % is current operating; ~80 % is the BS-1 thermal ceiling (also fine for TT25). Don't push past 80 %.

## Verification procedure

After any edit, sanity-check live state:

```powershell
$j = Get-Content -LiteralPath 'C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json' -Raw | ConvertFrom-Json
$ch = $j.OutputManager.ChannelsSettingsV3[0]
"$($ch.Name) | HP $($ch.HighPassFilter) LP $($ch.LowPassFilter) | LeftMaps $($ch.GlobalChannelsSettings.Stereo.MapsStore.Substring(0, 30))"
$p = $j.Profiles | Where-Object { $_.ProfileId -eq $j.activeProfileId }
"Active: $($p.Name) | enabled=$(($p.EffectsContainers | ? IsEnabled).Count)"
```

Expected (Phase 2A live):
```
Speakers (7- USB PnP Sound Device) | HP 25 LP 120 | LeftMaps 0;1;80;Left;;|1;1;100;Right;
Active: AC Copilot - Dual Transducer (BS-1 seat + TT25 pedal) Phase 2A | enabled=10
```

In-car smoke test:
1. Engine on, parking brake up → low thrum in **seat only** (RPM @ 22 → BS-1).
2. Drive curb → punch in **both** seat (full) and pedal (60 %).
3. Hard brake to lock → pedal-side ABS pulse (TT25), seat free of brake noise.
4. Push for grip → mild buzz on appropriate side: front-left wheel slipping → TT25; front-right slipping → BS-1.
5. Crash test → both transducers thump simultaneously.

## Phase roadmap

- Phase 1A → 1B → 1R: history; see superseded nodes.
- Phase 1S → 1T: signal-to-noise tuning era on single BS-1.
- **Phase 2A (CURRENT)**: dual-transducer, per-effect routing, 10 effects.
- Phase 2B (next experiment): consider DecelerationGforceContainer @ low gain on Ch1 for brake-proportional pedal rumble. Burn-in for ≥ 1 minute under load before walking away. TT25's continuous budget supports it; safety policy still says never add an always-on effect without observation.
- Phase 2C: tune Wheels Slip / Traction Loss split — current per-wheel/L-R routing maps physical wheel positions to physical transducers, which is "correct stereo" for a 4-shaker setup but not ideal for a pedal-vs-seat 2-transducer rig. Consider routing all slip/loss events to Ch1 (pedal) for cleaner brake-family clustering, like ABS.

## Rollback

```powershell
Stop-Process -Name SimHubWPF -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Copy-Item "C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.backup.20260426-215503-pre-phase2a-rename.json" `
          "C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json" -Force
Start-Process "C:\Program Files (x86)\SimHub\SimHubWPF.exe"
```

That reverts to the pre-rename / pre-Tier-2 state (Phase 2A routing already applied via UI but profile name still "Phase 1R" and Wheels Slip / Traction Loss still disabled).

## Change log

- **2026-04-26 21:55** — Stopped SimHub, backed up pre-rename state.
- **2026-04-26 21:56** — Patched JSON: profile rename + IsEnabled=true on WheelsSlipContainer + TractionLossContainer.
- **2026-04-26 21:56:52** — Restarted SimHub. File round-trip stable at 50 827 bytes.

## Related nodes

- `single-bs-1-recovery-phase1r-v1.md` — superseded predecessor (single transducer state).
- `dual-transducer-brake-body-v1.md` — earlier dual-transducer architecture target (with the original AliExpress unit). Architecture intent matches; transducer choice was the failure point.
- `haptics-thermal-failure-2026-04-18.md` — incident write-up; the durable lessons applied here.
- `srp-brake-bracket-v1.md` — bracket spec, reused from AliExpress mount for TT25.
