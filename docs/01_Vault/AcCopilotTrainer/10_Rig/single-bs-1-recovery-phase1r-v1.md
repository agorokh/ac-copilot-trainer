---
type: state
status: active
created: 2026-04-18
updated: 2026-04-18
supersedes: dual-transducer-brake-body-v1.md
relates_to:
  - 10_Rig/_index.md
  - 10_Rig/dual-transducer-brake-body-v1.md
  - 10_Rig/srp-brake-bracket-v1.md
  - 10_Rig/haptics-thermal-failure-2026-04-18.md
tags: [haptics, bass-shaker, simhub, bsv3, moza-srp, single-transducer, recovery, phase-1r]
---

# Single BS-1 recovery profile — Phase 1R

Active haptic state as of **2026-04-18 20:21**. Replaces `dual-transducer-brake-body-v1.md` because the AliExpress 4 Ω / 25 W pedal transducer suffered a voice-coil thermal failure 30 seconds into Phase 1B operation (see `haptics-thermal-failure-2026-04-18.md`). Pedal-side mount is physically empty and amp left channel is disconnected until a Dayton TT25 arrives.

## Hardware state

| Role | Part | Spec | Location | Status |
|------|------|------|----------|--------|
| Body shaker | Douk Audio BS-1 | 50 W nom / 100 W peak, 6 Ω, F0 30 Hz, 20–200 Hz | Bolted under bucket seat shell, wired to amp RIGHT channel | Live |
| Pedal transducer (brake) | — | — | SRP brake bracket is empty | **Awaiting Dayton TT25 replacement** |
| Amp (primary) | Douk 200 W stereo class-D (ASIN B0C7C7GD9R) | ~200 W, stereo, 4–8 Ω/ch | Under rig | Live; LEFT channel has nothing connected (no phantom load) |
| Amp (reserve) | AliExpress 50 W 2.0 BT 5.0 class-D | 2×25 W | In box | Reserve; not in use |
| USB DAC | PCM2902 (`VID_08BB&PID_2902`) | UAC 1.0 stereo | "Speakers (8- USB PnP Sound Device)" — **Windows renumbered from 6- to 8- after replug** | Live |

## Signal chain

```
SimHub ShakeIt BSV3 (Phase 1R profile, OutputMode=1 Mono sum)
        │
        ▼
PCM2902 USB DAC  (Speakers (8- USB PnP Sound Device))
        │
        ▼
Douk 200 W stereo class-D amp
        │
   ┌────┴────┐
 LEFT       RIGHT
  ∅          │
  (empty)   BS-1 under seat
```

Mono sum means every enabled effect is mixed into a single bus and routed to the right channel — so RPM, road texture, gear, impacts, ABS, lock — **all felt through the bucket seat via the BS-1**. The SimHub `GlobalChannelsSettings.Mono.MapsStore` left-channel entry is set to gain 0 and enabled=0 so SimHub does not internally address a dead output.

## SimHub profile

- **Active profile**: `AC Copilot - Single BS-1 Right (Recovery) Phase 1R`
- **ProfileId**: `f2c4bd6a-6b1a-4928-ba35-32ad42d04800` (same slot, renamed through 1A → 1B → 1R)
- **File**: `C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json` (41 542 bytes)
- **Generator**: `C:\Users\arsen\Projects\AC-copilot\AC Copilot\_workscratch\build_phase1r.py`
- **Pre-deploy backup**: `ShakeITBassShakersSettingsV2.backup.20260418-202120-pre1R.json` (41 548 bytes, = Phase 1B state)

### Channel and profile settings

| Setting | Value | Notes |
|---|---|---|
| `ChannelsSettingsV3[0].Name` | `Speakers (8- USB PnP Sound Device)` | Rebind required after user replugged USB DAC |
| `ChannelsSettingsV3[0].OutputId` | `{0.0.0.00000000}.{EFC1F598-227E-4C1E-B88D-7DC858020F06}` | New endpoint GUID |
| `ChannelsSettingsV3[0].HardwareID2` | `{1}.USB\VID_08BB&PID_2902&MI_00\7&13950D66&0&0000` | USB path suffix also changed |
| `UseHighPassFilter` / `HighPassFilter` | true / **25 Hz** | Below BS-1 F0 → filter absorbs excess heat |
| `UseLowPassFilter` / `LowPassFilter` | true / **120 Hz** | Reverted from 1B's 160 Hz — BS-1 body band |
| `OutputManager.GlobalGain` | 75 | Unchanged |
| Profile `GlobalGain` | **60** | Reverted from 1B's 65 |
| Profile `OutputMode` | 1 (Mono sum) | Unchanged |
| `GlobalChannelsSettings.Mono.MapsStore` | `0;0;0;Left (mono);;|1;1;99;Right (mono);;|...` | Dead left channel silenced |

### Enabled effects (12)

**Body / road feel (9)** — Phase 1A gains:

| Effect | Gain | Purpose |
|---|---|---|
| `GearEffectContainer` | 95 | Engaged shift thump |
| `WheelsVibrationContainer` | 80 | Curbs, main character |
| `RoadTextureContainer` | 35 | Always-on tarmac feel |
| `ImpactEffectContainer` | 100 | Collisions |
| `WheelsImpactContainer` | 85 | Kerb hits, potholes |
| `JumpContainer` | 95 | Airborne pop |
| `TouchdownEffectContainer` | 90 | Landing after Jump |
| `GearGrindingContainer` | 55 | Fumbled shifts |
| `GearMissedContainer` | 60 | Missed-shift punch |

**Brake events (2)** — Phase 1A gains (reverted from 1B boosts):

| Effect | Gain | 1B value | Purpose |
|---|---|---|---|
| `ABSActiveEffectContainer` | 85 | 105 | ABS cycling pulse through seat |
| `WheelsLockContainer` | 70 | 100 | Lock-up buzz |

**Engine presence (1)** — kept per explicit user request ("don't forget engine vibration"):

| Effect | Gain | Notes |
|---|---|---|
| `RPMContainer` | 25 | Low-frequency engine thrum through seat. Safe on BS-1's 50 W continuous rating. |

### Disabled (13)

Newly disabled in 1R (rolled back from 1B): `WheelsSlipContainer` (was 70), `TractionLossContainer` (was 60), **`DecelerationGforceContainer` (was 40 — the thermal killer, off for clean baseline)**.

Always off: `RPMSoundEffectContainer`, `WheelsSpinAndLockContainer`, `TCActiveEffectContainer`, `LateralGforceContainer`, `AccelerationGforceContainer`, `SpeedContainer`, `LocalizedSpeedContainer`, `WheelsRumbleContainer`, `FlightsWingsLoadContainer`, `CustomEffectContainer`.

## RPM character expectations

RPM on a BS-1 at gain 25, mono-sum to a single seat-mounted shaker, plays back as:
- **At idle / standstill**: low steady thrum through thighs + lower back.
- **On-throttle**: thrum pitch tracks engine RPM — more warm rumble than per-firing-stroke pulse.
- **Not a detailed cylinder count** — the BS-1 is tuned for body/road, not engine granularity. That's a design trade-off the BS-1 makes.

Preference tuning bounds (hardware-safe on BS-1):
- Too subtle → raise to 35–40.
- Too droney → drop to 15.
- Outside 10–50, character breaks down; pick a different effect instead.

## Verification procedure

Sanity check the loaded state after any SimHub restart:

```powershell
$j = Get-Content -LiteralPath 'C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json' -Raw | ConvertFrom-Json
$ch = $j.OutputManager.ChannelsSettingsV3[0]
"$($ch.Name) | HP $($ch.HighPassFilter) LP $($ch.LowPassFilter)"
$p = $j.Profiles | Where-Object { $_.ProfileId -eq $j.activeProfileId }
"Active: $($p.Name) | GlobalGain $($p.GlobalGain) | OutputMode $($p.OutputMode) | enabled=$(($p.EffectsContainers | ? IsEnabled).Count)"
```

Expected output:
```
Speakers (8- USB PnP Sound Device) | HP 25 LP 120
Active: AC Copilot - Single BS-1 Right (Recovery) Phase 1R | GlobalGain 60 | OutputMode 1 | enabled=12
```

In-car smoke test (sit in car, engine on, parking brake up):
1. **Standstill**: feel a low steady thrum under thighs / lower back → RPMContainer @ 25 working.
2. **Blip throttle**: thrum pitch modulates up and back → RPM modulation live.
3. **Drive over curb**: sharp punch through seat → `ImpactEffectContainer` / `WheelsImpactContainer`.
4. **Hard brake to lock**: buzz through seat → `WheelsLockContainer`; if car has ABS, also `ABSActiveEffectContainer`.
5. **Gear shift under load**: crisp thump → `GearEffectContainer`.
6. **Roll on throttle on exit**: subtle texture → `RoadTextureContainer` + `WheelsVibrationContainer`.

## Phase roadmap

- Phase 1A: mono-sum dual-transducer, no always-on. Superseded.
- Phase 1B: mono-plus with LP 160, brake-side boosted, RPM + DecelG always-on. **Killed the pedal transducer.** Superseded. Full incident write-up: `haptics-thermal-failure-2026-04-18.md`.
- **Phase 1R (CURRENT)**: single BS-1 right, LP 120, RPM kept at 25, no pedal-channel content.
- **Phase 2A (next)**: requires Dayton TT25 (real 25 W continuous). When arrived: mount on SRP bracket, replug amp left channel, flip MapsStore left to enabled=1 gain=99, reinstate RPM and carefully reintroduce DecelerationGforce. Add **hardware volume ceiling on Douk knob (~40 % max)** and optional **4 Ω 5 W series resistor on left leads as sacrificial fuse**. Test under real load for ≥1 minute before walking away.
- Phase 1C (true stereo routing via SimHub UI → learn `EffectToChannelsMapStore` format): deferred, blocked by Phase 2A.

## Rollback

Not useful while pedal channel has no load, but if ever needed:

```powershell
Stop-Process -Name SimHubWPF -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Copy-Item "C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.backup.20260418-202120-pre1R.json" `
          "C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json" -Force
Start-Process "C:\Program Files (x86)\SimHub\SimHubWPF.exe"
```

## Change log

- **2026-04-18 20:21** — Created. Supersedes `dual-transducer-brake-body-v1.md`. Phase 1R deployed after Phase 1B destroyed the AliExpress pedal transducer. Audio device rebound to new "8-" USB endpoint GUID. RPM kept enabled at 25 per user request.

## Related nodes

- `dual-transducer-brake-body-v1.md` — previous active architecture (now superseded).
- `bass-shaker-bs1-balanced-v1.md` — original single-shaker config (archival).
- `srp-brake-bracket-v1.md` — 3D-printed bracket (sits empty until TT25 arrives).
- `haptics-thermal-failure-2026-04-18.md` — incident write-up + durable lessons.
