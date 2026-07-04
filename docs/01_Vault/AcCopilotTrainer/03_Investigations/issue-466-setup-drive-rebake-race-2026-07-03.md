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

## Criterion (a) is a FUNDAMENTAL limitation - every setup-injection layer closed (2026-07-03)

`/autonomous-deliver 466` continued: operator approved trying FORCE_START (hygienic), then CSP-Lua.
Both refuted in-sim. Criterion (a) (reliable `--setup` + drive) is a **fundamental limitation** of
this AC/CSP/CM stack, not a missing mechanism. The setup-injection half works (fuel-verified
repeatedly); the overlay-skip half works (no-setup). They **cannot coexist**: setup application needs
a PRE-LIVE / resettable state, and CM's immediate-start (the only reliable overlay-skip) precludes it.
Every layer, verified in-sim:

| Layer / mechanism | Result | Evidence |
|---|---|---|
| race.ini re-bake (cadence sweep) | No sweet spot | 0.05s applies setup but breaks auto-start; >=0.1s preserves auto-start but misses setup (#482) |
| race.ini + CSP `[BASIC] FORCE_START` (install-tree gui.ini) | **FORCE_START does NOT skip the overlay** | 0/8+ across CM-launch AND direct-acs-relaunch; `FORCE_START=1` confirmed present through acs startup + setup applied (fuel=45), overlay still stalled. The #461 "~1/5" does NOT reproduce (why #465 removed it). Snapshot/restore/self-heal hygiene proven correct but reverted with the refuted mechanism |
| race.ini suspend-inject (freeze acs, inject, resume) | suspend BENIGN, the WRITE breaks immediate-start | suspend-only (no write) -> hijack OK; suspend+write -> setup applied (fuel=45) but overlay stalled. CM reacts to the race.ini change during launch, regardless of acs being frozen |
| Read-only race.ini (block CM's wipe) | CM can't launch | LIVE=False: CM must write race.ini to launch |
| CM-native setup (cmpreset / AppData) | Dead | CM Quick Drive writes `[CAR_0] SETUP=` **empty**; no preset setup field (verified real presets); no per-car AppData setup key |
| CSP-Lua `ac.loadSetup` at car init | Blocked | `ac.isCarResetAllowed()` polled continuously 45s on START **and** PIT -> **NEVER true** (0 OK / 152 "must be in pits"). `ac.loadSetup` needs a resettable state (CSP docs + PT usage + the #91 gate); an autonomous car never has one |

**Root cause (ironclad):** setup application needs a resettable/pre-live state; CM's immediate-start
precludes it. A race.ini WRITE during the immediate-start window breaks it (CM watches the file);
CSP `ac.loadSetup` needs `isCarResetAllowed` which is never true on an autonomous launch; CM has no
native setup slot; FORCE_START does not skip the overlay on this CSP.

**Recommendation:** treat criterion (a) as a documented CSP/CM limitation. Shipped value: criterion
(b) fast-fail is merged (#482); the setup applies fine when NOT composed with a drive (`--setup`
alone is fuel-verified); use `--no-setup` for reliable autonomous drives. A real fix needs an
upstream CSP/CM change (a QuickDrive setup slot, or a resettable autonomous state) - out of harness
scope. Probes preserved: `.scratch/issue-466/{suspend_inject,readonly_race,reset_allowed_timeline}_probe.py`.
