---
type: entity
status: active
created: 2026-04-22
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
---

# CSP app install paths + AC user-data

Canonical install locations and env-var aliases for the CSP apps our rig screen interoperates with, plus the AC user-data folder.

Use these placeholders in docs/scripts instead of user-specific absolute paths:

- `%AC_ROOT%` = Assetto Corsa install root (example: `%ProgramFiles(x86)%\Steam\steamapps\common\assettocorsa`)
- `%REPO_ROOT%` = local clone root of this repository
- `%AC_USERDATA%` = AC user-data root — **`%USERPROFILE%\OneDrive\Documents\Assetto Corsa`** on this PC (see resolved note below)

## Pocket Technician + Setup Exchange (installed via app-csp-defaults)

- `%AC_ROOT%\apps\lua\PocketTechnician\PocketTechnician.lua` (262 lines, v0.4.1)
- `%AC_ROOT%\apps\lua\SetupExchange\SetupExchange.lua` (1058 lines, v1.5.6)
- `%AC_ROOT%\apps\lua\SetupExchange\Config.lua` — endpoint `http://se.acstuff.club`

Both by x4fab / [ac-custom-shaders-patch/app-csp-defaults](https://github.com/ac-custom-shaders-patch/app-csp-defaults).

## AC Copilot Trainer (our app)

- Source: `%REPO_ROOT%\src\ac_copilot_trainer\`
- Installed-in-AC path: `%AC_ROOT%\apps\lua\AC_Copilot_Trainer\` (symlinked for dev)

## AC user-data folder — RESOLVED (2026-06-28)

`%AC_USERDATA%` = **`%USERPROFILE%\OneDrive\Documents\Assetto Corsa`** on this PC (Documents is
redirected into OneDrive; the plain `%USERPROFILE%\Documents\Assetto Corsa` does **not** exist). User
setups live at `%AC_USERDATA%\setups\<carID>\[<track>\]\<name>.ini` — confirmed against
`ks_porsche_911_gt3_r_2016\generic\last.ini` and `...\spa\Realistic_BB_v*.ini`. This closes the open
question previously tagged in [`csp-app-pocket-tech-setup-exchange-2026-04-21`](../../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md);
file-watching sidecar work against `UserSetups/<carID>/` and `setup_catalog --deploy` can use it. The
rig screen's `setup.list` already enumerates `<carID>/<activeTrack>/` from this root.

## Factory backup for rig screen

`%REPO_ROOT%\firmware\screen\_factory-backup\<factory_backup_image>.bin`

16 MB flash dump taken before the first experimental flash. Restore with `esptool.py --port <DEVICE_SERIAL_PORT> write_flash 0x0 <path>`.

## Vault (this)

- Source-controlled vault: `%REPO_ROOT%\docs\01_Vault\AcCopilotTrainer\`
- Obsidian config: `.obsidian/` inside same root
- Mirror / agent-facing: same path; no separate publish target yet
