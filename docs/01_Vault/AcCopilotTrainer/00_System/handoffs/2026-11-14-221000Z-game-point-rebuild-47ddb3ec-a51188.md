---
type: handoff
status: active
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-211850Z-issue988-game-point-rebuild-4876fb.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-220200Z-post-merge-pr1002-host-tests-4a01df.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Rig deployment: checkout pulled and Game Point rebuilt from main at 47ddb3e

**Resume pointer.** On the operator's instructions "Pull main on the rig" and then "Rebuild
Game Point from main on the rig", the rig PC was updated between 22:04Z and 22:08Z on
2026-11-14. This supersedes the `a3d4dda` executable recorded in the first `relates_to` node and
the "Not deployed" line in the second. #988 stays open; its bench has not run (0 of 1 rig
sessions used).

## What changed on the rig

- Primary checkout `C:\Users\arsen\Projects\ac-copilot-trainer` fast-forwarded `a3d4dda0` to
  `47ddb3ec` (`git pull --ff-only`). Six files: `tools/pressure_bench_oracle.py`, three test
  files, two vault notes. Nothing under `src/`, so the trainer Lua served through the app
  junction is unchanged.
- `dist\AC-Copilot-Game-Point.exe` rebuilt with the repo `.venv` (Python 3.13.15),
  `python -m tools.rig_launcher --build-exe`, exit 0. SHA-256
  `dbc689a0d88d7b272c6333835407ebb3bcf6adecb1118c4cb0a8992863f99463`, 63,711,804 bytes, baked
  commit `47ddb3e`, bake time `2026-11-14T22:06:17Z`.
- Previous executable (`1399654d…5e03`, baked `a3d4dda`) kept, hash-verified, in
  `%LOCALAPPDATA%\WorkstationOps\Recovery\game-point-before-47ddb3ec-20261114-220610\`.
- Build log and the post-build check script are in the rig checkout's gitignored `.scratch\`
  (`game-point-build-47ddb3ec.log`, `game-point-postbuild-47ddb3ec.ps1`).

## Verified

- Before the pull and before the build: no `acs.exe`, Game Point, sidecar or SimHub process and
  no listener on port 8765. Content Manager was open and idle. Checkout on `main`, clean.
- Packaged self-test exit 0: `/tablet/dash` and `/tablet/voice` serving. Afterwards no Game
  Point process and no listener on 8765.
- The bundle contains `tools.pressure_bench_oracle`, so the Python 3.14 oracle fix from PR 1002
  is now in the executable; `tools.human_control_attestation` and `coaching_trial` are present.
- Unchanged across the build: Game Point `settings.json` (`ffb1c4bb…`) and
  `keypad-profiles.json` (`89e27045…`). Checkout still clean at `47ddb3ec`. The Desktop
  shortcut targets the rebuilt path with no arguments.

## Not verified

- The launcher window was not opened, START was not pressed, and no lap was driven with this
  executable.
- Like the 21:15Z build, this bundle has no `ucrtbase.dll` or `api-ms-win-*` forwarder DLLs
  (built over SSH; the session `PATH` decides this). The self-test ran without them.
- The bundle listing was not diffed against the previous build.
- `main` moved to `99626ca0` during the build (vault notes only, PR 1007). The rig checkout is
  one docs-only commit behind.

## Consequence carried forward

The oracle hash changed with PR 1002, and the rig now runs that oracle. A #956 run registration
sealed before `8e583e02` no longer validates on the rig. #956 was open on a cap stop with no run
in flight when this was done.
