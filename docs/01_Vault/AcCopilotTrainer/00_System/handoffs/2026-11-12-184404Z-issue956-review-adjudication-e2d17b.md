---
type: handoff
status: active
created: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-165106Z-issue956-review-repairs-de23c8.md
---

# Issue956 continuation: review adjudication and deployment

## Pre-loaded substrate context

Task-specific canonical Tier3 fallback succeeded for ac_copilot on resume, with the
same stale-endpoint warning. Grounded further in current issue/PR, prior dated
handoffs, installed first-party CSP SDK and pinned gate source; no bypass.

Operator explicitly resumed956: recheck964 review, resolve findings, merge/deploy
when gates pass; keep the experiment disabled and956 OPEN until real-case and
operator-timing acceptance. All original criteria and60-minute bench cap retained.
No independent issue/chat/PR creation;966 is this assignment's required companion.
Existing primary runtime/settings,955 shadow configuration and529 remain preserved.

## Review5879407247: both HIGH claims source-refuted

Review on unchanged d800c427f27381dc9ada627ffa5a2229ad097633 finished17:54:37Z.
It claims car.isInPit is absent and recommends isInPitlane in both new Lua modules.
Installed first-party extension/internal/lua-sdk/ac_apps/lib.lua5062-5063 explicitly
has both booleans: isInPitlane=pits area; isInPit=parked pit-stop place. SDK SHA256
e599f16cfda1e69284046a3674e2de02bed2fa9648fc7309402dcb1bbcfa6b55.
Installed dwrite.dll FileVersion/ProductVersion0.3.1.0. The repository bootstrap
ac_schema.json explicitly says SUBSET, so absence there is not SDK absence.

Frozen original review/cases: .scratch/issue956/review-5879407247/;
cases SHA342deead76ebb14e16f5a6c072ba247e2dda5bfe1461a1ec7fc4f681c372e7f5.
Production d800 modules replayed under LuaJIT2.1/Lua5.1 strict FFI cdata with the
actual SDK field names/types. reset_allowed=true. Parked box context succeeds and
confirms1 write; lane outside box and on-track contexts perform0 writes. Unknown
cdata fields throw. The suggested substitution (isolated scratch variant only)
performs1 unsafe write in lane/outside box on the identical frozen input. Preserve
isInPit; source unchanged. Synthetic probes do not prove physical acceptance.

Public source/replay adjudication:
https://github.com/agorokh/ac-copilot-trainer/pull/964#issuecomment-6832550175
Pinned77fd full enforce gate after that reply still correctly returned1 for both
body findings. No self-dismissal, floor relaxation or report-mode override.

## Exact trusted-base companion

PR966 https://github.com/agorokh/ac-copilot-trainer/pull/966,
fix/issue-956-pit-field-adjudication,9257b3a. Only .github/resolve-gate-dismissals.json:
2 review_instance_v1 rows bound to964,d800,review5879407247,cursor,exact path/title/
line18 and976. Pinned parser+positive match pass; changed SHA/review/line/title
controls stay blocked. Three existing row values unchanged; this one ledger has
LF normalization for whitespace checks. Public commit SHA strings explicitly
allowlisted inline; secret scan passes, no detector/baseline changes.

Companion based on main66861e4 in isolated nested worktree, currently draft while
full local/hosted CI runs. It must pass independent exact-head review and full
actual final findings gate before merge. Only after its rows land on trusted MAIN
may unchanged964 be re-evaluated through the full enforced preflight and merged.
No actual deployment has occurred at this checkpoint.

## Current acceptance and runtime

Original code: local5493passed/34skipped; hosted build/policy/conformance green;
native1002assertions/inspectedPNG; targeted124pass. Real experiment INCONCLUSIVE:
0 usable archives; frozen183files/22sessions unchanged and no cold setup provenance.
Actual counterbalanced >=30% operator timing and real setup application/readback
remain unverified. Keep956 OPEN; do not arm or fabricate these results.

Resume18:43 readback: rig owner null,no ACS/CM; same GamePoint16088/12264/29236,
Steam8524,SimHub2348; health buildabcf1a9/screen_peers1; settings SHA unchanged
ffb1c4bb850fb2cfea4bee99b9b8b1f789c540d6a1f88218228506ae97b1a65b.
Pressure experiment flag unset in process,user and machine environments. COM6
303A:1001 serial3C:0F:02:CF:5A:20; no port/runtime/firmware action.

Next: finish966 CI/review/gates/merge, repeat964 exact-head gates, acquire fresh rig
ownership, preserve backups, safe primary FF and rebuild/final bundled+Lua proof;
fresh simulator/BIN PNG inspection before gated PIO upload, actual device framebuffer
and default-off WS readback, restore normal launcher/minimized state and955 shadow.
No live pressure application. Publish this one dated owned node after final results;
preserve earlier local blocked note and raw failure/diagnostic records.
