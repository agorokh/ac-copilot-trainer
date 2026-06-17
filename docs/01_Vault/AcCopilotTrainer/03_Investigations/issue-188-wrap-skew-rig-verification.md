---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-16
updated: 2026-06-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/188
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/delta-clock-boundary-alignment.md
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md
---

# Issue #188 — wrap-shaped same-lap teleport / lapCount–spline atomicity (rig verification)

## RESOLVED — issue #188 CLOSED 2026-06-16 (rig: `car.resetCounter` is PRESENT)

Ran the empirical pass **directly on the rig** (`AG_PC` / `100.75.251.87`) in an
autonomous-deliver session running on the rig itself — no SSH needed. Instrumented a one-time
`WRAP-SKEW-PROBE` in the live (symlinked) trainer, launched AC into a Magione HOTLAP via Content
Manager, and read live CSP `ac.StateCar`:

```
2026-06-16T20:21:48 [Lua: app] [COPILOT][WRAP-SKEW-PROBE] resetCounter present=true value=2
```

**`car.resetCounter` is present on this rig's CSP build** (`csp_helpers.safeCarField(car,"resetCounter")`
→ `2`, a real number). Trainer confirmed live alongside the probe (`RT-DIAG primary=ON PACE`,
`trace=2000`, `trackLen=2456`; coaching/timing/tyre overlays rendered on-screen).

**Decision (per the operator's [own criterion](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4713106661)):**
resetCounter present → teleports fully handled by the `teleported` signal → **close as moot.**
The one-frame deferred `delta.rollingResetDecision()` path from #199 is **defensive-only** for
hypothetical resetCounter-less CSP builds; it is dormant on this rig. Close comment:
[#188#issuecomment-4725615887](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4725615887).

**Q2 (frame-level spline/lapCount skew) is MOOT here** and was intentionally NOT pursued: it only
governs the resetCounter-less fallback, which does not execute on this rig — and there is no
resetCounter-less build here to characterize the skew against. If a future resetCounter-less build
ever shows `lapCount` lagging a wrap-shaped spline rewind by **>1 frame**, file a fresh follow-up to
widen `pendingWrapResetLapCount`.

The probe was a throwaway diagnostic (reverted after capture — not shipped). To re-run on a future
build, re-add the one-time `ac.log` after `resetCounterNow` is computed in
`ac_copilot_trainer.lua` `script.update`.

---

## Historical context (pre-resolution, kept for the record)

**Code path: SHIPPED** in PR [#199](https://github.com/agorokh/ac-copilot-trainer/pull/199)
(`delta.rollingResetDecision`, `state.pendingWrapResetLapCount`). The defensive branch for
CSP builds lacking `car.resetCounter` is on `main`.

**Empirical rig question (was open until 2026-06-16 on-rig pass).** Prior macOS sessions could
not observe live AC/CSP:

| Check attempted | Result |
|-----------------|--------|
| Tailscale ping `pc` (`100.75.251.87`) | Reachable (~5 ms RTT) |
| SSH `arseny_gorokh@100.75.251.87` | `Permission denied (publickey,keyboard-interactive)` |
| Sidecar WS `:8765` | Timeout (AC/sidecar not running or not bound externally) |
| WinRM `5985/5986` | Closed |

## What the issue still needs (operator-grade)

1. **`car.resetCounter` presence** on the rig CSP build (`csp_helpers.safeCarField`).
   - If **present** → teleports are fully handled; close #188 as defensive hardening shipped.
   - If **absent** → deferred wrap path from #199 is the production behavior; still close after
     skew probe below confirms one-frame deferral is sufficient.

2. **Frame-level skew at s/f** — log any frame where `splinePosition` wraps high→low with
   `lapCount` unchanged that is **not** a teleport:
   - **Atomic (same frame lapCount increment)** → optional follow-up to drop `likelyWrap` for
     the rolling-reset path (not required while #199 deferral is harmless).
   - **One-frame lag** → #199 deferral is correct; close #188.
   - **>1 frame lag** → extend `pendingWrapResetLapCount` window with live evidence.

## Recommended rig procedure (5 minutes)

Run **on `pc` (AG_PC)** with the trainer symlink live (`apps/lua/AC_Copilot_Trainer` → repo).

1. Launch AC + enter a hotlap on any track; drive **≥2 clean laps** (or use
   `python -m tools.ac_harness.lap_driver` if Custom AI is enabled).
2. In CSP log / `Documents/Assetto Corsa/logs`, grep:
   ```powershell
   Select-String -Path "$env:USERPROFILE\OneDrive\Documents\Assetto Corsa\logs\*.txt" `
     -Pattern "WRAP-SKEW-PROBE|resetCounter"
   ```
   *(If probe logging is not yet merged, use `tools/ac_harness/dump_schema.lua` with
   `resetCounter` + `lapCount` in `CAR_CANDIDATES` and re-run one session.)*
3. Record:
   - `resetCounter=present` vs `absent`
   - Any `defer` / `resolve` lines at lap boundaries (wrap-shaped jump → next-frame lapCount)

## Circumstantial evidence (not sufficient to close alone)

[`autonomous-drive-live-verified-2026-06-16`](autonomous-drive-live-verified-2026-06-16.md):
full Magione lap with **persistent real-time coaching** (`T1 — ON PACE`) and `completedLaps`
0→1. If `likelyWrap` falsely fired `resetRollingDrivingState` every lap without `resetCounter`,
coaching/session would wipe at each s/f crossing — not observed. This supports (but does not
prove) atomic updates or a working deferral/resetCounter path.

## Unblockers for the next agent

- SSH public key for `pc`, **or** run the procedure above locally on the rig and paste grep
  output into #188.
- Optional: merge pending `WRAP-SKEW-PROBE` `ac.log` instrumentation (branch
  `feat/issue-188-rig-skew-probe`) for deterministic log capture on the next drive.
