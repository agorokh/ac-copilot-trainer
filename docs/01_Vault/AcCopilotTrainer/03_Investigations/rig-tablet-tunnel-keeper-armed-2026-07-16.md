---
type: investigation
status: complete
memory_tier: canonical
created: 2026-07-16
updated: 2026-07-16
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/rig-porsche-data-acd-restore-2026-07-16.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Rig maintenance — tablet dash outage: tunnel keeper was shipped but never armed (2026-07-16)

## Symptom

After the Porsche `data.acd` restore, the tablet dashboard stayed dead. Sidecar was healthy
(`/health` ok, `/tablet/dash` 200) but `browser_peers=0`.

## Root cause

The PC-side **adb daemon was not running** and `adb reverse --list` was empty — the tablet's
`localhost:8765` had no path to the PC. The #567 self-healing tunnel keeper
(`tools/rig_launcher/tablet_tunnel.py`, PR #568) would have healed this, but it is **opt-in** via
`AC_COPILOT_MANAGE_TABLET_TUNNEL=1` and that variable was **never set on the rig** (not in User or
Machine env; the Game Point EXE is launched bare with no wrapper). The keeper shipped 2026-07-14
and has been dormant ever since — the handoff's "one `AC_COPILOT_MANAGE_TABLET_TUNNEL=1` launch"
step was still pending.

## Fix (rig ops, no code change)

1. `adb reverse tcp:8765 tcp:8765` re-asserted manually → tablet reconnected in <10 s
   (the dash page's WS reconnect backoff caps at 10 s).
2. `setx AC_COPILOT_MANAGE_TABLET_TUNNEL 1` — **persisted at User scope**, so every future
   Game Point launch (including the desktop shortcut) arms the keeper.
3. Game Point relaunched with the flag + `--start` (starts the sidecar without waiting for the
   GUI START press). Both peers reconnected: `screen_peers=1`, `browser_peers=1`.

## Self-heal proven live

`adb reverse --remove-all` with the launcher open → the 5 s GUI poll tick
(`_GUI_POLL_INTERVAL_MS`, app.py) re-asserted `UsbFfs tcp:8765 tcp:8765` and the tablet stayed
connected (`browser_peers=1`). An adb daemon death / USB replug / tablet sleep now heals without
operator action **as long as the launcher window is open**.

## Residuals

- Running EXE is still `8a895ee-dirty` (2026-07-15 03:00) — predates the #602 voice fix, so voice
  remains `disabled (rtmixer)`. The pending handoff step "rebuild the packaged EXE from merged
  main" still stands; the tunnel-flag half of that step is now done durably.
- The launcher GUI does not auto-start the sidecar (operator presses START, or pass `--start`).
  Two `AC-Copilot-Game-Point.exe` processes are normal (PyInstaller onefile bootstrap pair);
  the sidecar child is a third process with `--sidecar-child`.
