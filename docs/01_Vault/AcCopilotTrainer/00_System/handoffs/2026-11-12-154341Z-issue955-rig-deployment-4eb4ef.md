---
type: handoff
status: active
created: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/955
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-053500Z-issue955-iteration2-native-proof-f438b7.md
---

# Issue 955 rig deployment

The operator separately authorized deployment after source PR962 and handoff963
merged: "Deploy the merged #955 changes to the rig, keep traffic shadow-only,
and verify the installed runtime yourself. Preserve any active rig sessions."
This is the evidence for that new deployment directive. Closed955 remains the
historical experiment owner; no unfinished deployment was inferred from it.

## Authority and requirements

- Assignment: update the rig's existing primary checkout and packaged Game Point,
  keep traffic shadow-only, verify installed software, preserve active sessions.
- Live955 labels: enhancement, phase-3, python; state CLOSED. No stop label.
- Permitted: canonical rig lock, safe fast-forward, local build, idle-service
  restart, software probes and configuration readback. No race actuation.
- Authentication: existing user-environment sidecar token, documented
  X-AC-Copilot-Token header. No value printed or committed.
- Creation budget: at most2 outside-assignment creations; used0. No helper agents,
  outside issues, tasks or PRs. This assigned deployment's SAVE is its own carrier.

## Observed delivery

The canonical lock was free, AC/Content Manager absent, and Game Point's session
row idle. Existing launcher/sidecar had build3c746a3. Acquired canonical lock with
owner30236; preserved settings,407 AC cfg-file hashes and the old EXE privately.
Closed the idle Game Point via its normal window close; all its processes exited.
No active simulator session was interrupted. Original Steam8524 and SimHub2348
were preserved with matching process creation times.

Clean primary C:/Users/arsen/Projects/ac-copilot-trainer was fast-forwarded using
the hub sync_fast_forward.py primitive from bcf3878 to merged abcf1a9. Its AC Lua
junction still targets src/ac_copilot_trainer in that primary checkout.
All4 changed installed Lua files match merged Git blobs; sampler SHA prefix
411a283134bd matches the native20-car verified source. No junction swap.

Built using the primary .venv and canonical --build-exe path. Installed EXE:
C:/Users/arsen/Projects/ac-copilot-trainer/dist/AC-Copilot-Game-Point.exe
SHA256: 7a06b151aeec1a90a37d36e970251317448c0822594e2341650976f1f635169e
Build time: 2026-11-12T15:36:16Z. Previous EXE retained privately.
Native packaged --self-test --json exited0; both tablet endpoint checks served.

Restarted normal --start entrypoint. Fresh /health on8765 reports abcf1a9 and
screen_peers=1. Live process paths point at the installed EXE; no build-identity
environment override. Both /tablet/dash and /tablet/voice independently returned
HTTP200. Voice remains observer_only with playback disabled. Connected-screen
transport is verified; no new on-glass or audible acceptance is claimed.

## Shadow-only and behavioral checks

Actual EXE PYZ code for traffic_eligibility, coaching_runtime, external_protocol,
server and lap_qualification matches compiled merged source (recursive code
comparison ignores only filename). Executed bundled eligibility/coaching code
with same-commit dependencies: default traffic_gate_mode=shadow; occupied and
unknown traffic preserve PRIME cues in shadow mode. Explicit offline replay
control still suppresses them. Both original A011/A012 misses are constrained.
Unchanged fresh frozen45 scores20/20 occupied,20/20 clear,5/5 controls.

Primary-checkout tests/test_traffic_eligibility.py plus lap_archive_async suite:
86 passed in2.60s, including real installed sampler LuaJIT/Lua execution, cadence,
wheel traps, fail-closed/archive handling and shadow/replay controls. Lua entry
retains trafficShadowEnabled=false with session-only arming. No collection arm,
live suppression, firmware or setup change was made.

No native AC process was started for this deployment. Installed Lua integrity and
off-sim execution are distinct from a fresh native app-load observation. Earlier
actual20-car native acceptance remains in the linked source evidence; this run
adds installed-file, bundled-logic and actual packaged-process verification.

## Final state and receipts

407/407 original AC cfg hashes unchanged; Game Point settings byte-identical.
Primary checkout clean at abcf1a9. Own rig lock released, launcher status idle;
UI directly observed READY TO DRIVE / HEALTHY / CONNECTED / OBSERVER_ONLY.
Restored the initially minimized launcher window after inspection. Updated
Game Point/sidecar left running to preserve the original service state. No AC/CM
started; Steam and SimHub retained. Active Codex checkout/branch preserved.

Private receipts under this chat's .scratch/issue955-deploy-20261112/: before.json,
sync.log, build.log, installed-tests.log, bundle-proof.json, self-test.json,
self-test-output.log, runtime-live.json, final-state.json and previous-game-point.exe.
Tier-3 shim LOAD succeeded (workspace ac_copilot) with stale-endpoint warning
retained; direct MCP unavailable, no bypass. Handoff-erratum query returned0.
No source edits. Local shortcut repair and installer observation are recorded below.
All deployment requirements are verified
within the stated software scope; no operator/manual action is requested.


## Normal Desktop entrypoint repair

Final shortcut readback found the correct EXE target with stale PowerShell
-NoProfile/-File arguments. The packaged CLI parser rejected the exact retained
arguments with exit2. Preserved original-desktop-game-point.lnk and its metadata;
created a fresh link with canonical install_desktop_shortcut, then replaced only
that backed-up Desktop link. Readback: correct installed EXE/root/icon, arguments
empty. The old RulesOnly wrapper/diagnostics were retained untouched.

Reacquired canonical ownership (26952), confirmed no AC/CM, and closed only this
run's idle Game Point. Opened the actual Desktop link through Explorer, directly
observed Game Point open, and clicked its normal START button. Fresh sidecar
reports abcf1a9, screen1, voice observer_only; released ownership and observed
READY TO DRIVE. Explorer closed, launcher restored minimized;407 cfg hashes,
settings and original Steam/SimHub process identities still match. Latest receipt:
normal-entrypoint-proof.json, plus shortcut.json and shortcut-after.json.

Canonical installer retains Arguments when refreshing an existing link. The
fresh-link generation repaired this installed artifact without source changes;
that broader installer improvement is advisory, recorded without filing.
Vault CI passed117 tests/3 expected skips; new note secret scan0. An initial
make lookup used a nonexistent Git path; resolved WinGet make and reran the
canonical target successfully. No new runtime defect or manual action remains.


The first SAVE submission from the preserved feature checkout refused exit10:
its old HEAD lacks merged handoff963, so proceeding could revert that note.
Resume SAVE from the already-synchronized primary checkout; copy only this owned
new note. No source checkout move, stash, runtime rebuild or session restart is
needed. The failed submission log is retained as vault-submit.log.


Submission integrity check caught106 unrelated CRLF-to-LF normalizations produced
by the canonical temporary-index SAVE. In the same965 carrier, restored every
unrelated path to its exact merged-base blob; final net diff is only this new
handoff. No runtime source or primary checkout move was needed. The first red
vault-automerge check reported lease_in_flight on the earlier head; no bypass or
manual merge. Unintended-eol-audit.json and failed-vault-guard.log are retained.
