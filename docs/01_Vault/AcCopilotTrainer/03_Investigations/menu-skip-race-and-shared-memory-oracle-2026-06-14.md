---
type: investigation
status: active
created: 2026-06-14
updated: 2026-06-14
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/154
relates_to:
  - AcCopilotTrainer/03_Investigations/_index.md
  - AcCopilotTrainer/03_Investigations/garage-to-track-autonomous-entry-2026-06-13.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
---

# Investigation: the pre-drive menu-skip is a timing/state RACE (no config knob) + the shared-memory oracle (EPIC #154)

## The question
Why does CSP/AC "start session immediately" land on the track sometimes and sit on the
pre-drive Drive/Setup/Exit menu other times — same car/track — and how do we make autonomous
on-track entry deterministic? (Operator hunch: "depends on how I ended the previous race.")

## Conclusion (cross-confirmed vs Content Manager open source + CSP changelogs; workflow `wojtj94jq`)
- **It is a timing/state race, not a setting. There is NO CSP/CM config knob.**
  `acc-extension-config/.../general.ini` has no immediate-start key. CM's
  `GameWrapper.PrepareRaceModeImmediateStart` early-returns when `PatchHelper.IsActive()` —
  i.e. **with CSP active, CM delegates the skip to CSP's new-menu system**, so the CM
  Settings → Drive → "Start session immediately" toggle does nothing more.
- **Why it flips run-to-run:** the skip is edge-triggered on AC going LIVE (first physics
  packet, `AC_STATUS` PAUSE(3)→LIVE(2)) *while* CSP's new menu is mounted and ready to
  auto-confirm Drive. Load-time jitter shifts those two events, so the auto-Drive is
  sometimes dropped. **It also depends on prior pit state** (operator hunch CONFIRMED): both
  CM (`ImmediateStart.SetSharedListener` re-issues StartGame until `IsInPits` is false for >5
  reads) and CSP (teleports the car back to pits if the menu opens <5 s before a start) key
  off pit state, so ending in-pit vs. Esc-mid-lap vs. session-restart changes the outcome.

## The deterministic recipe — detect-and-retry keyed on shared memory
Stop treating the skip as fire-and-forget. Mirror CM's own battle-tested loop:
1. **Normalize prior state:** `SPAWN_SET=PIT` + cold `acs.exe` restart (or return to pits)
   between runs, so the state-dependent branch is constant.
2. **Detect** via `acpmf_graphics` (`AC_STATUS` + `IsInPit`) and `acpmf_physics` (packetId
   advancement) — "driving" = LIVE + not-in-pit + advancing, sustained.
3. **Retry** the Drive trigger while stuck; quit+relaunch on timeout.

## What shipped (the DETECT half) — #175 / PR #176
`tools/ac_harness/shared_memory.py`: pure `parse_graphics`/`parse_physics` + a
`DrivingEntryDetector` state machine (CI-tested, any OS) + a Windows `OpenFileMappingW`
reader + a stdlib live-probe CLI. Subtleties locked in by adversarial review + a rig smoke test:
- **Require an OBSERVED packetId change** before treating physics as "advancing" — a single
  frozen sample must not let a fast poll accumulate false-clear reads (false-driving on a
  stalled sim).
- **Gate stagnation only when physics is present this frame** — a physics page that
  disappears mid-session must not wedge the detector via a stale timestamp.
- **64-bit ctypes:** `OpenFileMappingW`/`MapViewOfFile`/`UnmapViewOfFile`/`CloseHandle` MUST
  have `argtypes` declared or a 64-bit pointer overflows the default C-int and raises
  `OverflowError` (crashed `close()` until fixed). `restype=c_void_p` returns Python
  `int`-or-`None`, so `if handle:` is the correct NULL check (a `.value` access would fail).
- **Open-existing-only** (not `mmap.mmap(-1, tagname=…)`, which would page-file-*create* the
  section, read zeros when AC is down, and risk clobbering AC's own telemetry).

## Verified on the rig (operator-grade)
Live-probe opened the real `Local\acpmf_graphics`/`acpmf_physics` (they persist stale after a
session), decoded `status=OFF` + plausible packet ids, and the detector correctly refused to
declare driving on the frozen packets, closing cleanly. **Still pending one live drive:**
confirm `IsInPit` flips true→false at offset 160 and `AC_STATUS` flips 3→2. The agent cannot
launch AC itself (elevated-harness/Steam-integrity constraint) → operator-gated.

## Follow-up
- **#177** — the ACTUATOR half (detect-and-retry launcher). Operator decision surfaced there:
  ViGEm `__CM_START_SESSION` pulse (vault flags ViGEm "last resort") vs. pit-state
  normalization + cold restart. `stuck_in_menu` was intentionally NOT shipped in #175 — its
  contract is ambiguous and belongs with the actuator.
