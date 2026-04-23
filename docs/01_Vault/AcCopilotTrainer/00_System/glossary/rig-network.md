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
| Windows Mobile Hotspot SSID | `<HOTSPOT_SSID>` |
| Windows Mobile Hotspot password | `<set-locally-not-in-git>` |
| PC (hotspot interface) IP | `<HOTSPOT_GATEWAY_IP>` |
| ESP32 rig screen IP | `<RIG_SCREEN_IP>` |
| Sidecar port | `8765` |
| Sidecar URL for rig | `ws://<HOTSPOT_GATEWAY_IP>:8765/` |
| WS auth header | `X-AC-Copilot-Token: <token>` |
| Dev placeholder token | `<set-locally-not-in-git>` |
| Device WS client-id | `<DEVICE_CLIENT_ID>` |
| Device VID/PID | `<DEVICE_USB_VID_PID>` |
| Device MAC | `<DEVICE_MAC>` |
| Device serial port | `<DEVICE_SERIAL_PORT>` |

## Household mesh (do NOT use for rig dev)

| Role | Value |
|------|-------|
| Mesh SSID | `<HOME_MESH_SSID>` |
| Mesh BSSID count | 8 (per-AP subnet segmentation) |
| PC subnet via mesh | `<MESH_PC_SUBNET>` |
| Device subnet via mesh | `<MESH_DEVICE_SUBNET>` |
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
