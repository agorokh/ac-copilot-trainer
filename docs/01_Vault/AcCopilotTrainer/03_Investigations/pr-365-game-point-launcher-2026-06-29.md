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

Merged 2026-06-29T09:15:25Z as squash
[`854f822`](https://github.com/agorokh/ac-copilot-trainer/commit/854f822bdd868397e99bfd56c08ade2f87277139)
from PR head `27e7dbd`; #363 is closed.

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
- `.env.example` — new operator-facing env knobs for Game Point, sidecar, voice,
  SimHub, and Setup Exchange routing.
- `pyproject.toml` — launcher/voice packaging extras and runtime dependency
  bounds.

Secrets (`AC_COPILOT_SIDECAR_TOKEN`, etc.) remain environment-only.

## Merge verification

- GitHub checks on `27e7dbd`: `build`, `conformance`, `Canonical docs exist`,
  `pip-audit`, PR-pain `score`, and post-merge `classify` green.
- Review graph: no unresolved review threads after Qodo updated to `27e7dbd`
  at 2026-06-29T09:14:22Z. Gemini and Codex review bots were quota-limited and
  did not provide a current substantive finding.
- Local proof on macOS: `tests/test_rig_launcher.py` +
  `tests/test_setup_library_summary.py` = 59 passed; `make ci-fast
  PYTHON=.venv/bin/python` = 1753 passed, 75 skipped, coverage 84.93%;
  firmware `python -m platformio run -e jc3248w535` green under
  `firmware/screen/` with temporary ignored dummy secret headers removed after
  each build.
- Post-merge classification: `.env.example` changed (review new required env
  variables); `pyproject.toml` changed (run `pip install -e '.[dev]'` or the
  lockfile workflow).

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

- Re-run packaged-launcher rig proof on the Windows rig after merge: launch the
  Desktop shortcut, confirm status/log roots, sidecar health, screen peer
  presence, and audible cue path when voice env is configured.
- Direct `se.acstuff.club` Setup Exchange calls remain disabled until the
  official signed `/session` handshake is ported. Use `AC_COPILOT_SE_ENDPOINT`
  for a proxy/test endpoint meanwhile.
- Refresh dev environments after the `pyproject.toml` changes with
  `pip install -e '.[dev]'` or the repo lockfile workflow.
