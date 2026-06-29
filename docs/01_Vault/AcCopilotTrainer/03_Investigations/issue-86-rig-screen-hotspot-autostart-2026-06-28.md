---
type: investigation
status: active
created: 2026-06-28
updated: 2026-06-28
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/glossary/rig-network.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/03_Investigations/screen-end-to-end-bringup-2026-04-26.md
  - AcCopilotTrainer/03_Investigations/wifi-hotspot-single-radio-2026-04-26.md
---

# Issue #86 rig-screen hotspot + sidecar autostart recovery

## Symptom

The JC3248W535 screen was powered on but not connecting to the trainer sidecar.

## Live diagnosis

- Windows Wi-Fi was attached to `AHOME5G` on 5 GHz; there was no active
  `192.168.137.1` Mobile Hotspot interface for the ESP32's configured `AG_RIG`
  path.
- Nothing was listening on sidecar port `8765`.
- The ESP32 itself was present over native USB CDC/JTAG (`COM6`, VID/PID
  `303A/1001`), so the fault was the PC-side network/sidecar path, not a dead
  board.

## Recovery performed

1. Started `tools.ai_sidecar` with external bind and the firmware-matching token.
2. Set the `AHOME5G` Wi-Fi profile to manual and disconnected the Intel 7260
   from 5 GHz so Windows Mobile Hotspot could host the 2.4 GHz `AG_RIG` AP.
3. Confirmed Mobile Hotspot `On`, one client, and ARP lease
   `192.168.137.231` for the ESP32 MAC.
4. Confirmed sidecar `/health` and `/metrics`, established socket
   `192.168.137.1:8765 <- 192.168.137.231`, and protocol counters moving
   (`state.snapshot`, `state.subscribe`, `corner_query`, setup experiment frames).

`ac_sidecar_screen_connected` is a 120-second recency gauge based on the WS
upgrade header, not a durable socket-open gauge. After quiet periods it can read
`0` while the ESP32 TCP connection is still established; check `/health`,
`Get-NetTCPConnection`, ARP, and message counters together.

## Code fix in flight

Branch `fix/issue-86-rig-sidecar-autostart` patches the recurring startup gap:

- `src/ac_copilot_trainer/start_sidecar.bat` stays loopback-only by default, but
  when `AC_COPILOT_SIDECAR_TOKEN` is set it launches with
  `--external-bind 0.0.0.0` (or `AC_COPILOT_SIDECAR_EXTERNAL_BIND`) and does not
  put the token on the process command line.
- `tools.ai_sidecar.server` reads the token from `AC_COPILOT_SIDECAR_TOKEN` when
  `--token` is omitted.
- `firmware/screen/README.md` documents the user-env setup and the restart
  requirement for Content Manager / Assetto Corsa.
- User environment on this PC now has `AC_COPILOT_SIDECAR_TOKEN` set and
  `AC_COPILOT_SIDECAR_PORT=8765`; token value intentionally not recorded here.

## Verification

- Focused tests: `6 passed` for rig env-token, missing-token safety, batch
  contract, and Windows hook path resolution.
- `start_sidecar.bat` artifact proof: launched on temporary port `9876`; logs
  showed `AI sidecar listening host=0.0.0.0 port=9876 ... token=set`, process
  command line omitted `--token`, and `/health` returned OK.
- Broad suite with only `tests/test_process_miner/test_distill.py` ignored:
  `1547 passed, 114 skipped`, coverage `83.32%`.
- Full pytest collection without the ignore is blocked on missing
  governance-hub `runtime/inference_egress`; `~/.fleet-governance` exists on this
  PC but has no `runtime/` directory.
- `make ci-fast` cannot run directly in this PowerShell because `make` is not
  installed; direct recipe pieces were run instead. Repo-wide ruff format check
  still wants to rewrite hundreds of unrelated CRLF/LF files in this Windows
  checkout, while changed files pass targeted `ruff format --check`.
