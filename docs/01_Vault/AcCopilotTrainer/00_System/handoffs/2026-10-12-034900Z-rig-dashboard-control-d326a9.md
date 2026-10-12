---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T03:49:00Z
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-11-230443Z-post-merge-pr800-c1-21e389.md
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Game Point and P7 dashboard operational check

Operator requested restoration of Game Point visibility, USB dashboard debugging,
screenshots and control, and retention of the verified state. Local session date:
October 11, 2026, America/Los_Angeles. No autonomous AC drive was started.

## Pre-loaded substrate context

Tier-3 MCP was not exposed. Canonical SessionStart prefetch successfully queried
`ac_copilot` in naive mode with a task-specific launcher/tablet/screen prompt.
It recalled the prior stale packaged-build failure; live evidence below settles
this session's state. Vault LOAD included latest handoff, current focus, relevant
tablet and ESP32 notes and the entrypoint invariant. No governance bypass.

## Observed results

- Running primary `dist/AC-Copilot-Game-Point.exe` reports build `786f0b8`,
  time `2026-07-16T21:38:07Z`; source checkout is `f27d9bf`. Source and deployed
  executable are different revisions. The EXE was not rebuilt or replaced.
- Game Point window enlarged from 931x589 to 1019x677 physical pixels;
  yellow START and all five buttons in this deployed build are visible.
  This is a live window resize, not a persistent startup-layout repair.
- `/health`: `screen_peers=1`; Game Point SCREEN CONNECTED. This establishes
  connection only, not physical ESP32 display rendering or touch verification.
- PRITOM P7, Android 13: `adb devices -l` reports one authorized USB device;
  `settings get global adb_enabled` returns `1`; `adb reverse --list` confirms
  `tcp:8765 -> tcp:8765`. Existing launcher manages the tunnel.
- Both `/tablet/dash` and `/tablet/voice` return HTTP 200 on loopback.
- Initial on-device screenshot showed Fully Kiosk's cached connection-refused
  page despite a restored tunnel. USB scrcpy 4.1 with `--no-audio` works.
  In the mirror, Alt+M opens Fully's menu; Goto Start URL reloads the saved dash.
  Dashboard then rendered, `/health` showed `browser_peers=1`, and Game Point
  changed from TUNNEL-UP to DASH-CONNECTED (`status.json` readback).
- Clicked the coaching page dot and observed DEBRIEF/PRIORITIES panels, then
  returned to the race page. USB screenshots and interactive control verified.
- Dashboard correctly shows WAITING/NO SETUP LOADED. Native process readback
  found no `acs.exe`; live driving telemetry is unverified.
- Voice health: observer_only, enabled=false, bank_configured=false,
  reference_configured=true, tts_enabled=false. No spoken-coaching claim.
- SimHub reports RUNNING. No profiles or hardware configurations changed.

## Reuse and remaining limits

Find installed adb/scrcpy with `Get-Command`. Select the P7 serial from fresh
`adb devices -l`, then use `scrcpy --serial <serial> --no-audio
--window-title=AC-Copilot-P7-Dashboard --max-size=1024`. Hyphenated window title
avoids Start-Process argument splitting. Capture tablet pixels with binary-safe
`adb -s <serial> exec-out screencap -p`; never pipe PNG through PowerShell text.
Computer-use skill's `@oai/sky` controls the mirror and Game Point.

Evidence stays in this chat worktree's ignored `.scratch/rig-restore/`:
`inspect_runtime.py`, `tablet-before.png` (latest capture), `tablet-coach.png`,
`game-point-expanded.png`, `tablet-restored.png`, scrcpy logs. Runtime status/settings/logs remain under
the existing local GamePoint folder. Mirror left running; sidecar and screen
connection preserved. No code changes, issues, chats or helper agents created.

Persistent startup sizing and deploying a current packaged launcher remain
unperformed; primary venv currently lacks PyInstaller. Current source also has
STABLE AC/RELEASE AC controls absent from the July binary. Keep the earlier C1
autonomous-drive pause until an explicit request resumes that acceptance run.

Automatic command review rejected an adb VIEW-intent launch; no reason beyond
blocked-by-policy was supplied. Recovery used observed kiosk UI instead.
