---
type: investigation
status: resolved
created: 2026-04-21
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Screen debugging journey — 2026-04-21

Companion to [`jc3248w535-display-canvas-flush-2026-04-21`](jc3248w535-display-canvas-flush-2026-04-21.md) and [`router-mesh-cross-ap-tcp-block-2026-04-21`](router-mesh-cross-ap-tcp-block-2026-04-21.md). Those nodes capture the **fixes**; this node captures **what was tried that didn't work** so the next session doesn't re-walk the same dead-ends.

## Symptom timeline

1. **T=0** — First flash from a prior Claude Cowork session leaves panel black with a single thin white line on the right edge. User expects the stock UI (last seen working directly before the flash).
2. Firmware boots fine (serial log prints `[boot] AC Copilot Screen ac-copilot-screen-01`, `[wifi] up`, `[ws] dial`) — it's a **display init** problem, not a boot problem.
3. Backlight (BL) is on (thin white line proves it) — not a power problem.

## Dead-ends tried (DO NOT REPEAT)

### 1. Seven-pin backlight sweep

Wrote a diagnostic firmware that pulsed every plausible BL candidate pin in sequence: 1, 38, 45, 46, 47, 48, 21.

**Result:** Zero visible brightness change on the panel. This is what falsely suggested "panel is hardware-dead." The real issue was the init table, not the BL pin — the panel stayed in partial-init state.

**Key insight:** a wrong init table can suppress the entire display regardless of BL. Don't use BL pulse response as proof of life for AXS15231B panels.

### 2. Cycling colour diagnostic

Full-screen R → G → B → W cycle with 2.2 s dwell per colour, black border, diagonal cross. No display output.

**Result:** Useless because pixel writes without `Arduino_Canvas::flush()` are discarded by the QSPI controller. Same root cause as #1.

### 3. Custom `JC3248W535_GFX.h` subclass

Guessed the moononournation init table was wrong and wrote a custom `Arduino_AXS15231B` subclass with minimum-init (sleep-out, `COLMOD=0x05` (RGB565), `MADCTL=0x00`, display-on). Wired into the board factory.

**Result:** "Blue lines all over" — visible evidence we're NOW driving the panel, but at the wrong pixel format. This was the **signal inversion** that redirected the investigation.

**Key insight:** If you see "lines all over" on a QSPI panel, you've crossed the driving-it-but-wrong-format threshold. Don't keep hand-tuning init — switch to `Arduino_Canvas` + `flush()` with default `Arduino_AXS15231B` + `ips=false`.

### 4. PC-side firewall disable + LAN probe

When the device joined the home mesh SSID on its mesh-assigned subnet but couldn't TCP to sidecar on the PC mesh subnet, tried: disabled Windows Defender Firewall entirely, added inbound port 8765 rule. Still no connect.

**Result:** Proved the block is NOT on the PC. It's at the router.

### 5. Tailscale suspicion

Suspected Tailscale's VPN stack might be intercepting LAN TCP. Checked routing table + firewall rules.

**Result:** Tailscale wasn't the cause.

### 6. Same-SSID join attempt (different subnet AP)

Tried to see other visible SSIDs via `netsh wlan show networks`.

**Result:** The network is a **mesh with 8 BSSIDs** under one SSID. It segments subnets per-AP. Router drops cross-AP TCP. No user access to router admin to remove the block.

## The actual fixes (for cross-reference)

### Display fix

```cpp
// Default Arduino_AXS15231B class, ips=false
auto *gfx = new Arduino_AXS15231B(bus, rst, 0 /*rotation*/, false /*ips*/);
// Wrap in Arduino_Canvas
auto *canvas = new Arduino_Canvas(480, 320, gfx);
canvas->begin();
// Draw to canvas as normal, then:
canvas->flush();  // once per ~16 ms in loop()
```

The moononournation init table is tuned for a 1.91" 360×640 AMOLED variant, not our 320×480 LCD. Using `ips=false` + `Arduino_Canvas` + `flush()` is the LCD path.

### Network fix

Windows Mobile Hotspot: local SSID + password (kept out of git) / PC becomes hotspot gateway / device gets hotspot lease. Sidecar launched with `--external-bind 0.0.0.0 --token <T>` binds the hotspot interface; device firmware compiled with hotspot gateway as `SIDECAR_HOST` and hotspot SSID as `WIFI_SSID`.

## The proof-of-life trick: factory backup restore

**Critical technique for any future "is this panel dead?" doubt:**

```powershell
# At flash time, BEFORE touching the panel, dump the factory image:
esptool.py --port <DEVICE_SERIAL_PORT> read_flash 0x0 0x1000000 `
  firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin
```

Then if the panel ever looks dead, restore it:

```powershell
esptool.py --port <DEVICE_SERIAL_PORT> write_flash 0x0 `
  firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin
```

If the stock UI boots, the panel is alive and the problem is in our firmware. Binary lives at `firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin` (16 MB, SHA recorded in change log of [`esp32-jc3248w535-screen-v1.md`](../10_Rig/esp32-jc3248w535-screen-v1.md)).

**Always dump the factory flash BEFORE first experimental flash.**

## Elapsed time

The full session (from "i see no changes now" to "end-to-end working") spanned ~6 hours. User was visibly frustrated multiple times ("you didnt do a thing for 50 min", "can you finish the work!", "please continuously run in foreground"). See [`cowork-session-retrospective-2026-04-21`](cowork-session-retrospective-2026-04-21.md) for how that shaped next-session autonomy preferences.

## Lessons durable beyond this board

1. QSPI panels (AXS15231B, ST77922, etc.) need full-framebuffer flushes — per-pixel writes garble the controller even though individual commands succeed.
2. Vendor init tables are often tuned for the flagship SKU; cheaper or different-form-factor variants from the same chip family need different init. Check panel size + interface before trusting the bundled example.
3. A wrong init table can make the panel look hardware-dead (no BL response, no colour). Always test with factory restore before calling hardware.
4. Mesh Wi-Fi can segment per-AP even on one SSID — ICMP can route across while TCP doesn't. Windows Mobile Hotspot is a reliable circumvention for single-user dev.
5. Always dump the factory flash image BEFORE first experimental flash.
