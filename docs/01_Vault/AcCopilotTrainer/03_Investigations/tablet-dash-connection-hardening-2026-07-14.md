---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-14
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-511-partd-tablet-voice-endpoint-2026-07-11.md
  - AcCopilotTrainer/01_Decisions/usb-serial-screen-transport-2026-07-02.md
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Tablet dash "not connecting" — root causes + hardening plan

## What the operator saw

Tablet GT dashboard (#531) not connecting, despite the Game Point **EXE** having
"started a sidecar." Live probe on the rig (2026-07-14) found **two independent
faults**, neither of which the EXE heals.

## Root causes (live-verified)

1. **The packaged EXE is a stale build.** The live process was
   `dist\AC-Copilot-Game-Point.exe --sidecar-child --port 8765 --external-bind 0.0.0.0`
   (PID 11744). It returned **HTTP 426** for `/tablet/dash` AND `/tablet/voice` —
   i.e. the frozen binary predates both endpoints (voice #511 2026-07-11, dash
   #531 2026-07-13). Even with a perfect tunnel it cannot serve the dash page.
   The route exists in source (`server.py` ~L1099-1126), so this is purely a
   **rebuild-freshness** gap, not a code gap.
2. **No `adb reverse` tunnel, and nothing establishes/heals it.** `adb reverse
   --list` was empty even though the P7 was plugged in and authorized
   (`device` state). The dash page connects to `ws://<location.host>/` — for the
   `http://127.0.0.1:8765/tablet/dash` deployment that only resolves via
   `adb reverse tcp:8765 tcp:8765`. The EXE starts the sidecar but **never runs
   `adb reverse`** (grep: zero `adb`/`reverse`/`scrcpy` refs in `tools/rig_launcher/`).
   The tunnel is manual, documented only in `19_Tablet_Voice_Endpoint.md`, and
   dies on unplug / tablet deep-sleep / `adb kill-server` / PC reboot with no
   watchdog.

The operator's "authorize USB every time" pain is a *third* axis (USB-debug RSA
prompt) — not today's blocker (device was already authorized) but a resilience
risk if the adbkey or the tablet's "always allow" is not persisted.

## Bring-up performed (temporary, non-destructive)

Ran a **current source** sidecar on `127.0.0.1:8770` (leaving the rig-screen EXE
on 8765 untouched) + `adb reverse tcp:8765 tcp:8770`. Sidecar log then showed
`external hello accepted client=tablet-dash class=browser` + `state.subscribe` +
`setup.list` — dash **connected**. Tiles read WAITING (no AC/Lua telemetry
producer). This is a demo bring-up, not the durable path.

## Hardening plan (ordered)

**H1 — Rebuild + version-gate the EXE.** Ship a fresh `dist/` on release; expose
`build_commit`/`build_time` (and the served endpoint set) on `/health` so a stale
binary is detectable at a glance and by CI/self-test. A dash/voice smoke check
(`GET /tablet/dash == 200`) belongs in the launcher self-test and release gate.

**H2 — Self-healing reverse-tunnel keeper in the launcher.** The
`GamePointSupervisor` already owns lifecycle + `ProbeResult` rows (sidecar/screen/
voice/simhub). Add a **tablet** probe + a keeper thread: `adb start-server` →
watch device state (`adb track-devices` or poll) → on each (re)connect assert
`adb reverse tcp:<port> tcp:<port>`, verify via `adb reverse --list`, re-assert on
loss. Surface `adb-missing / no-device / unauthorized / tunnel-up / dash-peer` in
the status row so "tablet not tunneled" is visible on the PC, not just a WAITING
pill on the glass.

**H3 — Persist USB authorization.** Ensure a stable PC `~/.android/adbkey` and the
tablet's "Always allow from this computer" is checked so the RSA prompt does not
recur; keep the kiosk tablet on "Stay awake while charging" (dev option) to avoid
deep-sleep dropping the tunnel/USB.

**H4 — Evaluate a more robust transport than `adb reverse` (tracking).**
Candidates + tradeoffs:
- **USB tethering / RNDIS** — stable `usb0` subnet, survives adb-daemon restarts;
  tablet reaches the PC's RNDIS gateway directly. Needs Android-Go RNDIS support
  check. Likely the strongest USB option.
- **LAN + token WS** (already supported: `--external-bind` + `AC_COPILOT_SIDECAR_TOKEN`).
  Blocked today by: browser WS can't set the `X-AC-Copilot-Token` header (page
  assumes no-token loopback — documented #511 limit) and the mesh cross-AP TCP
  block + P7 2.4GHz/CGNAT limits ([[router-mesh-cross-ap-tcp-block-2026-04-21]]).
  Fallback only; would need a page-side token param.
- Keep `adb reverse` as default but **make it a managed, monitored, self-healing**
  resource (H2) rather than a manual step.

**Invariant to preserve:** the dash targets `location.host`, so page-origin and
transport must always agree — do not hardcode a WS host in the page.

## Next action

File a hardening issue (H1+H2 are the high-value pair: stale-build detection +
self-healing tunnel with a launcher status row). H3 is ops config; H4 is a tracked
spike.
