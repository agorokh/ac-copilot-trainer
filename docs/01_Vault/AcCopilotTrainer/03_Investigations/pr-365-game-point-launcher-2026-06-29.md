---
type: investigation
status: active
created: 2026-06-29
updated: 2026-06-29
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
source_path: "AcCopilotTrainer/03_Investigations/pr-365-game-point-launcher-2026-06-29.md"
---

# PR #365 — Game Point launcher supervisor (#363)

## Summary

PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) delivers the
visible user launch path and extension contract for Game Point
([#363](https://github.com/agorokh/ac-copilot-trainer/issues/363)): Windows
shortcut installer, per-user settings, Pocket Technician spinner protocol, and
launcher-sidecar supervision.

## Install verification (rig)

Desktop shortcut via `python -m tools.rig_launcher --install-shortcut`:

- Shortcut: `C:\Users\arsen\OneDrive\Desktop\AC Copilot Game Point.lnk`
- Target: `C:\Users\arsen\Projects\ac-copilot-trainer\dist\AC-Copilot-Game-Point.exe`
- Working directory: repo root

## Code / docs touched

- `tools/rig_launcher/install`, `tools/rig_launcher/settings`, `supervisor.py`, Tk UI
- `docs/10_Development/14_Game_Point_Launcher.md`
- Pocket Technician spinner path carry + firmware refresh handling
- `AGENTS.md` — driver-facing rig functions belong in `tools.rig_launcher`

Secrets (`AC_COPILOT_SIDECAR_TOKEN`, etc.) remain environment-only.

## Review resolution history

Codex/Qodo threads addressed across the PR include: loopback-safe defaults when
no token; setup path traversal rejection; health poll on configured bind host;
PyInstaller sidecar data + launcher extra runtime deps; auto-drive `max_launches`
total cap; PT active-name preservation on path-only `setup.active`; case-insensitive
setup basename derivation; spinner refresh queue overflow toasts; sidecar log
handle lifecycle; settings UTF-8 decode fallback; Setup Exchange root validation,
bounded HTTP response reads, structured download error acks, and LVGL stale-row
guards; Pocket Technician decimal spinner transport; safe temp-file setup writes;
and path-load cache invalidation for freshly installed Setup Exchange files.

Setup Exchange direct `se.acstuff.club` calls remain intentionally disabled in
the sidecar until the official signed `/session` handshake is ported. Use
`AC_COPILOT_SE_ENDPOINT` for an authenticated proxy/test endpoint.

## Follow-ups

- Part C (Setup Exchange) and Part D (full rig smoke video) remain open on #363.
- Re-run packaged-launcher rig proof after merge when the Windows rig is available.
