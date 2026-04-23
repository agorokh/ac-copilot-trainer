---
type: glossary-term
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
---

# CSP app install paths + AC user-data

Exact filesystem locations on this PC for the CSP apps our rig screen interoperates with, plus the AC user-data folder.

## Pocket Technician + Setup Exchange (installed via app-csp-defaults)

- `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\PocketTechnician\PocketTechnician.lua` (262 lines, v0.4.1)
- `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\SetupExchange\SetupExchange.lua` (1058 lines, v1.5.6)
- `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\SetupExchange\Config.lua` — endpoint `http://se.acstuff.club`

Both by x4fab / [ac-custom-shaders-patch/app-csp-defaults](https://github.com/ac-custom-shaders-patch/app-csp-defaults).

## AC Copilot Trainer (our app)

- Source: `C:\Users\arsen\Projects\ac-copilot-trainer\src\ac_copilot_trainer\`
- Installed-in-AC path: `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\AC_Copilot_Trainer\` (symlinked for dev)

## AC user-data folder — STILL TO CONFIRM

`%USERPROFILE%\Documents\Assetto Corsa\` does NOT exist on this PC. AC's user-data folder is somewhere else (probably `OneDrive\Documents\Assetto Corsa\` or `%APPDATA%\Assetto Corsa\`). **Open question tagged in [`csp-app-pocket-tech-setup-exchange-2026-04-21`](../../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md):** verify before any file-watching sidecar work against `UserSetups/<carID>/`.

## Factory backup for rig screen

`C:\Users\arsen\Projects\ac-copilot-trainer\firmware\screen\_factory-backup\jc3248w535_v0.9.1_factory.bin`

16 MB flash dump taken before the first experimental flash. Restore with `esptool.py --port COM6 write_flash 0x0 <path>`.

## Vault (this)

- Source-controlled vault: `C:\Users\arsen\Projects\ac-copilot-trainer\docs\01_Vault\AcCopilotTrainer\`
- Obsidian config: `.obsidian/` inside same root
- Mirror / agent-facing: same path; no separate publish target yet
