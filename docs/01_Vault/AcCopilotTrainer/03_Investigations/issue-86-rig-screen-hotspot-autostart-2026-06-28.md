---
type: investigation
status: active
created: 2026-06-28
updated: 2026-07-01
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

- Windows Wi-Fi was attached to a home 5 GHz network; there was no active
  Windows Mobile Hotspot gateway for the ESP32's configured rig hotspot path.
- Nothing was listening on sidecar port `8765`.
- The ESP32 itself was present over native USB CDC/JTAG (`COM6`, VID/PID
  `303A/1001`), so the fault was the PC-side network/sidecar path, not a dead
  board.

## Recovery performed

1. Started `tools.ai_sidecar` with external bind and the firmware-matching token.
2. Set the home Wi-Fi profile to manual and disconnected the Intel 7260 from
   5 GHz so Windows Mobile Hotspot could host the 2.4 GHz rig AP.
3. Confirmed Mobile Hotspot `On`, one client, and an ESP32 DHCP/ARP lease.
4. Confirmed sidecar `/health` and `/metrics`, an established
   hotspot-gateway-to-screen socket, and protocol counters moving
   (`state.snapshot`, `state.subscribe`, `corner_query`, setup experiment frames).

Original diagnosis found `ac_sidecar_screen_connected` was only a 120-second
recency gauge based on the WS upgrade header, not a durable socket-open gauge.
PR #361 now adds current `screen_peers` health/metrics and keeps
`ac_sidecar_screen_connected` true when a screen socket is actually present.

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
- `tools.ai_sidecar` health/metrics now report current screen peers, and the Lua
  telemetry publisher reads CSP userdata/cdata car state defensively.
- User environment on this PC now has `AC_COPILOT_SIDECAR_TOKEN` set and
  `AC_COPILOT_SIDECAR_PORT=8765`; token value intentionally not recorded here.

## Verification

- Focused tests: `8 passed` for rig env-token, missing-token safety, batch
  contract, and Windows hook path resolution.
- `start_sidecar.bat` artifact proof: launched on temporary port `9876`; logs
  showed `AI sidecar listening host=0.0.0.0 port=9876 ... token=set`, process
  command line omitted `--token`, and `/health` returned OK.
- Broad suite with only `tests/test_process_miner/test_distill.py` ignored:
  `1548 passed, 114 skipped`, coverage `83.33%`.
- Full pytest collection without the ignore is blocked on missing
  governance-hub `runtime/inference_egress`; `~/.fleet-governance` exists on this
  PC but has no `runtime/` directory.
- `make ci-fast` cannot run directly in this PowerShell because `make` is not
  installed; direct recipe pieces were run instead. Repo-wide ruff format check
  still wants to rewrite hundreds of unrelated CRLF/LF files in this Windows
  checkout, while changed files pass targeted `ruff format --check`.

## Racing Atelier firmware pass (2026-07-01)

Branch `feat/issue-86-racing-atelier-rig` applies the PR #410 Racing Atelier
handoff to the ESP32 JC3248W535 firmware surface:

- Replaced the legacy firmware font bundle with committed `lv_font_conv`
  outputs for Saira, Saira Semi Condensed, and Spline Sans Mono, plus source
  TTFs and regeneration docs.
- Rewired `firmware/screen/include/ui/tokens.h` to the carbon/brass/signal
  palette (`#0B0C0D`, `#C8983E`, `#F23B2C`, `#F4A52C`, `#2FBE6E`,
  `#49B6C9`) and square tile radius.
- Rebuilt the AC Copilot screen as a portrait instrument UI: live/stale status,
  corner badge, single command, brake-distance readout, 12-cell brake-zone
  strip, signed delta fill, advice footer, and square back affordance.
- Touched Launcher, Pocket Technician, Setup Exchange, and toast styling only
  enough to use the shared Racing Atelier font/radius tokens.

Verification:

- `python -m platformio run -e jc3248w535` from `firmware/screen/` succeeded
  with RAM 48.5% and flash 18.3%.
- `python -m pytest -q tests/test_rig_screen_racing_atelier.py
  tests/test_setup_library_summary.py` reported `22 passed`.
- `FLEET_GOVERNANCE_ROOT=.fleet-governance-vendor make ci-fast` reported
  `2035 passed, 117 skipped`, coverage 85.82%, and `ci-fast: OK`.

Remaining closure gate: physical rig proof. Flash/boot the screen, compare a
photo against `docs/10_Development/design/racing-atelier-renders/esp32_rig.png`,
then smoke launcher -> AC Copilot live hints -> Pocket Technician setup load ->
Setup Exchange browse/download/install. The Tier-3 MCP memory tool was not
exposed in this Codex surface; repo memory prefetch returned stale #402
context, so this pass used Tier-2 vault state plus live GitHub #86 comments.
