---
type: investigation
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Router mesh cross-AP TCP block (2026-04-21)

## Symptom

PC (192.168.4.26 / `/22`) and ESP32 screen (192.168.0.220 / presumably `/24`)
are both joined to the same SSID `AHOME5G`. **ICMP routes both ways** (PC→
device ping reliable, ~80–160 ms RTT, TTL=63 → 1 hop via gateway). But
**TCP connect to any port times out**, both directions:

- Device → `192.168.4.26:8765`: `select returned due to timeout 3000 ms` /
  `setSocketOption fail errno 9`.
- PC → `192.168.0.220:80`: `connect: timed out`.

Confirmed not Windows firewall: still failed with both `Private` and
`Public` profiles disabled. Not Tailscale: service was in `NoState` (not
authed) so it had no active routes.

## Root cause

The home router runs an `AHOME5G` mesh with **8 BSSIDs**:

```
50:27:a9:1c:b8:e6  (PC's AP)
42:75:c3:43:43:f1
50:27:a9:1c:b6:86
50:27:a9:1b:63:c5
50:27:a9:1c:b6:85
50:27:a9:1c:b8:e5
42:75:c3:4a:43:f2
50:27:a9:1b:63:c6
```

Each BSSID has its own client isolation / VLAN. ICMP gets a "router echo"
NAT-style pass through, but TCP between `192.168.0.0/24` and
`192.168.4.0/22` clients is dropped at the bridging layer. This appears to
be a stock ISP router default we cannot change without router admin.

## Workaround

**Windows Mobile Hotspot.** PC bridges its primary Wi-Fi to a hosted
network; device joins the hotspot directly. Both peers end up on
`192.168.137.0/24` with PC at `192.168.137.1` (gateway).

Hotspot creds (PC default; rotate when sensitive):
- SSID: `AG_PC 7933`
- Pass: `4r3U9$87`

Programmatic enable (PowerShell, runs once):

```powershell
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
 Windows.Networking.NetworkOperators, ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.Connectivity.NetworkInformation,
 Windows.Networking.Connectivity, ContentType=WindowsRuntime] | Out-Null
$conn = [Windows.Networking.Connectivity.NetworkInformation]::
            GetInternetConnectionProfile()
$tm = [Windows.Networking.NetworkOperators.
       NetworkOperatorTetheringManager]::CreateFromConnectionProfile($conn)
$tm.StartTetheringAsync()  # await via the WinRT helper
```

After that, point `firmware/screen/secrets/sidecar.h` at `192.168.137.1`
and `wifi_secrets.h` at the hotspot SSID. Bind the sidecar with
`--external-bind 0.0.0.0 --token <secret>`.

## Live verification (2026-04-21 ~21:00 PT)

```
INFO ws upgrade accepted client=ac-copilot-screen-01
     peer=('192.168.137.25', 57810)
INFO sidecar client connected protocol=1 peer=('192.168.137.25', 57810)

[ws] -> {"v":1,"type":"action","name":"toggleFocusPractice"}    # device serial
```

## Open follow-ups

- Long-term: ask ISP to disable client isolation or get a flat-LAN router
  rule. The hotspot adds latency and only works when PC is on.
- Once Phase-2 firmware uses mDNS, switching networks no longer needs a
  reflash — just change the hotspot/router config.
