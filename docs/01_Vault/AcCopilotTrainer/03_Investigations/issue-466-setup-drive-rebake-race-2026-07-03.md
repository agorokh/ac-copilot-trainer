---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-03
updated: 2026-07-03
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/menu-skip-race-and-shared-memory-oracle-2026-06-14.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/466
---

# #466 — the `--setup` overlay stall is the setup re-bake ↔ CM immediate-start race

`/autonomous-deliver 466` on the rig (AG_PC), 2026-07-03. PR #482 (advances #466; keeps it open).

## Reconciliation (the issue body was stale)
#466's body described a direct-`acs.exe` relaunch skipped by CSP `[BASIC] FORCE_START`. **Merged #465
abandoned that** (repo-wide: no `force_start`/`gui.ini` writes) for a de-elevated CM launch +
Documents-only `race.ini` re-bake. All findings below are anchored to that evolved code — not the body.

## The real failure mode
`_wait_live` reports LIVE the instant `status==LIVE` + physics advance, but AC can sit at the frozen
"0 seconds" pre-drive overlay WITH LIVE + advancing physics (the `_minimize_foreground_window` note).
LIVE but not drivable; the carcsw hijack (CSP creating `Car0`) is the only deterministic "drivable"
signal. Old `rig_hijack` burned the full 25 s `hijack_timeout` + 7 s settle per stalled cycle.

## Root cause (in-sim, decisive)
- **no-setup** CM launch auto-starts + hijacks **reliably** (LIVE + hijacked, cycle 1).
- **`--setup`** stalls at the overlay **every** cycle. The only difference is the `race.ini` setup re-bake.
- Cadence sweep (via new `--setup-rebake-interval`): `0.05 s` default → setup APPLIED (fuel matched)
  but auto-start BROKEN; `≥0.1 s` → auto-start preserved but setup NOT applied (write lands after
  acs's spawn-read). **No cadence resolves it** (sharp ~0.05→0.1 s transition). The setup-apply write
  races acs's spawn-read that CM's immediate-start depends on.
- A post-hijack `SimState.restart_session()` does **not** re-read the setup (fuel 30→30, expected 45).
- Keypress nudge: the #482 cursor reviewer caught that it fired keys without verifying focus (a
  background/elevated process hits Windows foreground-lock → keys hit the wrong window — the real
  reason the first nudge "failed", which I'd mis-attributed to CSP). Fixed (`AttachThreadInput` +
  `GetForegroundWindow()==hwnd` verify). Re-tested: even with AC **correctly focused**, Enter/Space
  do **not** clear the CSP overlay — genuinely verified now (only `FORCE_START` skips it, #465). So
  the nudge was **removed** (not shipped as dead code); the fast-fail relaunch is the only recovery.

Conclusion: you cannot inject a setup via `race.ini` **and** preserve CM's immediate-start on the same
launch. This is the fundamental #461/#465 timing race, now characterized (not a mystery).

## Shipped (PR #482, verified in-sim)
- **Overlay fast-fail** (`rig_hijack` short `--hijack-probe-seconds` probes): a stall recycles in ~15 s
  not ~32 s (#466 criterion b). Per-cycle `[auto-drive]` logs + re-bake stats + `--setup-rebake-interval`.
- **No-setup DRIVE path reliable.** Keypress nudge kept opt-out (`--no-overlay-nudge`), documented ineffective.

## Remaining on #466 (criterion a: setup+drive ≥9/10)
Needs a different setup-injection mechanism. Top candidate: **PIT-spawn + pre-hijack in-sim
`setup.load`** (CSP `ac.setSetupSpinnerValue`) while `ac.isCarResetAllowed()` is true in the pit box —
the "must be in pits" refusal was seen at a START spawn / while a hijack held the car, and is untested
for a PIT-spawn pre-hijack load. Needs the trainer app as a loopback Lua peer. Larger than the
overlay-skip scope, so #466 stays open for it.
