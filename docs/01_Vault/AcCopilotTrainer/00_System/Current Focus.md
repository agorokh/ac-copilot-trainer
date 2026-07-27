---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-07-27T01:20:00Z
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-695-qss-apex-envelope-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-693-off-rig-session0-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-675-coach-v2-phase-slots-2026-07-25.md
  - AcCopilotTrainer/03_Investigations/issue-677-esp32-polish-2026-07-25.md
  - AcCopilotTrainer/03_Investigations/issue-671-telemetry-tick-hello-gate-2026-07-25.md
  - AcCopilotTrainer/03_Investigations/issue-674-l4-l0-meta-2026-07-24.md
  - AcCopilotTrainer/03_Investigations/issue-673-atelier-parta-remainder-2026-07-24.md
  - AcCopilotTrainer/03_Investigations/pr-657-resolve-blocked-2026-07-22.md
  - AcCopilotTrainer/03_Investigations/pr-637-pause-semantics-review-2026-07-20.md
  - AcCopilotTrainer/03_Investigations/pr-626-resilient-launch-review-2026-07-18.md
  - AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md
  - AcCopilotTrainer/03_Investigations/issue-602-portaudio-fixed-layout-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-603-car-content-preflight-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-596-pit-stall-sim-death-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-596-partc-actionable-reason-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/tier3-consumer-repoint-drift-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-575-stale-app-junction-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-531-partd-live-vitals-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-570-route-registry-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-582-l3-corner-refinement-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-577-alien-selfplay-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-572-alien-pipeline-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-555-cross-worktree-rig-ownership-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-537-ac1-rig-verify-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-488-part-b-tyre-identity-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/issue-488-part-a-tier2-csp-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/issue-466-partb-setup-resolution-hardening-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/pr-444-atelier-main-dashboard-2026-07-01.md
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-394-voice-reliability-2026-06-30.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/stanley-steering-live-verified-2026-06-19.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Current focus

**Repo:** ac-copilot-trainer.

**Delivered (2026-07-26):** PR [#696](https://github.com/agorokh/ac-copilot-trainer/pull/696)
MERGED [`7702b42`](https://github.com/agorokh/ac-copilot-trainer/commit/7702b42) — #695 QSS apex
solve made envelope-feasible by construction (the binned `ay_max` step function was costing the
self-play ladder its top envelope step). Issue #695 CLOSED. Detail:
[[issue-695-qss-apex-envelope-2026-07-26]].

**Delivered (2026-07-26):** PR [#694](https://github.com/agorokh/ac-copilot-trainer/pull/694)
MERGED [`49f90f1`](https://github.com/agorokh/ac-copilot-trainer/commit/49f90f1) — #693 off-rig
launch path (SSH lands in Windows session 0; `schtasks /IT` recipe, live-verified). Issue #693
CLOSED; codify-as-script follow-up **#697** OPEN. Detail:
[[issue-693-off-rig-session0-2026-07-26]].

**Delivered (2026-07-27):** PR [#699](https://github.com/agorokh/ac-copilot-trainer/pull/699)
MERGED [`c5afa50`](https://github.com/agorokh/ac-copilot-trainer/commit/c5afa50) — off-rig recipe
fails closed rather than hanging (8.3 `ShortPath` fail-open, unvalidated `$car`/`$track` into an
executable `.cmd`, ascii-mangled non-ASCII paths, blocking-wait block split). Detail:
[[issue-693-off-rig-session0-2026-07-26]].

**In flight (2026-07-26):** EPIC [#529](https://github.com/agorokh/ac-copilot-trainer/issues/529) —
new best Magione flying lap **88.425 s** (was 92.567 s), gap to the 82.7 s TT floor 11.9% → **6.9%**.
G1 pace / G2 / G1b still NOT met; **G3 is operator-gated** (needs a human driving multiple sessions).
The untested `ggv_scale` 1.15/1.20 rungs are blocked on a **rig reboot** to clear the #627 per-boot
launch accumulator — peer `codex`/MCP processes live in session 1, so that is the operator's call.

**Delivered (2026-07-25):** PR [#687](https://github.com/agorokh/ac-copilot-trainer/pull/687)
MERGED [`13c60e4`](https://github.com/agorokh/ac-copilot-trainer/commit/13c60e43e58cdc34cb24f96dc4d5862b4690ea17)
— #675 Coach V2 successor (phase-slot RESLOT, v2 brake calibration, between-lap
`corner_advice`, off-pace reference refusal). Issue #675 CLOSED. Detail:
[[issue-675-coach-v2-phase-slots-2026-07-25]].

**Delivered (2026-07-25):** PR [#680](https://github.com/agorokh/ac-copilot-trainer/pull/680)
MERGED [`e3e427c`](https://github.com/agorokh/ac-copilot-trainer/commit/e3e427c2d2e48f2ae57130387e0a176833cd3f8b)
— #677 ESP32 polish (NVS persist, serial backpressure probe, debug screen). Issue #677
CLOSED. Live COM6: `PASS drop=0`. #86 still open for on-glass smoke. Detail:
[[issue-677-esp32-polish-2026-07-25]].

**Delivered (2026-07-25):** PR [#679](https://github.com/agorokh/ac-copilot-trainer/pull/679)
MERGED [`efca5ca`](https://github.com/agorokh/ac-copilot-trainer/commit/efca5ca11e245d0f453a2ecc46fbdbc531eb3b70)
— #671 gates `telemetry_tick` on `externalHelloAcked` via shared `isExternalReady` /
`sendClientFrame` (PR #171 contract). Issue #671 CLOSED. Detail:
[[issue-671-telemetry-tick-hello-gate-2026-07-25]].

**Delivered (2026-07-25):** PR [#682](https://github.com/agorokh/ac-copilot-trainer/pull/682)
MERGED [`7b7b00a`](https://github.com/agorokh/ac-copilot-trainer/commit/7b7b00acc725d04ba2aa74d428ba5ca7544f1c21)
— #674 L4 stint optimizer / Layer-0 env observer / META prior transfer (EPIC #529 offline
layers). Issue #674 CLOSED. Live performance gates remain on #529 (blocked on #627). Detail:
[[issue-674-l4-l0-meta-2026-07-24]].

**Delivered (2026-07-24):** PR [#681](https://github.com/agorokh/ac-copilot-trainer/pull/681)
MERGED [`333ef93a9`](https://github.com/agorokh/ac-copilot-trainer/commit/333ef93a9a39742c2926d2d6f2af35c47cc95eb1)
— #673 Racing Atelier Part-A remainder (`hud_settings` / `racing_line` tokens + coaching-overlay
cyan-panel deletion + conformance lock). Issue #673 CLOSED. Detail:
[[issue-673-atelier-parta-remainder-2026-07-24]].

**Delivered (2026-07-23):** PR [#657](https://github.com/agorokh/ac-copilot-trainer/pull/657)
MERGED [`ce70add1e`](https://github.com/agorokh/ac-copilot-trainer/commit/ce70add1edaa700fefaabb27914fbb47a2edeaa2) — #625
**driver** (honest init-perturber / overlay A/B experiment planner+analyzer). Issue #625 stays
OPEN for the physical A/B on `pc` (operator-gated Steam/NVIDIA toggles + attached stats). Detail:
[[issue-625-init-perturber-ab-prepared-2026-07-22]].

**In flight (2026-07-25):** issue [#625](https://github.com/agorokh/ac-copilot-trainer/issues/625)
physical overlay A/B — code on `main`. #529 live gates still blocked on #627. Next ICE after
#675: voice-endpoint hygiene [#672](https://github.com/agorokh/ac-copilot-trainer/issues/672)
or rig-gated #529/#627.

**Delivered (2026-07-22 PM):** PR [#647](https://github.com/agorokh/ac-copilot-trainer/pull/647)
MERGED `c5d6e909b` — #630 **Part G** (runnable freeze-forensics capture driver; 6 review rounds).
**#630 is fully delivered (Parts A–G).** The #627 night: freeze rate 6/10 at ~9.5 h uptime
(reinstall did not fix it), **3 live wedges captured** — RIPs inside the `imul 0x147B`
formatting RUNTIME_FUNCTION at sustained full-core burn (§6.1 answered), **upstream report
filed**: [acc-extension-config#622](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/622).
Next on the freeze thread: watch #622, next-boot uptime-vs-kill-count experiment, `lm` module
map in capture records; #625 overlay A/B has a peer branch in flight. Detail:
[[wedge-live-forensics-2026-07-22]].

**Delivered (2026-07-22):** PR [#659](https://github.com/agorokh/ac-copilot-trainer/pull/659)
MERGED [`cc9da82`](https://github.com/agorokh/ac-copilot-trainer/commit/cc9da82b4942f34f9f430d57091f2163694b4fde)
(#529 **P4**, issue #654 CLOSED). The optional alien scientist converts named self-play failures or
plateaus into bounded, schema-valid one-parameter setup candidates, executes them through the normal
auto-alien oracle, promotes only complete uncertainty-significant gains, and durably suppresses
measured falsified physical adjustments within the same platform/tyre/track scope. Immutable setup
and scientist-state writes are contained beneath AC Documents and fail closed on drift, redirection,
confounding, or incomplete evidence. Full parity: 3,291 passed, 89 skipped; hosted checks and the
three-thread resolution gate were green. PR [#656](https://github.com/agorokh/ac-copilot-trainer/pull/656)
already delivered P5's coachable alien frontier. **Active #529 next:** only the remaining real
Windows-rig/cross-combo performance gates. Keep #529 open until those prove a fresh combo and real
scientist/frontier value; P4/P5 code completion alone is not alien-pace evidence.

**Delivered (2026-07-22):** PR [#646](https://github.com/agorokh/ac-copilot-trainer/pull/646) MERGED
`4265845` (#630 **Parts C+D+E**): `WEDGED_INIT` verdict (init livelock no longer buckets as
`never_live`), Car0 45 s TTL re-probe (loses-drivability sessions no longer STABLE), per-attempt
`AttemptRecord` + `--trials/--no-hold/--json` measurement mode (#627 §9.2). **In flight:** #630
**Part G** — PR [#647](https://github.com/agorokh/ac-copilot-trainer/pull/647) (runnable
freeze-forensics capture driver, render-TID preference, §7.1-guarded S3; `--self-test`
rig-verified) in the resolve-pr loop. After Part G merges, #630 has only the optional
RELEASE→STABLE atomic action left; the rig payoff run remains: catch a real wedge with the
promoted instrument to settle #627 §6.1.

**Delivered (2026-07-21):** PR [#644](https://github.com/agorokh/ac-copilot-trainer/pull/644) MERGED
`012577e` (#630 **Part F**). The validated freeze-forensics instrument is no longer trapped in
gitignored `.scratch/` — it lives at `tools/ac_harness/freeze_forensics.py` (S1 cycle-time
spin-vs-block, S2 noninvasive cdb RIP, pure `classify_forensics` with 19 unit tests, including the
cdb-timeout thaw path). Issue #630 stays OPEN. **Next on #630:** Parts C (init livelock mis-bucket),
D (Car0 one-shot latch), E (per-trial record), G (runnable capture driver + render-stack TID). Rig
next: catch a real wedge with the promoted instrument to settle #627 §6.1. Detail: handoff 2026-07-21
Part F block.

**Delivered (2026-07-20):** #630 Parts A+B — PR [#642](https://github.com/agorokh/ac-copilot-trainer/pull/642)
`cea4111` (post-STABLE wedge watch + Game Point `wedged` state) and PR
[#637](https://github.com/agorokh/ac-copilot-trainer/pull/637) `5497775` (pause ≠ freeze via physics
packet). Detail: [[pr-637-pause-semantics-review-2026-07-20]].

**Delivered (2026-07-19):** PR [#629](https://github.com/agorokh/ac-copilot-trainer/pull/629) MERGED
`c5c7b75` (issue #628 CLOSED). Launcher no longer discards healthy sessions on `acpmf_*` corpse
readings — section trust is packet-based only. Detail: [[issue-628-acpmf-corpse-classify-2026-07-19]].

**Review-resolved (2026-07-18):** PR
[#626](https://github.com/agorokh/ac-copilot-trainer/pull/626) delivers issue #624's resilient
operator session launcher through Game Point, with a machine-wide lock held across the live session.
Final code commit `8c9d22d` adds finite timing enforcement at the shared rig-lock boundary,
immediate failed-Car0 attempt termination, mandatory AC teardown before a pre-stability release can
escape the unsafe-hold loop, early configured-CM path validation, and durable Stable AC ownership
metadata. **Release AC** refuses known unrelated harness owners while preserving the recovery
sentinel for unknown or legacy metadata. Final hardening clamps bounded waits, resolves relative CM
paths from the Game Point root, atomically timestamps process liveness, rechecks cleanup success,
proves unknown-owner contention cross-process, fails closed on native enumeration errors, requires
two confirmed absence snapshots before releasing ownership, and blocks invalid configured CM paths
without default-install fallback. Car0 probing now observes Release AC throughout, and a post-LIVE
handshake miss cannot advance the stale-CM restart streak. Windows mapping-close failures are fatal
and cleanup still attempts CarControls release after a read-section error; explicit non-resilient
lock owners are visible as non-green `busy_other_session` rather than healthy Stable AC. Mapped
view/handle teardown now has one shared lifecycle helper; auto-drive converts teardown faults into
structured `cleanup` failures without hiding an earlier run failure. Car0 readiness is timestamped
only after its blocking handshake and measured against the pre-probe watch start, so it cannot
stretch go-live or shorten stability. The launcher summary reports a busy unrelated owner without
offering the refused Stable AC action. Durable lock metadata now advances from `stabilizing` to
`stable` only after the sustained proof, so Game Point cannot report READY during retries. Packet
regressions fail the attempt instead of inheriting stability across an `acs.exe` recycle, and the
Car0 timeout boundary performs its intended final read. Phase updates use a non-append descriptor
and valid-record replacement; acquisition-time metadata errors roll back the OS byte lock.
Starting/stabilizing remains non-green readiness while the accepted CLI/GUI start is not reported
as a failure. Owner records are capped at 4 KiB for both reads and replacement padding, including
recovery from an oversized corrupt file. AC-session ownership/recovery copy outranks the generic
sidecar-down prompt. Process absence before the first real `acs.exe` sighting remains false, while
enumeration uncertainty and post-sighting disappearance retain fail-closed/confirmed semantics;
enumeration errors before the first real sighting no longer synthesize a false process-exit edge.
Controller teardown retries the retained native resources, then brakes, terminates, and confirms
`acs.exe` absent in two consecutive strict snapshots before a cleanup report may drop ownership.
An unconfirmed safety shutdown or failed post-safety close aborts while retaining the controller
and detaching the rig-lock ExitStack; the CLI uses immediate OS process exit so the mapping and
machine lock close together. A track/car mismatch remains the primary launch error when its cleanup
also fails; a safely completed emergency cleanup retains its existing relaunch budget and evidence.
Each resilient-launch retry resets its liveness sighting history only after the previous `acs.exe`
has been cleaned up, so normal pre-spawn absence cannot become a false exit from an earlier attempt.
Resilient Car0 probe close failure retains the controller and terminates by OS process exit without
running the normal rig-lock release `finally`; it explicitly reconfirms `acs.exe` teardown with
operator interrupts disabled before that exit. Programmatic auto-drive abort ownership lives on the
exception's detached cleanup stack rather than an unbounded module-global resource list.
Cleanup uses a separate strict process oracle: enumeration uncertainty triggers taskkill/retry and
cannot masquerade as prior-AC absence, while the launch watcher keeps its attempt-scoped semantics.
Both resilient-launch cleanup and auto-drive's fatal controller-cleanup path now use the shared
`entry_launcher.terminate_process_tree_confirmed_absent` boundary, so taskkill, strict unknown-state
handling, bounded polling, and consecutive absence confirmation cannot drift between launchers.
That helper fails closed off Windows instead of accepting an empty unsupported-platform snapshot.
Auto-drive flushes the complete chained cleanup traceback before its required atomic OS exit, so
native teardown failures retain postmortem evidence without releasing the mapping before the lock.
Best-effort native enumeration now preserves matching PIDs already observed before a late Toolhelp
failure, while strict cleanup callers still receive the error. A failed post-proof `stable` phase
publication keeps the live AC session and lock under `stabilizing` ownership instead of destroying
the session; Game Point therefore stays honestly non-READY while the operator retains the drive.
Custom-AI native close retries now live in `custom_ai.close_controller_with_retries`; auto-drive
and the resilient Car0 probe both exhaust the same retained-resource retry budget before invoking
their persistent-failure AC safety paths. Close failures now distinguish retained CarControls
ownership from a read-only telemetry mapping: only a retained control mapping can trigger the AC
safety shutdown. The emergency safety command writes verified brake/steer fields and leaves the
explicitly unverified handbrake offset at zero.
Telemetry-only failures no longer lose their final owning reference: resilient launch retains each
read-only mapping and retries it throughout stabilization and the stable operator hold, while
standalone probes carry the controller on their cleanup exception. Auto-drive returns a structured
cleanup failure whose non-serialized report hold keeps the controller reachable for process-lifetime
cleanup, without invoking the retained-controls AC safety shutdown or atomic-abort path.
Writable mapping operations now reject an already-unmapped null view with a Python
`SharedMemoryUnavailable` error, so a handle-only partial close cannot crash the emergency-brake
path before authoritative taskkill runs.
Interrupts and other unexpected `BaseException` failures during native close attempts or the
retained-controls safety callback are converted to the launcher-specific retained-controller fatal
path. Auto-drive detaches the rig-lock cleanup stack; resilient Car0 cleanup retains its controller
for fatal AC teardown. The `AC_COPILOT_RESILIENT_LAYOUT` environment override is explicitly pinned
against the settings-file value.
Telemetry-only close failures no longer consume the remaining native hijack-probe or cached-session
relaunch budget. The rig CLI retains those read-only owners in a scoped hold list, and composed
auto-drive transfers every retained owner into its final structured report across all return paths.
Every structured return also preserves accumulated cleanup notes, including an earlier retained
telemetry-mapping warning when a later hijack attempt exits early. Readable mappings now match the
writable guard by rejecting an already-unmapped null view with `SharedMemoryUnavailable`.
The final post-safety native close converts every `BaseException` into the fail-closed cleanup
abort. That abort retains the fatal controller plus all earlier telemetry-only owners, including
owners accumulated across sim-death retries and rig CLI hijack probes, until process teardown.
A hijack cleanup that confirms AC absent and releases its native mapping consumes the remaining
launch budget instead of ending the run; its cleanup detail stays in the final report.
Fatal cleanup ignores the release sentinel before taskkill, sleeps between retries, and has a
bounded hold before atomic process exit. Content Manager must be positively enumerated and survive
its startup settle before the Quick Drive URL is issued. The existing `resilient_layout` settings
template key now has an explicit regression assertion.
Local repository parity is green at `3226 passed`, `77 skipped`, and `86.77%` coverage. The updated
head still requires its mandatory reviewer cooldown and exhaustive GitHub current-head audit. The
PR remains open and unmerged; Windows-rig verification is still pending. Detail:
[[pr-626-resilient-launch-review-2026-07-18]].

**Active (2026-07-16, autonomous run):** [#531](https://github.com/agorokh/ac-copilot-trainer/issues/531)
Phase 2+ delivery. Parts **D-remainder + E** MERGED via PR
[#615](https://github.com/agorokh/ac-copilot-trainer/pull/615)
([`de04860`](https://github.com/agorokh/ac-copilot-trainer/commit/de0486066538ac1e59486ce2219524ff9c19e27d)):
`race.status` topic (fuel-as-a-decision + reference-anchored predicted lap), `upshift`/`downshift`
cues from the learned shift profile, `audio_routing` on every cue, dash predicted row + tier-2
micro-cue slot. **Next in the same run:** P7 rig-verify from merged main (incl. the unobserved
TC/ABS intervention flash via #595), then Part F (COACH/MAP/STINT depth), Part G (native-audio
latency gate), H/I scope reconciliation. Detail: [[issue-531-parte-cues-fuel-2026-07-16]].

**Delivered (2026-07-16):** [#602](https://github.com/agorokh/ac-copilot-trainer/issues/602) is
**CLOSED** by PR [#606](https://github.com/agorokh/ac-copilot-trainer/pull/606), merge
[`a153fda`](https://github.com/agorokh/ac-copilot-trainer/commit/a153fda063490f40963e59a8a40685e8c3d263a6).
Mono/48 kHz banks negotiate fixed WASAPI layouts and map voice to front-center channel 3. Live
proof: Game Point `VOICE ENABLED` with `1ch bank -> 6ch stream/6ch max map=[3]`; WASAPI loopback
matched `Brake!` on channel 3 at score 1.0. Post-merge classification: no migration/env/deps
follow-ups. Detail: [[issue-602-portaudio-fixed-layout-2026-07-15]].

**Delivered and merged-main-proven (2026-07-15):**
[#603](https://github.com/agorokh/ac-copilot-trainer/issues/603) is **CLOSED** by PR
[#607](https://github.com/agorokh/ac-copilot-trainer/pull/607), merge
[`123a577`](https://github.com/agorokh/ac-copilot-trainer/commit/123a5774f1657ab5426ae4f90f759e844c7af800).
The harness now rejects damaged car data/LOD/KN5 chains before AC launch and records them as
explicit non-drive evidence excluded from drive and sim-death denominators. Shared car-data access
is packed-first, lazy for unpacked files, flat-member consistent, and reused by tyre specs. On
merged main, **222 focused tests passed**; real BMW packed content passed and the damaged Porsche
failed before launch with both denominator flags false. The product scope is complete; restoring
the local Porsche content remains a rig-maintenance action before the next Porsche drive. Detail:
[[issue-603-car-content-preflight-2026-07-15]].

**Delivered and live-proven (2026-07-15):** [#596](https://github.com/agorokh/ac-copilot-trainer/issues/596)
is **CLOSED** by PRs [#598](https://github.com/agorokh/ac-copilot-trainer/pull/598) and
[#600](https://github.com/agorokh/ac-copilot-trainer/pull/600) (merge
[`613fae2`](https://github.com/agorokh/ac-copilot-trainer/commit/613fae2ef4fe7ec3489800b13751f199185de7ce)).
The 450–580 m practice stall was a stationary-high-gear downshift latch; the driver can now select a
usable gear without already moving. Pure `acs.exe` deaths get one full, lock-held retry with every
attempt preserved. Seven new natural drives across two cars/two tracks had 0 deaths, 0 recovery
caps, and no stopped-high-gear samples; controlled PID death recovered to a 2,295 m PASS. Part C
keeps every failed report actionable. Full parity: **2,963 passed, 113 skipped, 87.61% coverage**.
No #596 product work remains. Detail: [[issue-596-pit-stall-sim-death-2026-07-15]].

**Review-resolved (2026-07-15, active PR):** [#595](https://github.com/agorokh/ac-copilot-trainer/pull/595)
turns #531 Part D's TC/ABS flash criterion into in-run machine evidence. `run_auto_drive` now opts
its tap into the `observer` client class required for `telemetry_tick` fan-out; reports preserve
`true` / `false` / `absent` per flag so a missing CSP field cannot masquerade as an idle system.
Functional-head CI, resolve-gate, GraphQL threads, and the self-hosted review were clean; the
resolution branch merged current `main`, passed **211 focused tests**, and finished full parity at
**2,961 passed, 77 skipped, 86.85% coverage, `ci-fast: OK`**. Remaining real-world proof:
deliberately provoke TC or ABS and observe a positive `true` count in `report.json`. Detail:
[[issue-531-partd-live-vitals-2026-07-14]].

**Delivered (2026-07-15, latest):** [#575](https://github.com/agorokh/ac-copilot-trainer/issues/575)
**CLOSED** by PR [#587](https://github.com/agorokh/ac-copilot-trainer/pull/587)
([`b51e1d5`](https://github.com/agorokh/ac-copilot-trainer/commit/b51e1d5)) — harness preflight now
detects a **stale AC app junction**: it compares the installed trainer app against the harness's own
`src/ac_copilot_trainer` by **content digest** (not commit — two checkouts can share a HEAD and still
differ), measured **under the rig lock**, and records `extras.run.app_install` in every evidence
bundle. Four states (`match`/`drift`/`absent`/`unverifiable`); `--strict-app-version` fails on drift +
unverifiable, never on absent. With [#569](https://github.com/agorokh/ac-copilot-trainer/issues/569)
(`8a895ee`) the stale-build problem is now closed on **both** halves — frozen EXE and Lua app.

**Live-proven, and still true:** the rig junction moved **three times during that session** (primary →
#531's worktree carrying an uncommitted `telemetry_publisher.lua` edit → restored), with both
worktrees at the **same commit**. The junction is volatile shared state; do not repoint it while
another session owns the rig ([#555](https://github.com/agorokh/ac-copilot-trainer/issues/555)).
Detail: [issue-575-stale-app-junction-2026-07-15.md](../03_Investigations/issue-575-stale-app-junction-2026-07-15.md).

**Previously delivered (2026-07-15):** [#570](https://github.com/agorokh/ac-copilot-trainer/issues/570)
**CLOSED** by PR [#585](https://github.com/agorokh/ac-copilot-trainer/pull/585)
([`2dbf7d8`](https://github.com/agorokh/ac-copilot-trainer/commit/2dbf7d8)) — the sidecar's
`/health` endpoint advertisement is now **derived** from the `server._ROUTES` registry that also
drives dispatch, so a route can no longer be served without appearing in `/health` (no
`advertise=False` opt-out exists). Exact-before-prefix dispatch; import-time registry validation.
Found en route: the parallel structure had **already drifted** — 4 paths were routed but
unadvertised (`/healthz`, `/voice/clips/`, `/voice/dispatches`, `/voice/echoes`); advertised set
6 → 9. Live-proven on merged main (`build_commit: 2dbf7d8`): all 9 routes serve, `/health`
reconciles against source, real font 200/82956 B, unrouted → 426. Detail:
[[issue-570-route-registry-2026-07-15]].

**Prior (2026-07-15):** [#582](https://github.com/agorokh/ac-copilot-trainer/issues/582)
**CLOSED** by PR [#583](https://github.com/agorokh/ac-copilot-trainer/pull/583)
([`b2ef740`](https://github.com/agorokh/ac-copilot-trainer/commit/b2ef740)) — **EPIC #529 Layer 3**
corridor-constrained per-corner refinement (the #577 item-3 follow-up). Evidence-gated relaxation
of measured low-variance grip bins toward the posterior mean under a hard z=1.0 stability floor;
QSS-pinned interior re-solve; named per-corner reverts; same artifact/provenance/verify gates.
Live merged-main proof: `auto-alien: OK`, 107.0 → 101.7 → **96.621 s**, all stages VALID; all 7
Magione corners honestly reverted (no measured corner-speed lateral bins yet) — gain unlocks as
the self-play ladder flips those bins to measured. Detail:
[[issue-582-l3-corner-refinement-2026-07-14]].

**Prior (2026-07-14):** [#577](https://github.com/agorokh/ac-copilot-trainer/issues/577)
**CLOSED** by PR [#579](https://github.com/agorokh/ac-copilot-trainer/pull/579)
([`5b8fe0a`](https://github.com/agorokh/ac-copilot-trainer/commit/5b8fe0a51f6df3dc3ecaef1a39d4a8138de67ee9)) — **EPIC #529 P3** flying-lap windows plus
progressive-envelope self-play. Direct and composed `--laps N` runs share a bounded multi-lap
budget; iteration evidence is provenance-bound, strictly monotone, peer-safe, and fail-closed on
falsification or persistence errors. Live rig proof: 911 GT3 R @ Magione flying laps
**107.009 → 101.642 → 96.624 → 92.567 s**, all AC-valid with zero recoveries. Final local parity:
**2,865 passed, 77 skipped, 86.68% coverage**; merged-main CI and conformance are green. Post-merge
classification reported no migration, environment, dependency, workflow, or other operator action.

**Tracking truth:** GitHub auto-closed #577 at merge, but issue-body item 3 (corridor-constrained L3
per-corner refinement) did **not** ship in PR #579. Before implementing that work, explicitly reopen
#577 or create a non-overlapping follow-up issue; do not infer delivery from the CLOSED state.
Detail: [[issue-577-alien-selfplay-2026-07-14]].

**Delivered (2026-07-14, latest):** [#572](https://github.com/agorokh/ac-copilot-trainer/issues/572)
**CLOSED** by PR [#573](https://github.com/agorokh/ac-copilot-trainer/pull/573)
([`dfd4b7e`](https://github.com/agorokh/ac-copilot-trainer/commit/dfd4b7e)) — **EPIC #529 P2**:
one-button alien pipeline (`python -m tools.ac_harness.auto_alien`), plant-ID → optimized
min-curvature line → QSS → drive with per-combo, provenance-gated line cache. Live-proven on the
rig (AC-valid lap, zero recoveries). Active EPIC #529 focus moves to G1 on unseen combos, then P3.
Detail: [[issue-572-alien-pipeline-2026-07-14]].

**Delivered (2026-07-15):** [#569](https://github.com/agorokh/ac-copilot-trainer/issues/569)
**CLOSED** by PR [#586](https://github.com/agorokh/ac-copilot-trainer/pull/586)
([`8a895ee`](https://github.com/agorokh/ac-copilot-trainer/commit/8a895ee)). Completes **H1** of
the #567 hardening plan: a packaged EXE now reports a real `build_commit` **and** `build_time` on
`/health` (was `"unknown"` — the frozen binary has no `.git`). Bake = a generated PyInstaller
`--runtime-hook`, which runs before the entry script; since the launcher re-spawns *itself* for
the sidecar child, the child inherits it with no propagation logic. **Live-proven on merged
main**, not on the branch: frozen EXE → `build_commit: "8a895ee-dirty"`,
`build_time: "2026-07-15T03:00:59Z"`, `endpoints` = 9 routes (composes correctly with #570's
registry, which landed 24 min earlier), `GET /tablet/dash` → 200. Counterfactual proven with a
no-bake frozen probe (`unknown`). Detail + rig gotchas:
[[issue-569-frozen-build-identity-bake-2026-07-14]].

**Delivered (2026-07-14, prior):** [#567](https://github.com/agorokh/ac-copilot-trainer/issues/567)
**CLOSED** by PR [#568](https://github.com/agorokh/ac-copilot-trainer/pull/568)
([`ae54ce9`](https://github.com/agorokh/ac-copilot-trainer/commit/ae54ce9)). Tablet GT dashboard
"not connecting" root-caused live (stale packaged EXE that 426'd `/tablet/dash` + no self-healing
`adb reverse` tunnel) and fixed: stale-build detection (`/health` `build_commit`/`endpoints`,
`--self-test` ground-truth `GET /tablet/dash==200`), a self-healing `adb reverse` keeper
(`tools/rig_launcher/tablet_tunnel.py`, opt-in `AC_COPILOT_MANAGE_TABLET_TUNNEL`), thread-safe
supervisor, and read-only off-thread GUI polling. 13 review rounds (two real gating HIGHs fixed);
`make ci-fast` green. Rig-pending: ~~rebuild the EXE~~ (done 2026-07-15 under #569 — `dist/` now
holds a fresh merged-main build serving `/tablet/dash` 200, replacing the stale Jul-2 binary) +
`--self-test` + one managed launch to confirm plug-in-and-connect. Follow-ups: #569 **CLOSED**
(above), #570 **CLOSED** (PR #585). Detail:
[[tablet-dash-connection-hardening-2026-07-14]].

**Delivered (2026-07-13):** [#543](https://github.com/agorokh/ac-copilot-trainer/issues/543)
**CLOSED** by PR [#564](https://github.com/agorokh/ac-copilot-trainer/pull/564)
([`3193e1b`](https://github.com/agorokh/ac-copilot-trainer/commit/3193e1b)) — uncertainty-aware
plant identification (strict AC PASS). Detail: [[issue-543-uncertainty-aware-plant-id-2026-07-13]].

**Delivered (2026-07-13, latest):** [#555](https://github.com/agorokh/ac-copilot-trainer/issues/555)
**CLOSED** by PR [#563](https://github.com/agorokh/ac-copilot-trainer/pull/563)
([`a195b38`](https://github.com/agorokh/ac-copilot-trainer/commit/a195b3826dcaffa058fbd55f133ea03974ee758a)).
CM logs disproved the earlier “crash-respawn” diagnosis: concurrent worktree Quick Drive requests
were replacing the live machine-global AC session. A LocalAppData OS lock now serializes every
worktree, while stable `acs.exe` PID monitoring distinguishes `session_replaced` from `sim_dead` and
closes stop/missing-telemetry sampling races. Live proof: competing harness rejected without
disturbing the owner; R8/Magione 3/3 pre-merge plus 1/1 merged-main PASS. The merged run completed
one lap / 2665.5 m / 191.8 km/h with stable PID 12004 and both failure flags false. Detail:
[[issue-555-cross-worktree-rig-ownership-2026-07-13]].

**Delivered (2026-07-13, latest):**
[#532](https://github.com/agorokh/ac-copilot-trainer/issues/532) **CLOSED** after live-state
reconciliation. Part A shipped in PR [#535](https://github.com/agorokh/ac-copilot-trainer/pull/535)
(`b023c92`); Part B shipped in PR [#551](https://github.com/agorokh/ac-copilot-trainer/pull/551)
(`155aac6`). The final Magione closed-loop acceptance pass is complete: generic plant
**108.447 s** versus identified plant **107.781 s**, both AC-valid. The stale Content Manager
failure found during verification was fixed in PR
[#559](https://github.com/agorokh/ac-copilot-trainer/pull/559) (`2cfd662`). Fresh focused
verification on current `origin/main`: **217 passed** across the plant-ID, GGV-profile, and
auto-drive suites. Detail: [[issue-532-partb-friction-id-2026-07-13]].

**Delivered (2026-07-13, earlier):** PR
[#547](https://github.com/agorokh/ac-copilot-trainer/pull/547) **MERGED**
([`9265521`](https://github.com/agorokh/ac-copilot-trainer/commit/92655217a0278214569abb3be5520258616d2398))
— **#531 Phase 1**: the tablet GT dashboard is LIVE on the real PRITOM P7 in Fully Kiosk
fullscreen at `/tablet/dash` (USB `adb reverse tcp:8765`) — car-adaptive electronics from real
per-car spinner ranges, woven coaching (BRAKE-takeover lane), honest LIVE/STALE/WAITING states.
Design artifacts landed on main with it.
[#531](https://github.com/agorokh/ac-copilot-trainer/issues/531) stays OPEN for Phase 2+
(Parts D–I) and the live in-sim acceptance pass. Node:
[[issue-531-phase1-tablet-dash-2026-07-13]].

**Delivered (2026-07-13, earlier):** PR
[#551](https://github.com/agorokh/ac-copilot-trainer/pull/551) **MERGED**
([`155aac6`](https://github.com/agorokh/ac-copilot-trainer/commit/155aac6ec24611212fbbb6b8bfb9cf7adf498a8a)),
closing [#552](https://github.com/agorokh/ac-copilot-trainer/issues/552). Plant identity now includes
track layout end-to-end (artifact path/save/load, handshake result, driver construction, CLI lookup),
with exact legacy naming for `layout=None` and hard A/B isolation. Merged-main filesystem proof
observed separate legacy/GP/short artifacts and a `None` short lookup while only GP existed. PR #551
also landed the #532 Part-B per-combo friction-ID core and review hardening. The distinct rig-only
full-lap A/B criterion was subsequently verified and #532 is now closed (see the latest entry).

**Delivered (2026-07-13, rig session):** Harness reliability —
[#537](https://github.com/agorokh/ac-copilot-trainer/issues/537) **CLOSED**. AC #2 = PR
[#544](https://github.com/agorokh/ac-copilot-trainer/pull/544)
([`41f4d53`](https://github.com/agorokh/ac-copilot-trainer/commit/41f4d53)) bounded relaunch on
cached-session mismatch; **AC #1 live-verified on the rig** (`AG_PC`, session ran there — the
macOS→rig SSH blocker was moot): clean consecutive hands-off pair, 911 GT3 R, **magione PASS then
spa PASS**, the relaunch loop absorbing 2+1 pre-drive overlay stalls, `acpmf_static.track` matched
per leg (#535 guard), HUD tiles MAGIONE/SPA inspected. Evidence:
[#537#issuecomment-4956636834](https://github.com/agorokh/ac-copilot-trainer/issues/537#issuecomment-4956636834).
Found en route → [#555](https://github.com/agorokh/ac-copilot-trainer/issues/555), now closed by
#563: CM logs showed concurrent-worktree Quick Drive launches, not crash-respawn; the R8 content
hypothesis was refuted by four clean R8/Magione runs.
[[issue-537-ac1-rig-verify-2026-07-13]] · [[issue-537-cm-cached-track-relaunch-2026-07-13]].

**Prior focus (2026-07-13):** Coaching QUALITY —
[#522](https://github.com/agorokh/ac-copilot-trainer/issues/522) V2 remains the only open scope.
PR [#538](https://github.com/agorokh/ac-copilot-trainer/pull/538) **MERGED**
([`20f68cb`](https://github.com/agorokh/ac-copilot-trainer/commit/20f68cb)) closed
[#527](https://github.com/agorokh/ac-copilot-trainer/issues/527): the `semantic_timeliness`
coverage gate now counts only **coachable** brake zones (onsets within 50 m of a reference mark;
off-zone correction dabs excluded, repeat dabs collapsed), an occurrence is coached iff it drew an
ACTIONABLE cue, with deterministic `corner+1` dispatch binding + time-local onset binding
(rejects stale cross-lap). Verified on the real #525 rig taps: metric stabilised from noisy
78/75/89% (raw) to clean 4/4, 3/4, 4/4 (coachable zones). The residual main-tap3 3/4 is a genuine
dropped-heads-up pass = **#522-V2** phase-slot scheduler scope. Detail:
[[issue-527-coachable-brake-coverage-2026-07-12]].

**Prior focus (2026-07-12, latest):** Coaching QUALITY —
[#522](https://github.com/agorokh/ac-copilot-trainer/issues/522) V2 (the only remaining
scope). PR [#525](https://github.com/agorokh/ac-copilot-trainer/pull/525) **MERGED**
([`56048ae`](https://github.com/agorokh/ac-copilot-trainer/commit/56048ae)) closed parts 1-2:
every gate-grade brake zone coached (marks 5 → 8 on the Magione reference; per-zone observer
state + zone-aware voice dedup) and per-driver brake-mark calibration (per-zone EMA of the
driver's own onsets, 50 m metric tolerance, wrap/layout/order-guarded). LIVE-VERIFIED
pre-merge: `--assert-coaching` exit 0 twice, coverage 80%/89% (was red 78%), junk 0,
`mark_source: driver_calibrated` on the wire. Remaining: V2 phase-slot scheduler + Ollama
`corner_advice` between-lap point + coach-v2-runtime calibration. Detail:
[[issue-522-parts12-coverage-calibration-2026-07-12]].

**Delivered (2026-07-12):** PR [#539](https://github.com/agorokh/ac-copilot-trainer/pull/539)
**MERGED** ([`e0b5eef`](https://github.com/agorokh/ac-copilot-trainer/commit/e0b5eef)) — **#528
CLOSED** (the standing "autonomous driver stalls near pit start" flake). `auto_drive` FAILed ~1/3
of pit-start launches via a recovery-to-pit-trap loop (`spawn_teleport=failed`, recovery cap at
0 m): a car OFF the racing line was recovered only by `teleport_to_pits` — the same trap. Fix:
`rig_drive` tracks a mutable `off_line` state (set at an off-line spawn AND after any
`teleport_to_pits`; cleared on a successful line teleport) and RETRIES the racing-line teleport on
recovery whenever off-line — closing the mid-lap-spin-into-pits re-entry too. Pure
`should_try_line_teleport_on_recovery` (honors `--no-spawn-line`) + `drive_leg_succeeded`; both
failure shapes now labeled false-green-KPI regression scenarios (15 broken / 9 healthy / 0 leaks).
Hardened over 3 review rounds (self-hosted cursor HIGH+MEDIUM, codex P2). **Live rig verification
PENDING** — rig saturated by 5+ concurrent sessions at merge; run repeated `auto_drive` launches
when free. Detail: [[issue-528-pit-start-stall-recovery-2026-07-12]].

**Prior focus (2026-07-12, later):** Coaching QUALITY —
[#522](https://github.com/agorokh/ac-copilot-trainer/issues/522) remaining parts. PR
[#523](https://github.com/agorokh/ac-copilot-trainer/pull/523) **MERGED**
([`56dd3a4`](https://github.com/agorokh/ac-copilot-trainer/commit/56dd3a4)) — operator verdict
("Brake arrives 4 s late — useless") measured (0/8 actionable), root-caused (0.8 s lead vs a
3.2 s audibility budget; reactive act tier unfixable in principle; synthetic 77.8 s reference),
and fixed: one calm heads-up per pass, silence past the mark, exit debrief, `semantic_timeliness`
gate. Live-proven junk 8 → 0 on identical laps. Detail:
[[issue-522-actionable-coaching-2026-07-12]].

**Prior focus (2026-07-12, earlier):** Tablet voice hardware verification for
[#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) /
[#511](https://github.com/agorokh/ac-copilot-trainer/issues/511) Part D. PR
[#519](https://github.com/agorokh/ac-copilot-trainer/pull/519) **MERGED**
([`fb54b9d`](https://github.com/agorokh/ac-copilot-trainer/commit/fb54b9d)) — `coaching.voice`
dispatch broadcast, sidecar-served tablet WebAudio page (USB `adb reverse`, no WiFi),
`voice.echo`/`voice.demo`, and the `audible_latency` chirp/matched-filter harness. Live smoke
green on the real stack. **Blocked only on the tablet's physical "Allow USB debugging" tap**;
then: burst measurement → autonomous drive (Magione + 911 GT3 R) → per-cue timeliness evidence
on #381 → operator A/B listen via tablet earpiece. Detail:
[[issue-511-partd-tablet-voice-endpoint-2026-07-11]].

**Prior state:** Awaiting next focus selection (see RESUME block in `Next Session Handoff.md`). EPIC
[#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) (autonomous self-test harness) is now
**CLOSED** (2026-07-11) — Closure Criterion met. EPIC
[#488](https://github.com/agorokh/ac-copilot-trainer/issues/488) (telemetry capture completeness for ML)
is **FULLY DELIVERED** and closed via PRs #497 (Part A), #500 (Part B), and #503 (Parts C & D).

**Delivered (2026-07-12):** PR [#516](https://github.com/agorokh/ac-copilot-trainer/pull/516)
**MERGED** ([`49af0a7`](https://github.com/agorokh/ac-copilot-trainer/commit/49af0a7)) — **#515**
harness lap-archive evidence fix, surfaced by the live SF-26 @ Silverstone GP verification of the
#512 harness. Post-lap grace-drive + full-tap-window drive budget + multi-dir archive poll so
`report.lap_archives` populates on a driven lap. Live-verified from merged main (`lap_archives=1`,
`dist=6215m`). Detail: [[issue-515-lap-archives-race-2026-07-11]].

**Delivered (2026-07-11):** PR [#513](https://github.com/agorokh/ac-copilot-trainer/pull/513)
**MERGED** ([`28185e2`](https://github.com/agorokh/ac-copilot-trainer/commit/28185e2)) — **#512**
false-green-rate KPI, the last Part-G residual → **EPIC #154 CLOSED**. New
`tools/ac_harness/false_green_kpi.py`: a CI-runnable known-failure-discrimination gate over the harness's
**real** oracles (`evaluate_sequence`, `load_schema`, extracted `PhysicsStallDetector`, `liveness_score`,
full `run_self_test` report path); zero-leak gate, honest `out_of_scope` list. Verified from merged main:
false_green_rate 0.0%, 13/13 broken caught, 22 tests green. Detail: [[issue-512-false-green-kpi-2026-07-11]].

**Delivered (2026-07-04):** PR [#503](https://github.com/agorokh/ac-copilot-trainer/pull/503)
**MERGED** ([`76a3cf6`](https://github.com/agorokh/ac-copilot-trainer/commit/76a3cf6)) — **#488 Parts C+D**
grain + serialization (`build_analytics.py` per-lap scalar + per-stint `deg_slope`, Parquet + SchemaVer, docs)
and setup⟷outcome linkage (`coaching_lake` join views + dynamic-vs-static deltas + setup-snap reliability).

**Delivered (2026-07-04):** PR [#500](https://github.com/agorokh/ac-copilot-trainer/pull/500)
**MERGED** ([`dd463fc`](https://github.com/agorokh/ac-copilot-trainer/commit/dd463fc)) — **#488 Part B**
tyre identity & specs: live `tyres` header (`longName` via `ac.getTyresLongName` + `optimalTempC` via
`wheel.tyreOptimumTemperature`), new pure-stdlib `tyre_specs.py` `data.acd` reader (**cipher is
subtraction, not XOR**) → `TyreSpec`, car-true window in `tyre_model` (+ ACD fallback),
`setup_model.resolve_tyre_spec`. **Rig-verified** (911 GT3 R: live "Slick Medium (M)" optimum 95;
ACD Slick Soft optimum 70). 6 review-hardening cycles. Detail: [[issue-488-part-b-tyre-identity-2026-07-04]].

**Delivered (2026-07-04):** PR [#497](https://github.com/agorokh/ac-copilot-trainer/pull/497)
**MERGED** ([`6eba176`](https://github.com/agorokh/ac-copilot-trainer/commit/6eba176)) — **#488 Part A**
Tier-2 CSP force/slip channels: 24 append-only per-wheel cols (76→100) `slipRatio/slipAngle/mz/fx/fy/dy`
(byte-identical Lua⟷Python), `car.extendedPhysics` header flag, new `handling_balance` advisory→verdict
rule (under/oversteer from front-vs-rear slip-angle balance). **Rig-verified** (911 GT3 R, Magione, 4 laps):
all 24 channels carry real values, `extendedPhysics=true`. **brakeTemp caveat RESOLVED** — flat 26 °C with
`extendedPhysics=true` ⇒ NOT extended-physics-gated, stays Tier-1 (per-car brake-thermal dependency).
`make ci-fast` 2390 passed; Qodo endorsed the append-only design. Detail: [[issue-488-part-a-tier2-csp-2026-07-04]].

**Delivered (2026-07-04):** PR [#496](https://github.com/agorokh/ac-copilot-trainer/pull/496)
**MERGED** ([`b9f597a`](https://github.com/agorokh/ac-copilot-trainer/commit/b9f597a)) — **#466 Part B**
setup-resolution + `race.ini` concurrency hardening: the 3 self-hosted-daemon (cursor) MEDIUM findings,
**separable from the criterion-(a) limit** and off-rig testable. **B1** `setup_reader.resetRaceIniCache()`
on the trainer's spawn resets (a reused Quick-Drive session index with a different baked setup now
refreshes on a real re-spawn; a same-spawn in-place edit still holds). **B2** transient-`race.ini`-miss
retries instead of a wrong legacy folder guess (vanilla `SETUP=` fallback preserved). **B3**
`write_setup_baked_race_ini` stable two-read snapshot + unparseable-noop so a torn CM write never drops
CM-owned sections (`unstable` counter added). 5 tests; `make ci-fast` green; Qodo **endorsed** the design.
**#466 actionable scope now complete** — criterion (b) #482, Part B #496, criterion (a) = documented
CSP/CM limit #495 — recommend closing #466. Detail: [[issue-466-partb-setup-resolution-hardening-2026-07-04]].

**Delivered (2026-07-03):** PR [#482](https://github.com/agorokh/ac-copilot-trainer/pull/482)
**MERGED** (`ab72152`) — [#466](https://github.com/agorokh/ac-copilot-trainer/issues/466) overlay
fast-fail hardening + setup-race diagnosis (built on merged #465). `rig_hijack` short `--hijack-probe-seconds`
probes detect a stalled "0 seconds" overlay and recycle a fresh launch in ~15 s (not ~32 s); per-cycle
`[auto-drive]` logs + re-bake stats + `--setup-rebake-interval`; CLI-validated finite/positive float flags.
**#466 criterion (a) EXHAUSTED (2026-07-03, later autonomous session):** reliable `--setup`+drive is a
**fundamental CSP/CM limitation**, not a missing mechanism. Every setup-injection layer is now closed
in-sim — race.ini re-bake (no cadence sweet spot); FORCE_START gui.ini (does NOT skip the overlay,
0/8+, so the #461 "~1/5" does not reproduce); suspend-inject (suspending acs is benign but the race.ini
WRITE breaks CM immediate-start); read-only race.ini (CM can't launch); CM-native (Quick Drive writes
`SETUP=` empty, no slot); CSP-Lua `ac.loadSetup` (`isCarResetAllowed` NEVER true on START or PIT
autonomous launch, 0/152). Root cause: setup application needs a resettable/pre-live state; CM's
immediate-start (the only reliable overlay-skip) precludes it. **Recommendation:** accept as a
documented limitation; use `--no-setup` for autonomous drives (setup applies fine when NOT composed
with a drive). FORCE_START code reverted; criterion (b) fast-fail shipped (#482). No-setup drive path
reliable. Full table: [[issue-466-setup-drive-rebake-race-2026-07-03]].

**Delivered (2026-07-03):** PR [#483](https://github.com/agorokh/ac-copilot-trainer/pull/483)
**MERGED** at [`28c0fe1`](https://github.com/agorokh/ac-copilot-trainer/commit/28c0fe1b8745cef02d2cf9828502f2c21be58fcf) —
**[#478](https://github.com/agorokh/ac-copilot-trainer/issues/478) CLOSED** (Capture Tier-B channels
accG/yaw_rate/wheelsPressure + first-class tyre-set id + weatherType; #266 stretch / #402 residual).
New `chassis_read.lua` captures measured g-forces (`car.acceleration`, in G) + yaw rate
(`car.localAngularVelocity.y`); `wheel_read` captures dynamic hot `tyrePressure`; `telemetry.lua`
persists them (TRACE_FIELDS 23→30, append-only, byte-identical Lua/Python, older archives load as
blanks; all-zero column = "no live data"). Consume: `corner_attribution` `turn_in_lag` flips
advisory→verdict only on real heading-trails-steer lag, `grip_limited` on live hot pressure. Lakehouse
`stints` split on the canonical compound index off the `setup_hash` proxy. Live `telemetry_tick` sends
real lat/long G. Analysis CSV + MoTeC (G-forces + yaw) export the channels. Review-hardened over 4
self-hosted-reviewer rounds (all real defects + tests). `make ci-fast` 2357 passed. **Operator-pending
(not a code AC):** live-CSP in-sim spot-check — deferred, shared rig on `feat/issue-479` + 12
concurrent worktrees; drive a lap with #478 active and confirm non-zero `accG_*`/`yaw_rate`/
`wheelsPressure_*` + `tyres` block + a confirmed verdict. Detail:
[[issue-478-tier-b-channels-2026-07-03]].

**Active focus (2026-07-03):** PR
[#465](https://github.com/agorokh/ac-copilot-trainer/pull/465) for
[#461](https://github.com/agorokh/ac-copilot-trainer/issues/461) is review-converged at
`d4fab02` but not merged in this session. It replaces the forbidden install-tree setup+drive compose
path with Content Manager launch plus compliant AC-Documents `race.ini` re-bake, hardens setup
snapshot/no-setup handling, and passed CI + resolve-gate + GraphQL/Qodo/Copilot review gates after
merge-forwarding from `origin/main` to clear GitHub's dirty merge state. The self-hosted reviewer did
not post a current-SHA review after the final cooldown, so its gate is vacuously satisfied per
`resolve-pr` anti-hang rules. Next action: merge PR #465 if desired, then run post-merge sync/SAVE.

**Delivered (2026-07-03):** PR [#480](https://github.com/agorokh/ac-copilot-trainer/pull/480)
**MERGED** ([`d15dd28`](https://github.com/agorokh/ac-copilot-trainer/commit/d15dd28)) closing
[#479](https://github.com/agorokh/ac-copilot-trainer/issues/479) — Game Point **AUTO-START SIMHUB** UI
toggle (opt-in default; hardened atomic `update_settings`: no-secrets, preserve-manual-work,
unique-tempfile; UI source-of-truth). Operator-grade verified; 4-round review-hardened. Follow-up
[#481](https://github.com/agorokh/ac-copilot-trainer/issues/481) **CLOSED** (PR
[#485](https://github.com/agorokh/ac-copilot-trainer/pull/485) `e126f02` — hermetic `AC_COPILOT_*` env
in `test_ai_sidecar_external`). Detail: [[pr-480-simhub-launcher-toggle-2026-07-03]].

**Delivered (2026-07-02):** PR [#460](https://github.com/agorokh/ac-copilot-trainer/pull/460)
merged [#459](https://github.com/agorokh/ac-copilot-trainer/issues/459) — autonomous harness as a
product + setup verify. Detail: [[issue-459-harness-product-2026-07-02]].

**Delivered (2026-07-02):** PR [#452](https://github.com/agorokh/ac-copilot-trainer/pull/452)
**MERGED** at [`ff65522`](https://github.com/agorokh/ac-copilot-trainer/commit/ff6552271107884222dd20c6b3420921e71318f9) -
telemetry-learned shift points for [#442](https://github.com/agorokh/ac-copilot-trainer/issues/442).
Lap/reference traces now carry `rpm`; `shift_profile.lua` learns per-gear upshift RPMs and
corner-exit gear provenance from the active reference; SHIFT UP coaching and the Racing Atelier RPM
zones use learned targets before heuristic limiter fractions. Review hardening covered old archives
without `rpm`, neutral/manual shift frames, skipped downsampled gear jumps, missing limiter readings,
and corner-exit sampling before the following straight. GitHub checks green, resolve gate clean, Qodo
`Bugs (0)`, Gemini current-SHA no feedback. #442 is **CLOSED**.

**Delivered (2026-07-02):** PR [#455](https://github.com/agorokh/ac-copilot-trainer/pull/455)
**MERGED** at [`5c582f7`](https://github.com/agorokh/ac-copilot-trainer/commit/5c582f7f7be166c8b10901d1116f268e7e214fef) -
post-merge review hardening for [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408).
`reference_source=imported` now matches only generic imported references, not `pro` / `tt` /
`generated`, and partial Track Titan debug archives are excluded from comparison fallback candidates.
GitHub build/conformance/docs green; Qodo follow-up reported no material issues.

**Delivered (2026-07-02):** PR [#451](https://github.com/agorokh/ac-copilot-trainer/pull/451)
**MERGED** at
[`81be1f3`](https://github.com/agorokh/ac-copilot-trainer/commit/81be1f33f52dcd3efe08c6bcc0582e1307a3a62c) -
voice-bank timing and stale-bank invalidation for
[#381](https://github.com/agorokh/ac-copilot-trainer/issues/381). Kokoro hot-register speeds and the
Piper alert/urgent/critical ladder now keep neural act cues inside the 450 ms brake-alarm budget;
`INTENSITY_CHAIN_VERSION=3` forces old `prosody2+intensity2` banks to fail validation; user
`AC_COPILOT_VOICE_BANK` points at
`C:\Users\arsen\Projects\ac-copilot-trainer\.scratch\coach-bank-kokoro-fenrir-v3-intensity3-20260702`.
Runtime proof: timing report urgent 379.6 ms, critical 361.4 ms,
`brake_alarm_within_450ms=true`; sidecar `/health.voice.enabled=true` with `rtmixer` on the USB
Sound Device. **#381 remains OPEN** only for the human-gated at-wheel A/B listening confirmation.
**Verified (2026-07-03, `/autonomous-deliver 381`):** acoustic proof on the real intensity3 bank —
headline A/B critical "Brake!" **+2.84 dB louder & 3× terser** than the calm apex; same-word ladder
monotonically terser+brighter; `timing_report` green (triple-cross-validated). Council: ship as-is,
no re-bake, don't auto-close. ⚠️ run the at-wheel test from an `origin/main` checkout (main tree is on
the intensity2 #408 branch, which would disable voice). Desk-listen A/B WAVs + waveform SVG delivered.
Detail: [[issue-381-intensity-verification-2026-07-03]].

**Delivered (2026-07-02):** PR [#453](https://github.com/agorokh/ac-copilot-trainer/pull/453)
**MERGED** at [`97a963f`](https://github.com/agorokh/ac-copilot-trainer/commit/97a963f) - session
review browser/report products for [#404](https://github.com/agorokh/ac-copilot-trainer/issues/404)
and reference selection for [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408). #404
is **CLOSED** (Part A in #423; Parts B-D in #453), and #408 is **CLOSED** (Parts A-B in #418, Part C
through #353/#428, Part D in #453). Session Review now writes schema-v2 Markdown/JSON/HTML with
Debrief, Next Session, History, Lap-Time Trend, Corner Trends, and Lap Compare; CLI/sidecar reference
selection supports `auto` / `your-best` / `pro` / `tt` / `generated` / `imported` / `none`; external
broadcasts expose basenames only. CI green, review threads resolved, post-merge classification clean.

**Delivered (2026-07-02):** Racing Atelier **runtime adoption complete on all three surfaces**
([#432](https://github.com/agorokh/ac-copilot-trainer/issues/432) Parts A2+B; #86 conformance fix):
PRs [#444](https://github.com/agorokh/ac-copilot-trainer/pull/444) (`82ced33`, in-game
main-dashboard card + COACHING tile — operator-directed evolution: 62px vitals, RPM shift zones,
SHIFT UP verb; live-verified in-sim), [#445](https://github.com/agorokh/ac-copilot-trainer/pull/445)
(`6f04755`, launcher photo-parity, real-pixel verified) and
[#446](https://github.com/agorokh/ac-copilot-trainer/pull/446) (`91ca72a`, rig-screen badge/delta
fixes the operator found on the glass — flashed to the device). Detail:
[[pr-444-atelier-main-dashboard-2026-07-01]]. **Operator-pending:** rig-screen photo vs
`esp32_rig.png`; in-sim BRAKE-state glance. **Open flake:** autonomous driver stalls ~500m from
pit start (both drivers) — file vs the harness next session. Follow-up
[#442](https://github.com/agorokh/ac-copilot-trainer/issues/442) is now delivered by PR #452.

**Delivered (2026-07-01):** PR [#429](https://github.com/agorokh/ac-copilot-trainer/pull/429)
**MERGED** ([`047309e`](https://github.com/agorokh/ac-copilot-trainer/commit/047309ef450c56c6e95a886cca86724e277a64e5))
implementing [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) four-tier expressive
voice intensity (`calm`/`alert`/`urgent`/`critical`, manifest v3, original race-engineer persona
signature). The register ladder was hoisted into the shared `tools/ai_sidecar/registers.py` so the
observer and voice vocabulary stop re-declaring it. CI green; 10 bot threads resolved.
**Operator-pending (not a code deliverable):** the on-rig A/B listening confirmation that
high-importance cues sound more urgent than low ones — audible-intensity is operator-confirmed per
the honesty invariant, never asserted by the pipeline. The #429 follow-up
[#438](https://github.com/agorokh/ac-copilot-trainer/issues/438) is now **CLOSED** — PR
[#441](https://github.com/agorokh/ac-copilot-trainer/pull/441) **MERGED**
([`65e9d42`](https://github.com/agorokh/ac-copilot-trainer/commit/65e9d42c4de469d20483cbd6da7b29341b20465d),
2026-07-02): `Manifest.validate()` enforces the persona/prosody/intensity `voice_signature` suffix,
`from_bank()` disables on drift, and `bake_bank()` fails fast on a suffix-less backend. Detail:
[[pr-441-voice-signature-gate-2026-07-01]].

**Active focus (2026-06-17):** EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) — **Part F harness daemon shipped** ([#228](https://github.com/agorokh/ac-copilot-trainer/issues/228)/PR #229) and its on-rig launch gap fixed ([#232](https://github.com/agorokh/ac-copilot-trainer/issues/232) **CLOSED** / PR [#233](https://github.com/agorokh/ac-copilot-trainer/pull/233) **MERGED** `c556dfe`): the daemon now launches AC **de-elevated via Content Manager** (`--launch-mode cm`), live-verified hands-off on `AG_PC`. The autonomous self-test is now **one command** ([#235](https://github.com/agorokh/ac-copilot-trainer/issues/235) **CLOSED** / PR [#236](https://github.com/agorokh/ac-copilot-trainer/pull/236) **MERGED** `d051096`): `python -m tools.ac_harness.self_test` drives the daemon hands-off and asserts the live coaching pipeline — **LIVE PASS** (`coaching.snapshot=335, tire_temps=168, connection=34`, no human at the wheel). The vision-oracle **"eyes"** also landed ([#238](https://github.com/agorokh/ac-copilot-trainer/issues/238) **CLOSED** / PR [#239](https://github.com/agorokh/ac-copilot-trainer/pull/239) **MERGED** `3e677c7`): `tools.ac_harness.hud_capture` (stdlib ctypes GDI, no new dep) captures the live AC HUD hands-off with a render-liveness check — **LIVE-VERIFIED** (in-cockpit at Spa, HUD text legible). [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188)/[#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) **CLOSED**. **The autonomous self-test now has launch + pipeline-assert + eyes, all hands-off + live-verified.**

**Active focus (2026-06-19) — HANDOFF, see [#244](https://github.com/agorokh/ac-copilot-trainer/issues/244):** Part G **racing driver** **MERGED** ([#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) / PR [#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) `372156a`): follows `fast_lane.ai`'s embedded speed profile with braking points/trail braking; **gear bug fixed** (was stuck in 1st — limiter below shift point) → now shifts 1→4, **146 km/h** (was 52). `tools/ac_harness/racing_telemetry.py` records human laps. **The wall is STEERING** (pure-pursuit cuts apexes → corners crawl, lap INVALID → no `lap`/`delta` telemetry). **Next:** record 5–10 human GT3 laps → build a path-tracking steering controller from real corner speeds/braking points. Full state: [`racing-driver-and-controller-2026-06-17`](../03_Investigations/racing-driver-and-controller-2026-06-17.md). Parallel hot path: Stream A rig screen EPIC [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) after PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) is final polish/proof: font conversion outputs, persistence/backpressure/debug-screen polish if still desired, and final on-device smoke.

**Active focus update (2026-06-19 LATER) — #244 / PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) MERGED + LIVE-VERIFIED on the rig:**
Ran `/autonomous-deliver 244` **on `AG_PC` itself** (prior Mac→rig blocker moot). The merged Stanley
controller from the human profile drove Magione via carcsw, no human → **3 AC VALID laps** (best
**106.8 s**, max **207.6 km/h**, gears 1–6, 0 stuck), and the sidecar tap showed **`delta=2935`** live
delta-to-reference + `coaching.snapshot=3797` — **the `lap`/`delta` telemetry wall is broken**. The
trainer captured the agent's lap as its coaching reference (lap archives written). **Residual:** best
clean lap is ~85% of the human's relaxed pace (106.8 s vs 90.7 s / 83.5 vs 98.7 km/h); the literal
`avg ≳100 km/h` bar is unmet and an aggressive-throttle tuning pass REGRESSED (TC-off wheelspin), so the
merged defaults are near-optimal. The last ~15% is separable controller-sophistication on
`racing_driver.py` → stays as remaining Part-G scope on #244 (no new overlapping issue). **#244 + #154
stay OPEN** for the pace bar; operator decides whether the wall-break + telemetry milestone closes
Part-G-core. Full write-up: [`stanley-steering-live-verified-2026-06-19`](../03_Investigations/stanley-steering-live-verified-2026-06-19.md).

**Runtime hotfix (2026-06-19) — #246 / PR #249 MERGED + CLOSED (live-verified):**
PR [#249](https://github.com/agorokh/ac-copilot-trainer/pull/249) (`4e2a310`) moved lap-archive writes
off the lap-complete/SF frame. **[#246](https://github.com/agorokh/ac-copilot-trainer/issues/246)
CLOSED** on the rig this session: timestamped tap of the script-frame `coaching.snapshot` stream
showed max gap **255 ms** (at S/F: 217 ms / 255 ms, not ~2 s); archives still land off-frame, laps
`valid=True`. The ~2 s render freeze is gone. Evidence:
[#246#issuecomment-4754133099](https://github.com/agorokh/ac-copilot-trainer/issues/246#issuecomment-4754133099).

**Active focus update (2026-06-27) — #324 / PR [#325](https://github.com/agorokh/ac-copilot-trainer/pull/325) MERGED (`0fb721f`), generality + flat-out LIVE-VERIFIED:**
Operator pushback ("the composed run wasn't racing — stuck in 1st gear") drove the fix. New
`tools/ac_harness/auto_drive.py` is the genuinely-composed one-command L2 loop (launch → carcsw
hijack w/ retry → autonomous drive in a thread → WS producer assert), **parametrized by
car/track/preset**, with **sim-death anti-false-green** (Car0 packet stagnation). Three driver modes:
`cruise` (LapDriver), `racing` (AI-line pace), **`ggv`** (flat-out friction-circle min-time).
**Generality proven beyond Magione/Porsche**: Imola + Audi R8 LMS (full lap + reference coaching),
Mugello + Corvette C7R, and **Spa + BMW Z4 GT3 flat-out top gear 6 / 211 km/h** with reference
coaching (`T2 · target entry 241 km/h`). Load-bearing fix: the generic GGV's `k_aero_lat` MUST be 0
(an aero-lateral term spins the GT3 out — a multi-agent verification workflow caught it against the
#259 plant fit). Honest residual: flat-out on Stanley still loses a few corners; the clean ~83 s line
needs curvature-ff + per-car `ff_c1/c2` calibration (#244). #154 stays OPEN (children #277/#278/#305 +
Part-G KPI residual). Full state:
[`autonomous-drive-multitrack-generality-2026-06-27`](../03_Investigations/autonomous-drive-multitrack-generality-2026-06-27.md).

**Infra (2026-05-20):** PR [#111](https://github.com/agorokh/ac-copilot-trainer/pull/111) closed the [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) agent-surface campaign (closeout doc only; five agent SHA alignments deferred). PR [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) memory-contract cursor rule fix remains on `main`.

## Stream A — Rig screen Phase-2 UI (PR #91 merged — Parts A–D on `main`)

**Infra (2026-05-16):** PR [#96](https://github.com/agorokh/ac-copilot-trainer/pull/96) landed template-2026.05 deterministic Claude hooks on `main` (`5d3019e`) — does not change device/UI scope; removes LLM-bearing Stop/PreToolUse hooks that caused session stalls.

**Status:** PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** `2026-04-29T17:02:22Z` as squash commit `[35d770c](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195)` on `main` (LVGL 8.3 portrait UI, launcher, AC Copilot mirror + `coaching.snapshot`, Pocket Technician + `setup.list` / `setup.load`, trainer Lua/sidecar protocol, lap-archive path alignment, Windows `ar` batching). Device bring-up catalogue: `[screen-end-to-end-bringup-2026-04-26](../03_Investigations/screen-end-to-end-bringup-2026-04-26.md)`.

PR #83 (WS + Lua bridge) **MERGED 2026-04-22** at `caa8a9ad` — still the foundation under Stream A.

**Outstanding housekeeping:** Issue [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81) may still be OPEN from before PR #83 — close with `gh issue close 81` when confirmed duplicate.

**Next (EPIC #86 remainder after PR #365):**

- **Delivered by PR #365** — Game Point launcher, Setup Exchange screen/proxy/install path, Pocket Technician spinner controls, and environment-only sidecar token/voice routing.
- **Still open on #86** — Part A4 `lv_font_conv` outputs; SPIFFS/persistence/backpressure/debug-screen polish if still desired; final device smoke artifact covering launcher → AC Copilot live hints → Pocket Technician setup load → Setup Exchange browse/download/install.

**Live-dev:** Hotspot + sidecar path per `[glossary/rig-network.md](../glossary/rig-network.md)`. Firmware: `python -m platformio run -e jc3248w535` under `firmware/screen/` (CI does not build firmware).

## Stream B — CSP-apps integration (Pocket Technician, Setup Exchange)

Integration ADR landed 2026-04-21 as `[screen-and-csp-apps-integration.md](../01_Decisions/screen-and-csp-apps-integration.md)`. Verdict: **replicate, don't bridge.** Our trainer Lua VM calls `ac.getSetupSpinners()` + `ac.setSetupSpinnerValue()` directly (same APIs PT uses); sidecar watches `UserSetups/<carID>/` for SX-dropped files. Both PT and SX stay installed; we coexist, not compete.

Surface map of both apps lives in `[csp-app-pocket-tech-setup-exchange-2026-04-21](../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md)`.

**Next:** `setup.list` / `setup.load` shipped with PR #91; spinner controls and Setup Exchange screen/proxy/install shipped with PR #365. Remaining B-stream work is optional `setup_control.lua` / UI polish if still desired, plus the #86 final on-device smoke artifact.

## Stream C — Physical rig integration EPIC #59

**New discovery**: `[10_Rig/physical-rig-integration-epic-59.md](../10_Rig/physical-rig-integration-epic-59.md)` captures the full scope — Arduino UNO (fan + OLED + seat vibration motors + pedal haptics), ESP32 touch dashboard (**Stream A is this**), Dayton BST-1 under-seat shaker (**done as Phase 1R**), salvaged Xbox controller motors for pedal haptics, full pin map.

**Protocol update (2026-06-16):** PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) delivered the sidecar `telemetry_tick` / `haptic_event` route for physical peripherals, including legacy rig-screen classification and haptics-only fan-out. Downstream hardware firmware can now consume a stable sidecar contract; active dev focus still stays on #190 / carcsw productionization.

Stream A is the first slice of this epic. Phase 3b (side bolster motors) and Phase 4 (pedal haptics) land after Phase 2 screen is fully wired.

## Stream D — PR #75 in-game smoke test (carried-over)

Now **MERGED 2026-04-14**. Ollama corner coaching pipeline (`corner_query` / `corner_advice`, sub-550 ms) is live. See `[pr-75-ollama-corner-coaching-protocol](../03_Investigations/pr-75-ollama-corner-coaching-protocol.md)` for the protocol the rig screen can subscribe to.

## Priority call

Stream A (rig screen Phase-2 LVGL + Figma UI + final on-device proof) is the hot path — the Game Point/Pocket Technician/Setup Exchange code path is now merged, so the next tangible win is a clean physical-rig smoke artifact across launcher → live hints → setup load → Setup Exchange install. Stream B integration is folded into Stream A's protocol work.

## Recently landed (reverse chronological)

- **2026-07-01 UTC / 2026-06-30 PT** - PR [#428](https://github.com/agorokh/ac-copilot-trainer/pull/428)
  **MERGED** at `9685155` - **Track Titan harness curriculum** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)
  **CLOSED**): adds `track_titan_harness_curriculum_v1`, `tools.tt_ingest curriculum`, retained
  coaching/last-session pairing, self-consistent in-lake `curriculum_lapN.json` output guards, derived
  retention cascade planning, and docs for the M-TT3 artifact. Classification: no migration/env/deps/script/workflow flags.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#433](https://github.com/agorokh/ac-copilot-trainer/pull/433)
  **MERGED** at `cd17dfe` - **setup review hardening** ([#407](https://github.com/agorokh/ac-copilot-trainer/issues/407)
  follow-up): setup archive/store ingestion now rejects malformed UTF-8 without replacement
  decoding, JSONL experiment-store reads stay streaming, closed-loop guards ignore later missing
  unrelated params instead of reporting false confounds, and `.secrets.baseline` hash validation
  accepts uppercase SHA-1 metadata. Classification: `scripts/` changed for policy hash regex only;
  no migration/env/deps/workflow action required.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#417](https://github.com/agorokh/ac-copilot-trainer/pull/417)
  **MERGED** at `a4ae501` - **setup intelligence** ([#407](https://github.com/agorokh/ac-copilot-trainer/issues/407)
  **CLOSED**): adds complaint-language setup advice, setup diffs, loopback-only closed-loop
  suggestions, schema-backed decoded display/cautions, packaged schema assets, and Windows-safe
  policy secret scanning. Classification: `scripts/` and `Makefile` changed for policy/secret scan
  plumbing; no migration/env/deps/workflow action required.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#422](https://github.com/agorokh/ac-copilot-trainer/pull/422)
  **MERGED** at `28048c1` - **coaching diagnosis depth** ([#405](https://github.com/agorokh/ac-copilot-trainer/issues/405)
  **CLOSED**): Coach v2 now spatially matches current/reference corners by apex spline, reuses one
  corner/signature/reference-match pass across reports and protocol follow-up, and emits richer
  `steering`, `brake_shape`, `gear`, `exit_road_usage`, and `consistency` diagnostics. History
  archives are bounded, same-combo scoped, deduped by metadata plus streaming trace digest, and routed
  through `historyArchivePaths`. Classification: no migration/env/deps/script/workflow flags.
- **2026-06-30** - PR [#419](https://github.com/agorokh/ac-copilot-trainer/pull/419)
  **MERGED** at `14f6257` - **driver progression profile** ([#403](https://github.com/agorokh/ac-copilot-trainer/issues/403)
  **CLOSED**): Coach v2 now derives cue density and curriculum from the persistent driver profile,
  scoped to the active car/track/layout. Added `tools.ai_sidecar.driver_progression`, hardened
  profile rebuild/idempotency/corner sample merging, documented `AC_COPILOT_DRIVER_PROFILE`, and
  kept runtime profile writes constrained to approved `journal/driver/profile.json` roots.
  Classification: `.env.example` changed for the documented profile override; no migration/deps/workflow flags.
- **2026-06-30** - PR [#418](https://github.com/agorokh/ac-copilot-trainer/pull/418)
  **MERGED** at `17aa36b` - **sector benchmarks and SuperLap targets** ([#408](https://github.com/agorokh/ac-copilot-trainer/issues/408)
  epic remains **OPEN**): post-lap sector/micro-sector deltas, complete-only stitched SuperLap
  targets, protocol/HUD surfacing, valid/same car-track-layout benchmark scoping, explicit lap-clock
  boundary handling, and 1-based benchmark indices. Classification: no migration/env/deps/script/workflow
  flags. Remaining #408 work: TT M-TT3 via [#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)
  and fuller reference-library management.
- **2026-06-30** - PR [#415](https://github.com/agorokh/ac-copilot-trainer/pull/415)
  **MERGED** at `c407d46` - **telemetry data platform** ([#402](https://github.com/agorokh/ac-copilot-trainer/issues/402)
  **CLOSED**): DuckDB `sessions` / `stints` rollups, compacted driver profile ledger, dry-run-first
  lap/TT retention, stdout CSV streaming, and telemetry data-platform docs. Review hardening made
  retention fail closed on invalid profiles, preserve compacted bests through partial rebuilds,
  reject negative caps, invalidate TT derived indexes after TT deletions, and normalize Windows
  drive-letter paths in the Git Bash agentic-memory wrapper. Classification: `scripts/` changed due
  wrapper hardening; no migration/env/deps/workflow action required.
- **2026-06-30** - PR [#416](https://github.com/agorokh/ac-copilot-trainer/pull/416)
  **MERGED** at `9832004` - **race management cues** ([#406](https://github.com/agorokh/ac-copilot-trainer/issues/406)
  **CLOSED**): live stint-level fuel-to-finish, tyre, brake, and conditions advisories now ride
  beside Coach v2 / the legacy observer and emit through the existing `coaching.cue` + voice path.
  Lua telemetry publishes fuel and tyre temps when available; protocol validation covers the new
  channels. Review hardening added critical-tyre escalation and lap-rollback fuel reset tests.
- **2026-06-30** - PR [#410](https://github.com/agorokh/ac-copilot-trainer/pull/410)
  **MERGED** at `d669b19` - **Racing Atelier design package** ([#400](https://github.com/agorokh/ac-copilot-trainer/issues/400)
  **CLOSED**): committed the canonical handoff package and render-target gate, removed the retired
  AG Porsche Academy components, and added review hardening for offline/CDN warnings plus safer
  prototype `postMessage` origin handling. Post-merge classification found no flags. ZIP
  reconciliation showed all 95 package files present; real drift from the raw ZIP is intentional
  hardening, not missing content. Browser verification loaded Game Point, in-game HUD, and ESP32 rig
  kits over localhost with the expected Racing Atelier palette and instrument geometry. Details:
  [`pr-410-racing-atelier-design-package-2026-06-30`](../03_Investigations/pr-410-racing-atelier-design-package-2026-06-30.md).
- **2026-06-30** — PR [#394](https://github.com/agorokh/ac-copilot-trainer/pull/394) **MERGED** at
  `b14c984` — **voice reliability for packaged Game Point** ([#392](https://github.com/agorokh/ac-copilot-trainer/issues/392)
  **CLOSED**): sidecar `/health.voice` is the launcher source of truth; Game Point now reports
  disabled/stale schema-v1 banks, adopted no-voice sidecars, missing old voice health, observer-only
  sidecars when playback was requested, and pyttsx3 startup failures honestly. PyInstaller collects
  the installable voice floor (`numpy`, `sounddevice`, `pyttsx3`) and only collects opt-in `rtmixer`
  modules when present. Windows packaged proof was captured on `pc` at the packaging head; final
  review-fix behavior was re-smoked locally because `pc` was offline before merge. Details:
  [`pr-394-voice-reliability-2026-06-30`](../03_Investigations/pr-394-voice-reliability-2026-06-30.md).
- **2026-06-30** — PR [#395](https://github.com/agorokh/ac-copilot-trainer/pull/395) **MERGED** at
  `b122e1b` — **M-TT2 Track Titan reference archive builder** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)):
  `tools.tt_ingest reference` builds schema-v1 `lap_archive` records from retained TT services
  telemetry, with strict full-lap spatial coverage, reference-lap timing/identity validation,
  debug-only partial metadata, and a runtime guard so partial TT archives cannot install as M0 live
  observers. Lake discovery is scoped by session/lap, repeated same-lap `/last-session` captures are
  retained as deterministic segment-window files, and archive output cannot overwrite retained TT
  inputs. Classification: no migration/env/deps/workflow flags. #353 stays OPEN for M-TT3
  per-corner analysis -> harness curriculum/oracle work and for live full-window capture before
  production non-partial TT references exist.
- **2026-06-29** — PR [#370](https://github.com/agorokh/ac-copilot-trainer/pull/370) **MERGED** at
  `26e9a09` — **M-TT1 Track Titan services crack** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)):
  `tools/tt_ingest/tt_services.py` (services client) + `coaching` CLI retaining per-lap raw
  reference + advice evidence to the write-once lake. **Auth corrected**: services `/api/v2/*` /
  `/dynamic-reference-laps/*` / `/advice/*` use the raw Cognito **access token** (not SigV4 — that
  was the disproved hypothesis); verified live (accessToken→200, idToken→403). Per-corner coaching
  oracle works E2E. Classification: additive `tools/`+tests+fixtures, no migrations/env/deps.
  Resume → **M-TT2** (reference telemetry → `lap_archive` → M0 `--reference-archive`). Full state:
  [`tt-services-sigv4-crack-2026-06-29`](../03_Investigations/tt-services-sigv4-crack-2026-06-29.md).
- **2026-06-29** — PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) **MERGED** at
  `854f822` — **Game Point launcher supervisor** ([#363](https://github.com/agorokh/ac-copilot-trainer/issues/363)
  **CLOSED**): Windows launcher package/shortcut/settings, supervised sidecar start/status/logging,
  environment-only sidecar token/voice routing, Pocket Technician spinner controls, Setup Exchange
  proxy/install path + rig-screen browse/download/install UI, and Game Point docs. Classification:
  `.env.example` and `pyproject.toml` changed; no migrations.
- **2026-06-28** — PR [#348](https://github.com/agorokh/ac-copilot-trainer/pull/348) **MERGED** at
  `226bc97` — **Coaching lakehouse DuckDB** ([#344](https://github.com/agorokh/ac-copilot-trainer/issues/344) P1):
  embedded DuckDB star schema in `tools/coaching_lake` rebuilt from lap-archives.
  9 off-sim tests, ~46s build time. Closes the P1 query engine requirement for EPIC #344.
- **2026-06-28** — PR [#349](https://github.com/agorokh/ac-copilot-trainer/pull/349) **MERGED** at
  `c477aee` — **live voice wiring** ([#341](https://github.com/agorokh/ac-copilot-trainer/issues/341)
  M0 **CLOSED**): sidecar turns the live `telemetry_tick` stream into spoken cues — `coaching.cue` topic
  + `voice` client-class + optional `spline`/`lap` validation; `server.py` `_publish_coaching_cues`
  feeds the `RealtimeObserver` per tick → speaks via the in-process #340 `VoiceCoach` **and** publishes
  `coaching.cue` to WS peers; `--voice-reference`/`--voice-bank` flags (audio deps lazy, OFF by default).
  A parallel session hardened it (scheduler tie-break by rank→freshness + act-cue latency logging). 9
  wiring tests + e2e round-trip; ci-fast green. **#350 follow-up:** the Lua `telemetry_tick`-with-`spline`
  producer already shipped (`telemetry_publisher.lua`, #341/#342) and **PR [#372](https://github.com/agorokh/ac-copilot-trainer/pull/372)
  MERGED** (`e0c93fd`, 2026-06-29) re-scoped to the bake path (batch Piper + 48 kHz default). **Only the
  on-rig audible smoke remains** — rig-gated, currently SSH-blocked from m5 → [#350](https://github.com/agorokh/ac-copilot-trainer/issues/350) (OPEN).
- **2026-06-28** — PR [#338](https://github.com/agorokh/ac-copilot-trainer/pull/338) **MERGED** at
  `f8d010e` — CoachingOracle **Qodo round-6 hardening** ([#333](https://github.com/agorokh/ac-copilot-trainer/issues/333)
  follow-up to #334): None-on-failure `get_coaching()`, spaced debrief OCR marker, nested-None coercion,
  WinRT await budget + cancel, helper timeout tests (19/19). No post-merge classification flags.
- **2026-06-28** — PR [#343](https://github.com/agorokh/ac-copilot-trainer/pull/343) **MERGED** at
  `f50719c` — **in-the-ear voice coach** ([#340](https://github.com/agorokh/ac-copilot-trainer/issues/340)
  **CLOSED**): new `tools/ai_sidecar/voice/` speaks the same `Advisory` stream the text HUD renders, via
  a pre-rendered phrase bank (not live TTS) + urgency scheduler (barge-in/dedup/TTL/cooldown). Stdlib
  core dep-free (audio deps behind a new `voice` extra); 51 tests; `make ci-fast` green. Off-rig verified:
  emit→dispatch latency **1.27 ms** (≤150 ms budget), 9.19 s real-speech WAV. Decision:
  [`voice-coach-architecture-2026-06-28`](../01_Decisions/voice-coach-architecture-2026-06-28.md).
  **Deferred (rig-gated):** on-rig audible verification at the wheel; v1.1 number-splicing. #154 stays OPEN.
- **2026-06-27** — PR [#325](https://github.com/agorokh/ac-copilot-trainer/pull/325) **MERGED** at
  `0fb721f` — `tools/ac_harness/auto_drive.py`: one-command composed L2 loop (launch → hijack → drive
  → WS assert), driver modes cruise/racing/**ggv flat-out**, sim-death anti-false-green, `max_gear_used`;
  closes [#324](https://github.com/agorokh/ac-copilot-trainer/issues/324). Live-verified non-Magione /
  non-Porsche: Imola+Audi R8 LMS (full lap + reference coaching), Mugello+Corvette C7R, Spa+BMW Z4 GT3
  **flat-out 6th gear / 211 km/h** with reference coaching. 21 off-sim tests; no post-merge flags.
  #154 stays OPEN.
- **2026-06-19** — PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) **MERGED** at
  `88249bf` — Stanley steering + `RacingDriver.from_human_profile` ([#244](https://github.com/agorokh/ac-copilot-trainer/issues/244)).
  **LIVE-VERIFIED on `AG_PC`**: 3 AC VALID laps via carcsw (best 106.8 s, 207.6 km/h, gears 1–6),
  sidecar `delta=2935` + `coaching.snapshot=3797`, agent lap captured as trainer reference. The
  steering/telemetry wall is broken. Residual: pace ~85% of human (`avg ≳100 km/h` bar unmet; defaults
  near-optimal, aggressive tuning regressed) → remaining Part-G scope on #244. #244/#154 stay OPEN.
  See [`stanley-steering-live-verified-2026-06-19`](../03_Investigations/stanley-steering-live-verified-2026-06-19.md).
- **2026-06-19** — PR [#249](https://github.com/agorokh/ac-copilot-trainer/pull/249) **MERGED** at
  `4e2a310` — mitigates [#246](https://github.com/agorokh/ac-copilot-trainer/issues/246) by replacing
  synchronous lap-complete archive writes with a queued per-frame `lapArchive.createWriteJob`, temp-file
  streaming/finalization, and retrying `setup.experiment.record` notifications after WS tick/poll.
  Classification: no post-merge flags. **Issue #246 remains open until live AC rig proof confirms the
  S/F render freeze is gone.**
- **2026-06-19** — PR [#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) **MERGED** at `372156a` — closed [#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) with `tools/ac_harness/racing_driver.py` (speed-profile following, braking points, trail braking, traction throttle; 12 tests) + `tools/ac_harness/racing_telemetry.py` (human-lap CSV recorder). Gear bug fixed (1→4 shifts, 146 km/h). Classification: no post-merge flags. **Next:** human-lap capture + path-tracking steering controller ([#244](https://github.com/agorokh/ac-copilot-trainer/issues/244)).
- **2026-06-16** — **#188 CLOSED** (on the rig, autonomous-deliver). Direct probe on `AG_PC`: `car.resetCounter` **present** (`[COPILOT][WRAP-SKEW-PROBE] resetCounter present=true value=2`) → teleports fully handled → closed as moot ([close comment](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4725615887)). No code change (the #199 defensive deferral stays). New rig-ops node: [steam-elevation-mismatch-ac-launch-2026-06-16](../03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md).
- **2026-06-16** — **#190 CLOSED** — EPIC #154 Part E complete. Merged PRs: [#191](https://github.com/agorokh/ac-copilot-trainer/pull/191) L1.5 probe, [#209](https://github.com/agorokh/ac-copilot-trainer/pull/209)/[#221](https://github.com/agorokh/ac-copilot-trainer/pull/221)/[#222](https://github.com/agorokh/ac-copilot-trainer/pull/222)/[#223](https://github.com/agorokh/ac-copilot-trainer/pull/223) carcsw driver, [#201](https://github.com/agorokh/ac-copilot-trainer/pull/201) session replay for late taps. Live-verified autonomous lap + coaching on Magione. Next EPIC thread: Part F harness daemon.
- **2026-06-16** — PR [#206](https://github.com/agorokh/ac-copilot-trainer/pull/206) **MERGED** at `7d87f96` — closed [#114](https://github.com/agorokh/ac-copilot-trainer/issues/114) with setup experiment tracking and suggestions. Adds `tools.ai_sidecar.setup_optimizer`, JSONL experiment rebuild/live recording from lap archives, setup A/B comparison, deterministic expected-improvement suggestion, CLI + v1 websocket frames, Lua store registration/recording, path safety, corrupt-store/missing-dir guards, and docs in [`13_Setup_Experiments`](../../../10_Development/13_Setup_Experiments.md). Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#204](https://github.com/agorokh/ac-copilot-trainer/pull/204) **MERGED** at `dc93b1b` — closed [#115](https://github.com/agorokh/ac-copilot-trainer/issues/115) with `tools.lap_archive_export`, a streamed lap-archive CSV exporter plus deterministic MoTeC-shaped CSV bridge, documented in [`13_Lap_Archive_Export`](../../../10_Development/13_Lap_Archive_Export.md). Output paths are contained under cwd, invalid laps are skipped by default, mixed MoTeC inputs are rejected, and post-merge classification found no flags. Active focus remains #190.
- **2026-06-16** — PR [#202](https://github.com/agorokh/ac-copilot-trainer/pull/202) **MERGED** at `d71bca3` — closed [#156](https://github.com/agorokh/ac-copilot-trainer/issues/156) by removing `scripts/` `sys.path` pollution from hook/manifest tests and adding `tools.testing.script_imports`, a path-aware file loader with sibling-script support that does not expose `scripts/mcp` as a namespace package. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#205](https://github.com/agorokh/ac-copilot-trainer/pull/205) **MERGED** at `6d0ddc8` — generated reference-lap prototype for [#116](https://github.com/agorokh/ac-copilot-trainer/issues/116). Adds stdlib-only `tools.ac_harness.reference_lap`, schema-v1 `generated_reference_v1` archive emission, trainer-state bridge preserving driver PBs, validator hardening, and ADR [`rl-reference-lap-generation`](../01_Decisions/rl-reference-lap-generation.md) deferring RL runtime dependencies. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#214](https://github.com/agorokh/ac-copilot-trainer/pull/214) **MERGED** at `3e9c927` — removed the PyYAML runtime dependency from the PR-pain allowlist gate after PR #198 exposed a failing post-merge `score` run. Adds `tools/pr_pain/config.py`, routes `.github/workflows/pr-pain-detection.yml` through it, and reuses it for `extra_bot_logins`. Classification: `.github/workflows/` changed; post-merge `PR pain detection / score` succeeded on the merge commit. Active focus remains #190.
- **2026-06-16** — PR [#200](https://github.com/agorokh/ac-copilot-trainer/pull/200) **MERGED** at `ee25118` — detect-and-retry AC entry launcher; closes [#177](https://github.com/agorokh/ac-copilot-trainer/issues/177). Adds `tools/ac_harness/entry_launcher.py`, a pluggable `EntryLauncher`, default `ColdRestartActuator`, atomic `race.ini` `SPAWN_SET=PIT` normalization, retry/relaunch loop around `DrivingEntryDetector`, and CLI timing knobs. Classification: no post-merge flags. Mac-side verification is complete; live Windows/AC rig verification remains the next runtime smoke. Active focus remains #190.
- **2026-06-16** — PR [#207](https://github.com/agorokh/ac-copilot-trainer/pull/207) **MERGED** at `0c637e3` — MoTeC CSV reference-lap importer plus opt-in imported-reference activation; closes [#79](https://github.com/agorokh/ac-copilot-trainer/issues/79). Imported laps write schema-v1 `source="imported"` / `import_format="motec_csv"` archive JSON and can drive realtime coaching only when faster than the local PB, without overwriting local PB persistence. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) **MERGED** at `e5103be` — sidecar physical-peripheral protocol (`telemetry_tick`, `haptic_event`), derived haptic cues, haptics/screen routing, signed slip, partial tyre maps, legacy `ac-copilot-screen-*` classification; closes [#118](https://github.com/agorokh/ac-copilot-trainer/issues/118). No migration/env/deps/script/workflow post-merge flags; active focus remains #190.
- **2026-06-16** — PR [#198](https://github.com/agorokh/ac-copilot-trainer/pull/198) **MERGED** at `4a8ab98` — CI policy now accepts documented `vault/post-merge-pr<N>` handoff branches via `vault/`; closes [#179](https://github.com/agorokh/ac-copilot-trainer/issues/179). Classification: `scripts/` changed; no runtime/migration action. Active focus remains #190.
- **2026-06-16** — PR [#197](https://github.com/agorokh/ac-copilot-trainer/pull/197) **MERGED** at `392a868` — `ws_bridge.openEpoch()` reconnect re-arm for lifecycle `session` emission; closes [#183](https://github.com/agorokh/ac-copilot-trainer/issues/183). No migration/env/deps/script/workflow post-merge flags; active focus remains #190.
- **2026-06-13** — PR [#165](https://github.com/agorokh/ac-copilot-trainer/pull/165) **MERGED** at `1a08d45` — fleet-propagated `secrets-from-doppler` Scope-clause CI drift-guard (`tests/test_invariants_present.py`; template-repo#308/#309). Infra only; does not move Stream A / EPIC #154.
- **2026-05-17** — PR [#100](https://github.com/agorokh/ac-copilot-trainer/pull/100) **MERGED** at `ac810c0` — PT row BB chip refresh (LVGL + Lua `chipInt` + firmware JSON int path); closes [#93](https://github.com/agorokh/ac-copilot-trainer/issues/93).
- **2026-05-17** — PR [#99](https://github.com/agorokh/ac-copilot-trainer/pull/99) **MERGED** at `ebdef7e` — `tools/session_journal.py` loader hardening + tests; closes [#97](https://github.com/agorokh/ac-copilot-trainer/issues/97).
- **2026-04-29** — PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** at `35d770c` — Phase-2 LVGL rig screen Parts A–D (launcher, AC Copilot mirror, Pocket Technician, trainer/sidecar plumbing).
- **2026-04-25** — PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) development: Part A + B through full Parts C+D bring-up (pre-merge branch work).
- **2026-04-25** — PR [#89](https://github.com/agorokh/ac-copilot-trainer/pull/89) `.gitattributes *.sh/*.bash eol=lf` **MERGED** at `a55a0ed`. Hotfix for the Windows CRLF hook misfire from PR #87. Same item is queued upstream as part of `[agorokh/template-repo#97](https://github.com/agorokh/template-repo/issues/97)`.
- **2026-04-24** — PR [#87](https://github.com/agorokh/ac-copilot-trainer/pull/87) **template sync to template-repo@061d9ab** MERGED at `ab13a71`. Fixes orchestrator hook-drift, ships 9 new skills, deterministic flow-control hooks, post-merge steward + `vault-automerge.yml`. Upstream tracker `agorokh/template-repo#97` for 17+ deferred items. Full context in `[03_Investigations/template-sync-pr87-2026-04-24](../03_Investigations/template-sync-pr87-2026-04-24.md)`.
- **2026-04-22** — Session MCP infra: installed TurboVault + 6 MCP servers; see `~/Projects/mcp-work/mcp-servers` + `docs.claude.md`.
- **2026-04-22** — PR [#84](https://github.com/agorokh/ac-copilot-trainer/pull/84) vault post-merge handoff.
- **2026-04-22** — PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) external WS + Lua bridge MERGED.
- **2026-04-22** — PR [#80](https://github.com/agorokh/ac-copilot-trainer/pull/80) post-merge steward automation.
- **2026-04-21** — PR [#78](https://github.com/agorokh/ac-copilot-trainer/pull/78) sidecar auto-launch + per-lap archive (schema v1, 500 MB cap). See `[pr-78-sidecar-autolaunch-lap-archive](../03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md)`.
- **2026-04-14** — PR [#75](https://github.com/agorokh/ac-copilot-trainer/pull/75) Ollama corner coaching + CSP cdata-callable fixes.
- **2026-04-07** — PR [#73](https://github.com/agorokh/ac-copilot-trainer/pull/73) Phase-5 HUD rebuild + bundled Michroma/Montserrat/Syncopate fonts + `FIXED_SIZE` manifest.
- **2026-04-06** — PR [#70](https://github.com/agorokh/ac-copilot-trainer/pull/70) visual design match with Figma spec.
