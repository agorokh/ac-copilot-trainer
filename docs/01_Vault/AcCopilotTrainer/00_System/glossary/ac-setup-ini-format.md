---
type: entity
status: active
created: 2026-04-26
updated: 2026-04-26
relates_to:
  - AcCopilotTrainer/00_System/glossary/_index.md
  - AcCopilotTrainer/03_Investigations/screen-end-to-end-bringup-2026-04-26.md
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
---

# AC setup INI format (verified)

Canonical layout used by AC + every CSP-built setup file we've inspected
(`ks_porsche_911_gt3_r_2016`, `bmw_m3_gt2`). Each setting lives in its own
`[SECTION]` with key `VALUE`; AC's UI maps the integer to a discrete position
per the car's `setup.ini` schema.

| Section                | Meaning                              |
|------------------------|--------------------------------------|
| `[FRONT_BIAS]`         | Brake bias as a front-bias percent (0..100) |
| `[ABS]`                | ABS level (0..N, car-specific N)     |
| `[TRACTION_CONTROL]`   | TC level                             |
| `[BRAKE_POWER_MULT]`   | Brake power scalar percent           |
| `[WING_1]`             | Front wing / splitter (or first aero element) |
| `[WING_2]`             | Rear wing                            |
| `[FUEL]`               | Fuel litres                          |
| `[TYRES]`              | Compound index into the car's tyres list |
| `[ARB_FRONT] / [ARB_REAR]` | Anti-roll bar stiffness          |
| `[CAMBER_LF / LR / RF / RR]` | Per-corner camber (negative integers) |
| `[TOE_OUT_LF / ...]`   | Per-corner toe                       |
| `[PRESSURE_LF / ...]`  | Per-corner cold tyre pressure        |
| `[SPRING_RATE_LF / ...]`, `[ROD_LENGTH_*]`, `[PACKER_RANGE_*]`, `[DAMP_*]` | Suspension settings |
| `[DIFF_COAST] / [DIFF_POWER]` | LSD ramps                     |
| `[FINAL_RATIO]` / `[INTERNAL_GEAR_*]` | Gearing                |
| `[BUMP_STOP_RATE_*]`   | Bump stop rate                       |
| `[CAR]`                | Includes `MODEL=<carID>` (not a setting) |
| `[ABOUT]`              | Includes `AUTHOR=` and `DESCRIPTION=` |
| `[__EXT_PATCH]`        | CSP version stamp                    |

Each section contains exactly `VALUE=<int>`. There is no `BRAKE_BIAS` key
at the top level — that was an early wrong guess.

## Why front bias is 0..100, not raw

`[FRONT_BIAS] VALUE=66` means "66% front brake bias". AC's UI shows it as
`66 / 34` etc. directly. Useful as a chip on the rig screen.

## Wing semantics differ per car

For GT3-style cars (911 GT3 R, M3 GT2), `WING_1` is typically the front wing
or splitter and `WING_2` is the rear wing. For F1-class or open-wheelers the
mapping changes; do not assume "WING_1=front" on every car. If we ever need
canonical labels we'll have to load the per-car `data.acd` setup schema —
out of scope for the rig screen today.

## How we read this on the trainer

`src/ac_copilot_trainer/modules/setup_library.lua::summaryForSetup(iniPath)`
opens the INI via `setupReader.readIniSnapshot` and walks the
`{section, key, value}` tuples extracting the five chips the rig screen
displays per row (BB / ABS / TC / WING_1 / WING_2). Anything missing comes
back nil and the screen omits the chip.

## See also

* `csp-app-pocket-tech-setup-exchange-2026-04-21.md` — the CSP API surface for
  `ac.loadSetup` / `ac.isCarResetAllowed` etc. that the screen-tap path uses.
* `screen-end-to-end-bringup-2026-04-26.md` — first-time bring-up where the
  section-name discrepancy was discovered.
