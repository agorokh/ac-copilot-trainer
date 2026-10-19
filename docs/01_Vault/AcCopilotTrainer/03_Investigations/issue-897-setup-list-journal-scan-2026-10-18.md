---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-18
updated: 2026-10-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/897
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-pt-long-names-2026-10-18.md
  - AcCopilotTrainer/03_Investigations/issue-627-stable-ac-chain-2026-10-18.md
---

# #897 session-start freeze: setup.list re-streamed the whole lap journal (2026-10-18)

Operator: the picture froze for a few seconds right after go-live, on every launch, but only
with Game Point and the sidecar running. Physics kept running.

## How it was found

AC physics runs on its own thread, while rendering and every CSP Lua app share the main thread.
So the useful question was whose main-thread work held the frame. The CSP log only showed the
trainer's 3 s diagnostic timer skipping time, which didn't say whose code was responsible. A
frame-hitch watchdog (`modules/frame_hitch.lua`) answered it in one operator drive:

`[COPILOT][HITCH] gap=9.54s ours=9532ms update=9515ms u:wsInbound=9515ms`

- `wsBridge.pollInbound` was running the `setup.list` handler.
- That handler calls `setupLibrary.bestForSetups`, which calls `lapRecords()`.
- `lapRecords()` streamed **every** `journal/laps/lap_*.json` through `lap_metadata.read`: 182
  archives, about 500 MB, in a OneDrive folder. #804's design validates the full framing of each file.
- The requests come from the tablet dash and the rig screen, at session start and on reconnect.

## Fix — PR #898 (`cb9304d`)

`journal/lap-metadata-index.json` is kept in memory and on disk, keyed by archive name and size.
Archives are immutable once written, so each one is projected once, ever. The directory is still
scanned on every request: new laps appear and deleted ones drop out. Unreadable archives are
retried. A corrupt index is rebuilt. The index is swapped by moving the old file aside, so a
failed swap never leaves no index.

Diagnostics that stay in the product:
- `[COPILOT][HITCH]` for any frame of 0.25 s or longer, with the trainer's share by section,
  capped at 40 lines per session.
- `[COPILOT][WS-SLOW]` for any request handler of 100 ms or longer.

## Evidence (harness `auto_drive`, Spa, Game Point sidecar)

| Run | `setup.list` | HITCH |
|---|---|---|
| Operator drive, old `main` | 9.5 s | `gap=9.54s` |
| Launch 1, index cold | 3.8 s once | `gap=3.82s` |
| Launch 2 (PR head) and launch 3 (deployed `main`) | 5 replies, each under 100 ms | none |

## Lessons

- Instrument the main thread before theorising. One log line split "ours vs CSP vs Python apps"
  after an hour of log archaeology had not.
- Handlers on the WS dispatch run on AC's main thread. Anything that touches the journal must be
  bounded or cached.
- The harness closes AC with a forced kill, and `acs.exe` then exits with code `1`. An
  exit-code watcher (`.scratch/hitch/acs-exit-watch.ps1`) tells a kill from a crash.

## Open

One operator drive ended with `acs.exe` gone mid-lap: no clean exit, no crash report, no Windows
event, and the wheel kept its force feedback. No harness, Stable AC or Game Point action was in
flight. The cause is unknown. Capture the exit code on the next repro.
