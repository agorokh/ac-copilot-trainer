---
type: investigation
status: active
created: 2026-11-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-956-autonomous-acceptance-proposal-2026-11-12.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-13-235051Z-post-merge-pr978-native-acceptance.md
---

# Revised excluded pilot: native wheel-speed feedback

The owner explicitly authorized repairing AI driving, preregistering a revised
pilot and resuming autonomous acceptance under the same remaining rig cap.
Every admission guard remains unchanged; ordinary experiment OFF, issue956 OPEN.

## Evidence and repair boundary

Frozen prior run63ab0ac98a8b40edbb4a1180558dbb8c remains INCONCLUSIVE,0/12 scored.
Its genuine laps4/5 had front-right wheel-lock observations under high braking,
rear braking slip near-0.48 and rear positive slip up to0.39 under high throttle.
RacingDriver consumed pose/speed/RPM/gear, never wheel speed; its existing pure
slip limiter was unused. Opt-in GGV feedback now consumes the existing harness
PhysFrame reader, using strict authored compound-specific front/rear radii.
Each wheel constrains one shared brake command; either rear constrains throttle.
It only reduces planner demands, predicts briefly with bounded influence,
ramps pedal application with earlier braking lookahead, restores authority slowly
after observed clearance, and suppresses downshifts
during braking slip. Invalid, stale or reversed native packets stop the run.
No qualification, oracle, thermal, slip, completeness, native identity, #529
plant fitting, recovery, reset or raw-source policy is relaxed.

Council run18cb187214d54d108992790fd9637504 ended3/7 answered, reported quorum3/3;
advisory only. Adopted freshness, shared-actuator, hysteresis and replay limits.
Rejected unsupported macOS/launchd and learned-braking/cumulative-freeze claims:
this is Windows and immutable captured data, not an OS scheduling experiment.
Required independent review of the actual PR head still precedes native use.

## Preregistration before any revised native capture

Freeze a new opaque run ID, reviewed merged source/EXE, unchanged firmware,
oracle/rules/candidate hashes, driver source and all operational helpers before
Drive. Preserve all202 current native archives and matching durable hashes,
including both old pilots. Old outcomes are retained and never receive credit.
No input/driver tuning or pilot replacement within the new frozen registration.

Use genuine G1 first to avoid spending scarce rig time on another short pilot
when genuine admission is still impossible. G1 uses the same Porsche/Magione,
high26psi setup,36C ambient, blankets on, ABS/TC1, GGV scale0.9, max240km/h,
plant off, five timed laps and exact native ordinal window4/5. The only driving
revision is `--slip-compound-index 1`, requiring native compound readback1 and
authored radii0.34m front/0.355m rear. Retain actual governor packet/intervention
counts, path/completion and all unchanged oracle measurements. Zero recovery,
spawn teleport, relaunch, setup/session replacement or retry remains required.
Fresh same-session natural assigned-box return and authoritative zero-write
audit precede independent sealing and first candidate reveal. If genuine
admission or end-to-end pilot fails, retain it, disarm, stop INCONCLUSIVE/FAIL
as required by the adopted protocol and restore. No hidden-label actor access.

Only if G1 passes and full-unit headroom remains, run excluded T3 under the same
new registration: original17psi,36C, blankets/ABS/TC unchanged, same new feedback,
two timed laps, exact selected ordinal2. Both current-registration end-to-end
pilots must pass before any scored case. Prior short PASS cannot substitute.
Scored order/roster,12-case denominator, independent oracle,90s timer,120s TTL,
native supported pressure steps and real safety-trial requirements stay intact.
Thermal readiness is not assumed: prior front cores were about55-57C; even a
successful slip repair may still be refused by unchanged genuine-case guards.

## Resource and restoration bounds

Prior use11215.5731184s remains consumed;3184.4268816s of14400 remain before
this new lease. Clock stays stopped during diagnosis/review/build. Reserve
860.227089s for restoration, leaving at most2324.1997926s for owned operation.
Keep every existing full-unit guard (drive cap plus370s), fixed drive caps,
250s total natural-return allowance and hard owner/permission expiry. Start no
unit that lacks its full headroom; partial12-case coverage is INCONCLUSIVE.
There is no promise all12 fit. Publish the frozen run/plan hashes on956 before
capture. On stop, revoke the process-local permit, restore original config and
archive capacity, preserve/hash every raw, verify actual inactive normal/bench
paths, and release all owned apps/listeners/lock. Never auto-enable or close956.
