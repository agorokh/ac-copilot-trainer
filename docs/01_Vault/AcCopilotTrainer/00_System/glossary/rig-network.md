---
type: glossary-term
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Rig network — the known addresses

Single reference for all the addresses, SSIDs, and tokens the rig screen + sidecar + PC use during live-dev on 2026-04-21's Windows Mobile Hotspot workaround.

| Role | Value |
|------|-------|
| Windows Mobile Hotspot SSID | `AG_PC 7933` |
| Windows Mobile Hotspot password | `4r3U9$87` |
| PC (hotspot interface) IP | `192.168.137.1` |
| ESP32 rig screen IP | `192.168.137.25` |
| Sidecar port | `8765` |
| Sidecar URL for rig | `ws://192.168.137.1:8765/` |
| WS auth header | `X-AC-Copilot-Token: <token>` |
| Dev placeholder token | `replace-me-when-sidecar-auth-ships` |
| Device WS client-id | `ac-copilot-screen-01` |
| Device VID/PID | `0x303A / 0x1001` |
| Device MAC | `3C:0F:02:CF:5A:20` |
| Device serial port | `COM6` |

## Household mesh (do NOT use for rig dev)

| Role | Value |
|------|-------|
| Mesh SSID | `AHOME5G` |
| Mesh BSSID count | 8 (per-AP subnet segmentation) |
| PC subnet via mesh | `192.168.4.0/22` (PC = `192.168.4.26`) |
| Device subnet via mesh | `192.168.0.x` (device got `192.168.0.220`) |
| Cross-AP TCP | **BLOCKED** by router, ICMP routes |

The mesh is fine for normal PC/internet use but blocks the rig dev loop — hence the hotspot workaround. See [`router-mesh-cross-ap-tcp-block-2026-04-21`](../../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md).

## Hotspot re-enable (WinRT via PowerShell)

```powershell
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$mgr.StartTetheringAsync()
```

Use this after any PC reboot before running the device.
