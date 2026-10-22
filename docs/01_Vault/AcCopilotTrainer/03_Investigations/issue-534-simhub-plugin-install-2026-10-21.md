---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-21
updated: 2026-10-21
issue: https://github.com/agorokh/ac-copilot-trainer/issues/534
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-534-car-enrichment-simhub-audio-2026-07-25.md
  - AcCopilotTrainer/03_Investigations/issue-693-off-rig-session0-2026-07-26.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #534 SimHub car-enrichment plugin installed on the rig (2026-10-21)

The last unchecked #534 box is the operator install/enable step plus the property-picker/NCalc
check. The operator removed `not-this-cycle` and authorized the install in-session (no edits to
ShakeIt or dashboard profiles). Evidence comment:
[#534#issuecomment-6329734691](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6329734691).

## Done and observed (off-rig over SSH)

- **Build:** rig checkout `87fe0cb`, MSBuild Release against installed SimHub **9.13.2**, warnings
  as errors. DLL SHA-256 `314B8437…DFEF1E`, same hash in `C:\Program Files (x86)\SimHub`.
- **Enable:** SimHub keeps the enable state in `PluginsData\PluginsActivation.json`
  (`ClassName` / `IsEnabled`). The entry `AcCopilot.CarEnrichment.AcCopilotDataPlugin` was added
  with SimHub stopped; the original is backed up under the rig's `.scratch\issue534\`.
- **Load:** `Creating plugin manager with plugins : … AcCopilotDataPlugin …` (12 plugins) and
  `AC Copilot car enrichment bridge started`; 12/12 on two more restarts, entry preserved.
- **Wire:** source sidecar on 8765 logged `client=simhub-car-enrichment class=external`; the
  socket's owner is `SimHubWPF`. Stopping the sidecar puts the plugin back in its bounded retry loop.

## Still open

The property-picker/NCalc readback. The console was locked (`LogonUI` running, black desktop
capture), UI Automation can't reach SimHub's WPF window while locked, and `/api/getgamedata`
carries no plugin properties. About 1 minute at the rig: *Available properties*, filter
`AcCopilotDataPlugin`.

## Rig-ops lessons

- `schtasks /tr` with the 8.3 short path runs SimHub as `SI3624~1.EXE` (image name changes, so
  `tasklist /FI "IMAGENAME eq SimHubWPF.exe"` misses it). Use `Register-ScheduledTask` with the
  long path and `-LogonType Interactive` for the console user instead.
- `CloseMainWindow()` doesn't exit SimHub (it goes to the tray); a stop always ends up forced.
- Windows PowerShell 5.1: `[ArrayList]@(… | ConvertFrom-Json)` wraps the whole array as one
  element. Enumerate with `foreach` before re-serializing, or the file collapses to 2 entries.
- Unexplained: two early starts built an **empty** plugin manager (no exception logged), each right
  after a forced stop of the short-path instance. Every later start was normal (4/4).
