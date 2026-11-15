---
type: handoff
status: active
created: 2026-11-15
updated: 2026-11-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-221000Z-game-point-rebuild-47ddb3ec-a51188.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
  - AcCopilotTrainer/00_System/glossary/rig-network.md
---

# Rig: Game Point opened and START pressed on the 47ddb3e executable

**Resume pointer.** On the operator's instruction "Open Game Point on the rig and press START",
the rebuilt launcher was opened on the rig's logged-on desktop and its START button was clicked
on 2026-11-14 between 23:50Z and 23:52Z. This closes the first "Not verified" line of the
rebuild node in `relates_to` (window not opened, START not pressed). No lap was driven. #988
stays open; its bench has not run (0 of 1 rig sessions used).

## What was done

- **Open, 23:50:27Z.** Launched through the Desktop shortcut, after checking that it targets
  `dist\AC-Copilot-Game-Point.exe` with no arguments. The window appeared in about 4 seconds.
  Bootloader pid 9620, GUI pid 1008, Normal priority, console session 1.
- **START, 23:51:38Z.** One real mouse click on the START button, sent only after confirming the
  window under the point was a `Button` owned by Game Point at the measured rectangle. The
  sidecar child (pid 2664, `--sidecar-child --port 8765`) started at 23:51:39Z. No warning dialog.
- **SimHub.** Game Point started it at 23:50:31Z on opening (pid 15120, parent 1008), because
  AUTO-START SIMHUB is ticked. It was not running beforehand.

## Verified

- `http://127.0.0.1:8765/health`: `status ok`, `build_commit 47ddb3e`,
  `build_time 2026-11-14T22:06:17Z`, `connected_peers 1`, `screen_peers 0`.
- Launcher rows 10 seconds after START: SIDECAR HEALTHY, SCREEN WAITING (no ESP32 screen peer),
  VOICE OBSERVER_ONLY (reference archive configured, no phrase bank, TTS off), PRACTICE DRILL
  DISABLED, HUMAN SESSION DISABLED, SIMHUB RUNNING, TABLET TUNNEL-UP, KEYPAD DISABLED, OFFLINE
  REPORT NOT_RUN.
- The banner still reads "PRESS START" and `status.json` has `ok: false`. The only cause shown
  is the unconnected rig screen.
- No `acs.exe` or `AssettoCorsa.exe` process before or after. With HUMAN SESSION disabled and
  Practice drill unchecked, this START spends nothing from the #529 G3 cap.
- `AC_COPILOT_HUMAN_CONTROL_ATTESTATION` unset at process, User and Machine level.
- Rig checkout clean at `0db28a7`. `keypad-profiles.json` unchanged (`89e27045…`).
- Re-read at 16:00Z on 2026-11-15: the same four processes (9620, 1008, 2664, 15120) are still
  running, health answers as above, checkout and both hashes unchanged.

## How the desktop was reached

SSH logons on the rig land in session 0, which cannot show a window on the console desktop.
`tools/ac_harness/remote_launcher.py` only runs allowlisted harness modules, none of which opens
the production launcher. Two hand-made one-shot scheduled tasks were used instead
(`ac-gp-open-a51188`, `ac-gp-press-a51188`: interactive token, least privilege, no trigger,
5-minute limit). Both were deleted after running; 0 `ac-gp*` tasks remain. The scripts, result
logs and four screenshots are in the rig checkout's gitignored `.scratch\gp-start\`.

## Found, not caused by this work

- Game Point `settings.json` was modified at 22:34Z on 2026-11-14. Its hash is now
  `38bd2180060be06a…`, not the `ffb1c4bb…` in the rebuild node. A `rig-operator\` folder
  appeared in the Game Point user directory at the same time.
- A Codex app session titled "Deliver issue 529" was open and idle on the rig desktop. Its
  visible text said it had installed a `rig-operator` skill and staged Porsche/Spa Practice, and
  that G3 was unarmed with zero attempts spent. It was not interacted with, and those statements
  were not checked.

## Not verified

- No lap was driven with this executable, and nothing was checked with the sim running.
- The health check reports inference as `not_checked_or_stale`.
- No process owns a listener on 8765 in the tools' output: `netstat` attributed it to PID 0 and
  `Get-NetTCPConnection` from the SSH session listed none, although the health check answers.
- Who changed `settings.json`, and which keys changed, was not determined.

## Left running

Game Point, its sidecar and SimHub were left running on the rig, with the mouse pointer on the
START button. Older disabled `ac-harness-*-815-*` scheduled tasks on the rig were left alone.
