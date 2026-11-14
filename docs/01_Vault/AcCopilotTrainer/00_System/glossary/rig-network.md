---
type: entity
status: active
created: 2026-04-22
updated: 2026-04-26
relates_to:
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/wifi-hotspot-single-radio-2026-04-26.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Rig network — the known addresses

Single reference for all the addresses, SSIDs, and tokens the rig screen + sidecar + PC use during live-dev on 2026-04-21's Windows Mobile Hotspot workaround.

| Role | Value |
|------|-------|
| Windows Mobile Hotspot SSID | `<HOTSPOT_SSID>` |
| Windows Mobile Hotspot password | `<redacted-local-only>` |
| PC (hotspot interface) IP | `<HOTSPOT_GATEWAY_IP>` |
| ESP32 rig screen IP | `<RIG_SCREEN_IP>` |
| Sidecar port | `8765` |
| Sidecar URL for rig | `ws://<HOTSPOT_GATEWAY_IP>:8765/` |
| WS auth header | `X-AC-Copilot-Token: <token>` |
| Dev placeholder token | `<redacted-local-only>` |
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

## Hotspot re-enable (PC reboot recovery)

The PC's Wi-Fi card is **single-radio**: it cannot host the 2.4 GHz hotspot while the primary Wi-Fi is connected to a 5 GHz network. The hotspot will report `Band: TwoPointFourGigahertz` and `TetheringOperationalState: On` but the radio is still on 5 GHz and the ESP32 (2.4 GHz only) gets `NO_AP_FOUND`. Always disconnect the primary Wi-Fi before starting the hotspot. Full diagnosis: [`wifi-hotspot-single-radio-2026-04-26`](../../03_Investigations/wifi-hotspot-single-radio-2026-04-26.md).

```powershell
# 1. Stop the household mesh from auto-reconnecting and stealing the radio
netsh wlan set profileparameter name='AHOME5G' connectionmode=manual
netsh wlan disconnect

# 2. Start hotspot (already configured: SSID AG_RIG, Band 2.4 GHz)
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$mgr.StartTetheringAsync()  # await via WinRT helper

# 3. Verify: device should join AG_RIG within ~5 s
# When done, restore internet:
#   netsh wlan connect name='AHOME5G'
```
