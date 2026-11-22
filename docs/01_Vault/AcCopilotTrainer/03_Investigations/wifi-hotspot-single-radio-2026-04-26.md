---
type: investigation
status: active
created: 2026-04-26
updated: 2026-04-26
relates_to:
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# WiFi hotspot single-radio + SSID-with-space (2026-04-26)

## Symptom

After PC reboot + device reconnect to a different USB port, the JC3248W535
firmware boot serial spammed only:

```
[wifi] up 192.168.137.156   <- never appeared this session
Reason: 201 - NO_AP_FOUND     <- 50+ retries, every 2.4 s
```

Earlier (2026-04-21 session) the same firmware joined `AG_PC 7933` Mobile
Hotspot fine. Nothing about the firmware changed.

## Root cause (TWO stacked problems)

### 1. PC's Wi-Fi card is single-radio + 5 GHz client mode

`Intel Dual Band Wireless-AC 7260` (the PC's Wi-Fi card) has **one radio**:
it cannot host an AP and be a client on a different band simultaneously.
Windows quietly hides this — `Get-NetIPAddress` shows the hotspot adapter
"Up", `TetheringOperationalState` reports `On`, and the API even accepts
`Band = TwoPointFourGigahertz`, but the radio is physically still on
the 5 GHz channel its primary connection is using. **The hotspot is not
actually broadcasting on 2.4 GHz.** ESP32-S3 is 2.4 GHz only → never
sees the SSID → `NO_AP_FOUND`.

Confirmation: `Local Area Connection* 2` (the hosted-network virtual
adapter) shows `LinkSpeed: 54 Mbps` (802.11g cap = 2.4 GHz), but
`netsh wlan show interfaces` proves the primary `Wi-Fi` is still
`Band: 5 GHz, Channel: 36, 390 Mbps` — these are mutually exclusive on
single-radio cards.

### 2. SSID with embedded space

The default Windows hotspot SSID is `"<DeviceName> <RandomNNNN>"` (space
+ digits). ESP32 Arduino `WiFi.begin("AG_PC 7933", "...")` fails to scan
this consistently — different driver versions handle the space
differently, and we never reliably joined it.

## Fix

```powershell
# 1. Stop AHOME5G auto-reconnect so the radio stays free for 2.4 GHz hosting
netsh wlan set profileparameter name='AHOME5G' connectionmode=manual
netsh wlan disconnect

# 2. Re-configure hotspot: no-space SSID + force 2.4 GHz
$tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::
        CreateFromConnectionProfile(
            [Windows.Networking.Connectivity.NetworkInformation]::
                GetInternetConnectionProfile())
$cfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
$cfg.Ssid = 'AG_RIG'                      # NO SPACE
$cfg.Passphrase = '<keep existing>'
$cfg.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::TwoPointFourGigahertz
# StopTetheringAsync → ConfigureAccessPointAsync → StartTetheringAsync
# (ConfigureAccessPointAsync returns IAsyncAction not IAsyncOperation<T>)
```

After: device boot serial reaches `[wifi] up 192.168.137.106` and
`[ws] open` within 5 s.

## How to verify the radio is actually on 2.4 GHz

```powershell
netsh wlan show interfaces        # primary Wi-Fi: must be 'disconnected'
                                  # OR Band: 2.4 GHz
Get-NetAdapter -InterfaceAlias 'Local Area Connection* 2' | fl LinkSpeed
                                  # 54 Mbps == 2.4 GHz cap
```

If the primary Wi-Fi is connected on 5 GHz, the hotspot's reported band
is misleading. The only authoritative test is whether a 2.4 GHz client
(phone, ESP32) sees the SSID.

## Re-enable internet on PC after rig session

```powershell
# Either: rejoin AHOME5G in 2.4 GHz mode (if mesh exposes one),
#  or: accept that hotspot only runs while disconnected from the mesh.
netsh wlan connect name='AHOME5G'
# If the hotspot needs to persist, set 'connectionmode=manual' on AHOME5G
# remains in effect.
```

## Things to NOT chase next time

- Adding firewall rules. Disabling Public+Private profiles changed
  nothing (we tried). The SYN never reaches Windows because the radio
  is misbehaving; no firewall rule helps.
- Tailscale. We had it running and stopped — independent of this issue.
  Tailscale interface "Up 100 Gbps" is the virtual driver, not actual
  bandwidth.
- Switching the device to a router 2.4 GHz extender (e.g.
  `AHOME5G-2.4G-ext`). It joins fine, but the mesh router segregates
  per-AP into different /24 subnets and drops cross-subnet TCP — same
  problem documented in
  [router-mesh-cross-ap-tcp-block-2026-04-21.md](router-mesh-cross-ap-tcp-block-2026-04-21.md).
  Hotspot bypasses this only because the device joins the PC directly
  (no router in between).

## SCons stale-bug bonus fix

While reflashing with the new SSID, the build broke with:

```
TypeError: _batched_ar_action() got an unexpected keyword argument 'env'.
Did you mean '_env'?
```

`firmware/screen/tools/long_cmd_fix_post.py`'s `_batched_ar_action(target,
source, _env, _ar=ar)` declared the third arg as `_env` but SCons calls
`execfunction(target=target, source=rsources, env=env)` with the keyword
`env=`. Renaming the parameter to `env` (with comment that it's unused)
fixes the build. Already addressed in the PR #91 hardening pass with
the underscore retained — verify any future SCons-version bump still
binds positionally OR the kwarg name matches.
