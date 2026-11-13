---
type: state
status: superseded
superseded_by: dual-transducer-brake-body-v1.md
created: 2026-04-18
updated: 2026-04-18
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - 00_Graph_Schema.md
---


> **Superseded 2026-04-18** by [`dual-transducer-brake-body-v1.md`](dual-transducer-brake-body-v1.md). The user added a second tactile transducer on the SRP brake pedal, so the single-shaker design below no longer reflects the live rig. The JSON profile it described is preserved as the SimHub `Default profile` for rollback, but the active profile has been renamed and re-tuned to dual-transducer Phase 1A.

# ShakeIt BSV3 profile — "AC Copilot - BS-1 Seat Mount, Balanced v1"

Active ShakeIt Bass Shakers V3 profile for the **Douk BS-1** tactile transducer bolted under the bucket seat, wired to the **Right** channel of the 200 W Douk stereo class-D amp (Amazon ASIN B0C7C7GD9R) via 1.5 m 16 AWG speaker cable. (Earlier drafts of this note called the amp a ~2×30–50 W TPA3116 mini amp — that was wrong; the actual amp is the 200 W Douk unit.)

## Hardware chain

| Stage | Component | Spec |
|---|---|---|
| Source | PC → USB DAC | PCM2902 (VID 08BB, PID 2902), exposed as "Speakers (4- USB PnP Sound Device)" |
| Amp | 200 W Douk stereo class-D amp (ASIN B0C7C7GD9R) | ~200 W budget, stereo, 4–8 Ω per channel. Right channel in use. NOT a TPA3116 mini amp — prior notes were wrong. |
| Load | **Douk BS-1 bass shaker** | 6 Ω ±15 %, 50 W nominal / 100 W peak, 20–200 Hz, **F0 = 30 Hz**, 30 lbf peak |
| Mount | Bucket seat shell (under-seat mount) | Left channel currently idle. Small shakers planned for left-backrest later. |

## SimHub state

- **File**: `C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json`
- **Profile ID**: `f2c4bd6a-6b1a-4928-ba35-32ad42d04800` (active)
- **Fallback**: "Default profile" `33a258e4-49aa-49a4-860e-8467cea15cbb` preserved untouched.
- **Pre-edit backup**: `ShakeITBassShakersSettingsV2.backup.20260418-110925.json` in the same folder.
- `AudioMode: 1` (Mono). Both L and R carry the same signal; only R is wired.

## Shaker / amp protection

| Setting | Value | Why |
|---|---|---|
| `UseHighPassFilter` / `HighPassFilter` | `true` / 25 Hz | Below F0 (30 Hz) the voice coil absorbs power as heat — filter stops amp thermal run-up. |
| `UseLowPassFilter` / `LowPassFilter` | `true` / 120 Hz | Above ~120 Hz the BS-1 loses tactile authority and starts buzzing audibly. |
| `OutputManager.GlobalGain` | 75 | Global headroom so stacked effects don't clip. |
| Profile `GlobalGain` / `UseProfileGain` | 55 / true | Per-profile throttle; allows the Default profile to stay at 50 for comparison. |
| Douk amp knob (first session) | 50–60 % | Tune up only after a curb + gear-shift test confirms no clipping. |

## Enabled effects (10)

### Tier 1 — body feel (always on)

| Effect | Gain | Freq | Filter / shaping | Notes |
|---|---|---|---|---|
| `ABSActiveEffectContainer` | 72 | 46 Hz | Pulse 100 ms, prehemptive on | Brake-pedal feedback matches ABS cycling. |
| `GearEffectContainer` | 95 | 42 Hz | Pulse 70 ms, ignore neutral | Crisp thump on engaged shifts. `GearMode=2` (engaging). |
| `WheelsVibrationContainer` | 80 | 40→48 Hz (HF on) | AutoThreshold 45, Corners | Curbs + rumble strips; main character of the rig. |
| `RoadTextureContainer` | 35 | 42→50 Hz (HF on) | Grain 50, 8→140 km/h | Tarmac feel; was 19 in Default — bumped to 35. |
| `ImpactEffectContainer` | 100 | 44 Hz | Sensitivity 40, Corners | Collisions and hard contacts. |
| `WheelsImpactContainer` | 85 | 44 Hz | autocalMin 50, Corners | Kerb hits, potholes. |
| `JumpContainer` | 95 | 40 Hz | Front/Rear | Airborne pop for Spa / Nürburgring-style crests. |

### Tier 2 — occasional detail

| Effect | Gain | Freq | Filter / shaping | Notes |
|---|---|---|---|---|
| `GearGrindingContainer` | 55 | 44→50 Hz (HF on) | Gamma 1.2, WhiteNoise 15 | Only when clutch / shift is fumbled. |
| `GearMissedContainer` | 60 | 44 Hz | Gamma 1.2 | Missed-shift punch. |
| `TouchdownEffectContainer` | 90 | 40 Hz | Pulse 100 ms | Landing impact after JumpContainer. |

### Tier 3 — intentionally disabled (reserve for left-channel small shakers)

`RPMContainer` (tone), `RPMSoundEffectContainer` (FMOD bank), `WheelsSlipContainer`, `WheelsLockContainer`, `WheelsSpinAndLockContainer`, `TractionLossContainer`, `TCActiveEffectContainer`, `LateralGforceContainer`, `AccelerationGforceContainer`, `DecelerationGforceContainer`, `SpeedContainer`, `LocalizedSpeedContainer`, `WheelsRumbleContainer`, `FlightsWingsLoadContainer`, `CustomEffectContainer`.

These are chatter/continuous-drone effects. On a single seat-mounted 50 W transducer they mask discrete body events and heat the coil during long stints.

## Tuning philosophy

1. **Pulsed before continuous.** Body shaker prefers discrete events (gear, impact, jump) over continuous tones (RPM, speed). Continuous low-frequency stacks sum into clipping.
2. **Centre on F0.** The BS-1 resonates at 30 Hz; everything in this profile sits **35–55 Hz** to hug the efficient band without falling off the high-pass (25 Hz) or into the buzz band (>120 Hz).
3. **Curbs dominate.** `WheelsVibrationContainer` at 80 is the emotional core — it's the effect you feel most mid-corner and it carries track character.
4. **ABS audible but not overwhelming.** 72 is loud enough to feel pedal discipline without making threshold braking a chore.

## Verification procedure

After any edit to this profile:

```
pwsh -NoProfile -Command {
  $j = Get-Content -LiteralPath 'C:\Program Files (x86)\SimHub\PluginsData\Common\ShakeITBassShakersSettingsV2.json' -Raw | ConvertFrom-Json
  $ch = $j.OutputManager.ChannelsSettingsV3[0]
  "HighPass {0}@{1}  LowPass {2}@{3}" -f $ch.UseHighPassFilter,$ch.HighPassFilter,$ch.UseLowPassFilter,$ch.LowPassFilter
  $p = $j.Profiles | Where-Object { $_.ProfileId -eq $j.activeProfileId }
  "Active: {0} - enabled effects {1}" -f $p.Name, ($p.EffectsContainers | ? IsEnabled).Count
}
```

Expected output:
```
HighPass True@25  LowPass True@120
Active: AC Copilot - BS-1 Seat Mount, Balanced v1 - enabled effects 10
```

**In-game smoke test** (one lap):
1. Engaged-gear upshift at WOT — crisp discrete thump, no smearing.
2. Straight-line ABS threshold brake — steady textured pulse through the pedal, not a continuous drone.
3. Kerb-strike on exit of a rhythm section (e.g. Variante Alta at Imola) — big thump + follow-up Wheels Vibration tail.
4. Repeat 10 laps. Watch for amp thermal shutdown (dropouts) — if that happens, drop profile GlobalGain to 45 or tighten HighPass to 30 Hz.

## Change log

- **2026-04-18** — Initial profile created by AC Copilot. Default profile preserved; backup saved.

## Next planned changes

- Left-channel small shakers (backrest / rails): switch `AudioMode` 1 → 0 or 3, re-distribute Tier 3 effects via `EffectToChannelsMapStore`.
- Arduino-driven pedal vibration motors: lives under `ShakeITMotorsV3Plugin` (separate JSON). **Do not** route DC/ERM motors through this audio amp.
