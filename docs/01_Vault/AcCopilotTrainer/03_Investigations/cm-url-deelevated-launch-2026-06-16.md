---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-16
updated: 2026-06-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/232
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/menu-skip-race-and-shared-memory-oracle-2026-06-14.md
  - AcCopilotTrainer/03_Investigations/garage-to-track-autonomous-entry-2026-06-13.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
---

# De-elevated Content Manager launch — hands-off on-track entry from an elevated agent shell (EPIC #154 #232)

**The keystone for fully hands-off L2.** Lets the harness daemon (running in the rig's elevated
agent shell) get AC on track without a human, surviving the elevation split that breaks a direct
`acs.exe` launch.

## The problem (found live on `AG_PC`)

- The agent/daemon shell on the rig is **elevated**; **Steam and Content Manager run non-elevated**
  (see [[steam-elevation-mismatch-ac-launch-2026-06-16]]).
- A child `acs.exe` of the elevated daemon is **elevated** → Steam-integrity mismatch
  ("Steam API has failed to initialize"). So the merged Part F daemon's `acs.exe`-direct
  `/session/start` (`ColdRestartActuator`) **cannot** get AC on track from the agent shell. The
  Part F merge was verified off-sim (mocked launcher), so this never surfaced in CI.

## The fix (verified)

Spawn `Content Manager.exe "acmanager://race/quick?presetFile=<preset>"` **from the elevated
shell**. The new (even elevated) CM instance forwards the URL via CM single-instance IPC to the
**running non-elevated** CM, which runs the Quick Drive preset and launches `acs.exe` as **its own
non-elevated child** → Steam matches.

- URL → CM `ProcessRaceQuick` → `QuickDrive.RunAsync(serializedPreset)` (it **runs** the race;
  the `loadPreset` flag would only *show* it). Source: `gro-ove/actools`
  `AcManager/Tools/ArgumentsHandler.Race.cs`. `presetFile=` is URL-encoded; CM does
  `File.ReadAllText(presetFile)`.
- `acmanager://` handler = `C:\Program Files (x86)\ContentManager\Content Manager.exe "%1"`.
- **`explorer.exe "acmanager://…"` did NOT work** (URL never reached CM); spawning `CM.exe` with
  the URL **did** (forwards to the running instance). UIPI allows elevated→non-elevated, so the
  forward succeeds.

**Verified facts (rig, 2026-06-16):** `acs.exe` **non-elevated**; **on track in ~3 s**; shared-memory
oracle `status=LIVE, is_in_pit=false`, physics advancing at **~333 Hz**, sustained 90 s.

## Productionized — `ContentManagerActuator` (#232 / PR #233)

`tools/ac_harness/entry_launcher.py` `ContentManagerActuator` implements the existing
`EntryActuator` Protocol; `trigger_drive` is `supported=False` so the shipped detect-and-retry loop
cold-relaunches when the (still non-deterministic, see [[menu-skip-race-and-shared-memory-oracle-2026-06-14]])
pre-drive menu-skip race loses. `make_actuator(mode)` picks `cm` vs `acs`; the daemon defaults to
`cm` on Windows (`--launch-mode`, `--cm-exe`, `--cm-preset`).

**Live daemon acceptance (elevated shell):** `/session/start` (cm) → `outcome:"driving"` →
`/sidecar/start` → external WS `hello_ack`; `/sidecar/start` before session → 409.

## Gotchas

- The shared-memory mmap **persists stale** after AC exits (frozen packet IDs read `LIVE`). Confirm
  on-track by packet **advancement**, not a single read.
- A token written by Windows `print` carries a trailing `\r`; bash `$(cat)` strips `\n` but not
  `\r` → 33-char token vs a `.strip()`ed 32-char client → daemon 401. Write tokens with no trailing
  whitespace.
- `ThreadingHTTPServer` sets `allow_reuse_address`, so a stale daemon and a new one can both bind
  9876 and race requests — kill stale listeners first.
