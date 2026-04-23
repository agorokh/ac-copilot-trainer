---
type: epic
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/bass-shaker-bs1-balanced-v1.md
  - AcCopilotTrainer/10_Rig/single-bs-1-recovery-phase1r-v1.md
  - AcCopilotTrainer/10_Rig/haptics-thermal-failure-2026-04-18.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
---

# Physical Rig Integration — EPIC #59

Umbrella for the physical hardware layer of the sim rig. **Not** coaching logic — this is the tactile, visual, and interactive hardware that makes the cockpit feel alive and removes the need to reach for keyboard/mouse during a session.

Source: [GitHub issue #59](https://github.com/agorokh/ac-copilot-trainer/issues/59) (OPEN, label `enhancement`, author `agorokh`, 0 comments). No milestone/assignee.

## Scope — 4 phases

### Phase 1: Basic telemetry + wind sim (Arduino UNO R3)

- **Arduino UNO R3** (ATmega328P) — main controller
- **0.96" OLED SSD1306** (I²C, 128×64) — tyre condition display
- **USB 5V PWM fan** — speed-mapped wind simulation via NPN transistor
- **3D-printed enclosure** — mounts to 3030 extrusion via M6 bolt
- Wiring: OLED on I²C (A4/A5), fan on D9 PWM, USB power/data from PC

### Phase 2: Touch dashboard (ESP32 JC3248W535)

**This is the current stream A work.** See [`esp32-jc3248w535-screen-v1.md`](esp32-jc3248w535-screen-v1.md).

Originally scoped in #59 for a generic "ESP32 3.5" IPS touch 480×320 8MB PSRAM / 16MB Flash" — landed on the Guition JC3248W535 (AXS15231B QSPI + capacitive touch via same chip at I²C 0x3B).

Planned screens:
- Live telemetry dash — speed, RPM, gear, brake/throttle bars, lap time
- Tyre condition heatmap — 4-tyre temp/pressure/wear
- Car setup selector — browse and apply setups from AC setups folder
- Post-lap coaching summary — ranked improvement suggestions from sidecar

Connects as a second WebSocket client to the Python sidecar (WiFi). See [`external-ws-client-protocol-extension`](../01_Decisions/external-ws-client-protocol-extension.md) for the `{v,type}` envelope.

### Phase 3a: Bass shaker (under-seat)

- **Dayton Audio BST-1** — bolted **underneath** the bucket seat, NOT inside upholstery
- Driven by small class-D amp (Nobsound NS-01G, 4Ω 25W RMS)
- SimHub audio output → amp → shaker
- Mapped to: engine RPM, road texture, curb rumble, ABS, wheel lock, gear shifts, collisions

See [`bass-shaker-bs1-balanced-v1`](bass-shaker-bs1-balanced-v1.md) and [`single-bs-1-recovery-phase1r-v1`](single-bs-1-recovery-phase1r-v1.md) for the live configuration.

### Phase 3b: Side bolster vibration motors (lateral G-force)

- **2× DC vibration motors** (12V ~4000 RPM, enclosed)
- Mounted on the **outside** of the bucket seat shell, NOT inside foam
- Aluminum frame acts as heatsink
- Left motor = right turn G-force, right motor = left turn G-force
- **Driver**: Arduino PWM → gate resistor → IRLZ44N MOSFET → motor → 12V external PSU. Flyback diode across each
- Pins: **D10 + D11**
- **Software duty cycle safeguard**: cap continuous PWM at ~70%, thermal cooldown if >50% for 30+ s

### Phase 4: Pedal haptics

- **Apex SimRacing SimNet Rumble Motor** — bolt-on rumble for pedal assembly (ABS pulse, brake lock, throttle wheel-spin)
  - Pin: **D3** or **D5** (PWM) if driven from Arduino
- **Salvaged Xbox controller rumble motors** (from broken controller):
  - 2 motors: large (heavy offset, low-freq rumble) + small (light, high-freq buzz)
  - 3–5V DC, no proprietary protocol
  - Drive from Arduino PWM via 2N2222 transistor
  - Large → pedal base for brake ABS / lock-up rumble
  - Small → pedal base for tyre slip / gear shift buzz
  - Pins: **D3 + D5**

## Pin allocation (Arduino UNO R3)

| Pin | Function | Driver |
|-----|----------|--------|
| D3 | Pedal rumble motor | 2N2222 or MOSFET |
| D5 | Pedal buzz motor (Xbox small) | 2N2222 |
| D9 | Wind simulation fan | 2N2222 |
| D10 | Left seat vibration motor | IRLZ44N MOSFET |
| D11 | Right seat vibration motor | IRLZ44N MOSFET |
| A4 (SDA) | OLED display | I²C |
| A5 (SCL) | OLED display | I²C |
| D6 | **Spare PWM** | — |

## Architecture

```
┌──────────────┐     CSP Lua API      ┌──────────────────┐
│  Assetto     │◄────────────────────►│  ws_bridge.lua   │
│  Corsa       │  ac.StateCar/Sim     │  setup_reader.lua│
└──────────────┘                      └────────┬─────────┘
                                               │ WebSocket
                                               ▼
                                      ┌──────────────────┐
                                      │  Python Sidecar  │
                                      │  server.py       │
                                      │  (hub / router)  │
                                      └──┬─────┬─────┬───┘
                              WebSocket │     │     │  Audio
                                        ▼     ▼     ▼
                                      ┌────┐ ┌────┐ ┌─────┐
                                      │ESP │ │UNO │ │Amp  │
                                      │32  │ │R3  │ │+BST1│
                                      │Touch│ │    │ │Shaker│
                                      └────┘ └──┬─┘ └─────┘
                                                │ PWM
                ┌───────────────────────┼───────────────────┐
                ▼                       ▼                   ▼
         ┌──────────────┐      ┌──────────────┐    ┌──────────────┐
         │ OLED + Fan   │      │ Seat Motors  │    │ Pedal Motors │
         │ Tyre + Wind  │      │ L: Right-G   │    │ Xbox Large:  │
         │ I²C + D9     │      │ R: Left-G    │    │  ABS rumble  │
         └──────────────┘      │ D10 + D11    │    │ Xbox Small:  │
                               │ 12V MOSFET   │    │  Slip buzz   │
                               └──────────────┘    │ D3 + D5      │
                                                   └──────────────┘
```

## Software deltas required

### `ws_bridge.lua` (CSP side)
- Rate-limited `telemetry_tick` (~10–20 Hz): speed, RPM, gear, brake, throttle, steering, tyre temps/pressures/wear, position, lap time, lateral/longitudinal G
- `setup_list_request` → trigger `setup_reader.lua` to enumerate setups
- `setup_apply` → switch active car setup

### `server.py` (Python sidecar)
- Multi-client WS — tag connections as `lua` / `esp32` / `browser`
- Route `telemetry_tick` to ESP32/browser clients only
- Handle `setup_list` / `setup_select` from ESP32
- Expose coaching summaries to ESP32 after each lap
- Haptic event generation from telemetry for Arduino outputs

### `protocol.py`
- New types: `telemetry_tick`, `setup_list`, `setup_select`, `setup_applied`, `coaching_summary`, `haptic_event`
- Version for back-compat

### ESP32 firmware
- PlatformIO + LVGL UI
- WiFi auto-connect to sidecar
- Multi-screen navigation (swipe or tab buttons)
- JSON parsing for telemetry + coaching
- Setup file browser UI with touch selection

### Arduino UNO firmware
- SimHub protocol or custom serial for fan PWM + OLED + vibration + pedal haptics
- Duty cycle management + thermal protection
- Map lateral G → L/R vibration intensity
- Map ABS / brake lock → pedal rumble
- Map tyre slip / gear shift → pedal buzz

## Hardware shopping list (~$93 + Apex motor)

| Item | Purpose | Est. $ |
|------|---------|--------|
| Arduino UNO R3 (ATmega328P) | Main controller | 4 |
| 0.96" OLED SSD1306 (I²C, 128×64) | Tyre condition display | 2 |
| USB 5V PC fan | Wind sim | 5 |
| Dupont jumpers (F-M, 20 cm) | Prototyping | 2 |
| ESP32 3.5" IPS Touch (480×320, 8 MB PSRAM) | Dashboard | 15 |
| Dayton Audio BST-1 | Under-seat shaker | 20 |
| Nobsound NS-01G class-D amp | Drives shaker | 15 |
| 2× DC vibration motors (12V 4000RPM, enclosed) | Side bolsters | 14 |
| 12V 2A DC PSU | Powers bolsters | 8 |
| 2× IRLZ44N MOSFET + flyback diodes | Motor drivers | 3 |
| 3× 2N2222 + 1 kΩ resistors | Fan + pedal drivers | 2 |
| Apex SimRacing SimNet Rumble Motor | Pedal ABS/lock | TBD |
| Salvaged Xbox controller motors (×2) | Pedal buzz + shifter | 0 |
| 3D print filament (PLA/PETG) | Enclosures | 3 |

## Lessons learned (heat management) — from [`haptics-thermal-failure-2026-04-18`](haptics-thermal-failure-2026-04-18.md)

- **Never mount bass shakers or vibration motors inside seat upholstery/foam** — sustained duty cycles overheat them
- Bass shaker goes **underneath** the seat, bolted to the frame
- Vibration motors go on **outside** of the bucket seat shell or on 3030 frame rails
- **Software duty cycle caps are mandatory** for vibration motors in continuous use
- Massage chair / generic DC motors are designed for short burst duty — sim racing demands sustained vibration (30+ s through long corners)

## Acceptance criteria (from #59)

- [ ] Arduino UNO drives fan speed proportional to car speed + displays tyre data on OLED
- [ ] Arduino UNO drives L/R vibration motors proportional to lateral G with thermal protection
- [ ] Arduino UNO drives pedal rumble for ABS/lock-up + tyre slip
- [ ] ESP32 shows live telemetry, tyre heatmap, setup selector, coaching summary
- [ ] ESP32 can browse and apply car setups from the touch screen
- [ ] Bass shaker vibrates based on road surface + engine + events (**done** — Phase 1R)
- [ ] Side bolster motors provide directional G-force feedback without overheating
- [ ] Pedal haptics pulse on ABS + buzz on tyre slip
- [ ] All peripherals connect without SimHub dependency (native to ac-copilot-trainer stack)
- [ ] Enclosure prints cleanly on FDM + mounts to 3030 profile

## Current completion status (2026-04-22)

- **Phase 1** (Arduino fan + OLED): not started
- **Phase 2** (ESP32 touch dashboard): **firmware Phase 1 shipped** (device joins hotspot, WS round-trip live, auto-ping every 10 s). **LVGL + touch + real tiles pending** — Phase-2 work.
- **Phase 3a** (bass shaker): **done** (Phase 1R recovery config after Phase 1B thermal failure)
- **Phase 3b** (side bolster motors): not started
- **Phase 4** (pedal haptics): not started

Stream A (see [`Current Focus`](../00_System/Current%20Focus.md)) is the ESP32 dashboard UI. Other phases follow once that pattern is proven end-to-end.
