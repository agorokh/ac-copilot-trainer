---
type: handoff
status: active
created: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-210226Z-post-merge-pr997-988-attestation.md
  - AcCopilotTrainer/03_Investigations/2026-11-14-issue988-attestation-prerequisites.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Rig deployment: Game Point rebuilt from main at a3d4dda; PR 997's Lua is live

**Resume pointer.** On the operator's instruction "Rebuild Game Point from main", the rig was
updated at about 2026-11-14T21:15Z. This supersedes the "nothing was changed on the rig" line
in the PR 997 post-merge node. Issue #988 stays open; the bench has not run (0 of 1 rig
sessions used) and still waits on the keypad firmware (workstation-ops#3863). The operator
chose the keypad as the declaration surface the same evening.

## What changed on the rig

- Primary checkout fast-forwarded `e17f5a54` to `a3d4dda0`. The app junction serves that
  checkout, so the trainer Lua from PR 997 is live: new laps should carry
  `trace.control_observation`.
- `dist\AC-Copilot-Game-Point.exe` rebuilt with the repo `.venv` (Python 3.13.15, PyInstaller
  6.22.3). SHA-256 `1399654dd411a055fe33e507df22182630b3cd6c2dc444cefa34cb1933bc5e03`, baked
  commit `a3d4dda`, 63,712,520 bytes. The Desktop shortcut targets that path with no arguments.
- Previous executable (`2c2aaad2…cae2`, from `e17f5a54`) kept in
  `%LOCALAPPDATA%\WorkstationOps\Recovery\game-point-before-abf0864c-20261114\`.

## Verified

- Packaged self-test exit 0: own sidecar started, `/tablet/dash` and `/tablet/voice` serving,
  sidecar stopped; no leftover process or port-8765 listener.
- Bundle gained `tools.human_control_attestation`, `tools.ai_sidecar.coaching_trial` and
  `tools.ai_sidecar.coaching_trial_replay`. A profile binding buttons to
  `human_control.declare` and `human_control.clear` validates against the built source.
- Unchanged: `keypad-profiles.json`, Game Point `settings.json`, the attribution ledger
  (`3ca3b3cf…7425b`), 202 lap archives. The attestation opt-in is not set for user or machine.

## Not verified, and one build difference

- The launcher window was not opened and no lap was driven: the new Lua has not run in the sim.
- The `attest` binding has not been exercised through the keypad worker (stock firmware).
- This bundle lacks `ucrtbase.dll` and 43 `api-ms-win-*` forwarder DLLs that the 20:05Z build
  carried. No directory on the SSH session's `PATH` holds them, so PyInstaller did not collect
  them; they are Windows components and the self-test ran without them. The build guide's
  "only dist-info versions differ" check therefore does not hold between these two builds. The
  build environment's `PATH` decides this, and the guide does not pin it.

## Next

1. First real lap on the rig: confirm `trace.control_observation` is present and read what
   `isAIControlled`, `isUserControlled` and `isLive` report.
2. Keypad flash and qualification (workstation-ops#3863), then the bench procedure on #988.
