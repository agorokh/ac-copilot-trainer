---
type: handoff
status: active
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-16-200530Z-issue86-software-checkpoint-5d2b8a.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Issue86 native CSP integration: review checkpoint

The operator clarified that the working in-game Setup Exchange experience must
extend to the screen. The earlier external-proxy question is superseded. Do not
ask the operator to configure a separate proxy for normal operation. They want
agent-run software checks before any flash and human involvement only for the
remaining physical checks.

Owner86 stays OPEN. [PR862](https://github.com/agorokh/ac-copilot-trainer/pull/862)
is ready at21e6c9ac3798eb5a8e8365aa01f40b736856a254, not merged at this checkpoint.
Draft861 was replaced only because repo policy rejects codex/ branch names.
The current branch is feat/issue-86-csp-setup-exchange. Original primary remains
clean on70ed2fe with its original GamePoint processes3904/33628/2696 preserved.
No firmware flash or AC launch was performed in this continuation.

## Implementation and authority

The trainer's new setup_exchange.lua uses the installed app's legitimate CSP
machine-key/signing/session APIs against fixed HTTPS. Signing material stays
in CSP. The existing screen se.search/se.download contract reaches a private,
bounded, connection-scoped broker; callbacks cannot install after requester
loss or leak stale results to a replacement socket. Public result/ack injection
is rejected. The existing approved-root/exclusive/non-overwrite installer and
pits/reset loading gate remain. Nondefault proxy/test overrides still work;
both official service schemes select the native route.

Tier3 ac_copilot grounding succeeded. Council run0d2a67379c4a49398c66241e8e3efa11
reached3/3 quorum; HTTPS adopted, speculative auth redesigns rejected by synthesis.
Native signing/service success is still unverified; adapters are not that proof.

## Verified software

- Local make ci-fast passed:5092 tests,26 skips,86.25% coverage; lint, security,
  tracked-secret and CSP checks clear. The test process adds the existing scratch
  native compiler and excludes host AC_COPILOT settings; host settings unchanged.
- Current-source focused broker/LuaJIT/protocol/proxy batch152 passed.
- Required Linux CI on21e6c9a passed:5113 tests,16 skips,87.32% coverage and
  permanent native simulator61 assertions. Run38972034853; logs pr862-ci.log.
- Fresh permanent simulator run20261016T214442Z-e176d626:61 assertions,13
  captures, all inspected. Production UI/fonts/LVGL8.3.11/config at320x480.
- Supplemental real broker→production Lua→installer public frames through exact
  extracted firmware JSON coercion/Setup Exchange dispatcher:74 assertions,15
  captures; added success/failure PNGs inspected. Exact installer path/name used
  for auto-load; failed downloads cannot trigger another load. Scratch
  native-csp-dispatch/{extraction-proof.json,frames.json,test.log,captures/}.
- Packaged checkpoint2639c4e starts, serves both tablet routes and takes the native
  no-trainer error path. This is not the final merged/deployed artifact.
- Both earlier build-only firmware environments passed. Current45 production
  source/config/tool files match that compile staging exactly; binaries use public
  example headers and MUST NOT be flashed. No MCU source changed in862.
- Primary rig preflight: installed app provenance match, preflight ok for Porsche
  911 GT3 R2016/Magione. Existing health/metrics report one screen peer. That is
  not panel/touch/photo acceptance.

Local evidence is under .scratch/issue86/. Original launcher backup hash:
CB9A1BF587BDEC170152BF040BE3539ACF4812FCE00E170E4189124D00FB536A.
Isolated test listeners18765/19586 are closed. A leftover owned standalone
PyInstaller test child was identified and removed after a soft-close attempt;
the scratch helper now closes its owned process tree, rerun confirmed cleanup.
Original rig processes were preserved.

## Review and next action

Ready boundary2026-10-16T21:54:56Z, final head21e6c9a. Required600-second quiet
window elapsed. The daemon claimed this head; no eligible verdict had arrived
at the latest checkpoint. Canonical review deadline is22:44:56Z. Continue the
same bounded pr_wait command; do not reset its boundary or bypass the floor.

The old host-local waiter used unsafe Windows os.kill(pid,0). The repair already
merged in workstation-ops PR4039 as5b45005fe0a1bf61ce42bba394df1280b026d65a.
An unchanged git-archive export is under .scratch/issue86/waiter-runtime; exact
source and native live-child-survival/exit probes passed. Set process-local
WORKSTATION_OPS_ROOT to that export for waiter/gate calls. Host runtime and
primary checkouts were not updated. This was covered work; no duplicate filed.

After eligible exact-head review: read complete feedback, run the actual full
enforce final gate, refresh queue/head/labels, then head-bound merge. Prepared
scratch deploy_merged_gamepoint.py requires the actual merged receipt, takes the
rig lock, refuses active AC/foreign launchers/dirty primary, uses the canonical FF
primitive, builds/self-tests the merged EXE and checks runtime build plus screen
peer. It has not run. Keep primary/peer state protected.

Then use canonical GamePoint Stable AC and live_native_acceptance.py for real
CSP signing/search/authors/download/install/exact-path list/load and actual CSP
spinner readback. Repair failures before involving the operator. Only afterward
request physical touch/readability/photo acceptance. Earlier CONNECTED/all-three/
Back report is dated navigation evidence, not a waiver of86's four-leg/photo gate.

Author vendor OpenAI/Codex desktop; exact model ID unexposed. No outside-assignment
issue/task created. Two bounded in-run helpers returned, created nothing and
never touched the rig. No .operational-dod.json at the last check. This dated SAVE
is a checkpoint, not a completion claim; all live/physical rows remain unverified.

## BLOCKED: exact-head review did not arrive within the bounded window

The canonical50-minute round ended EXPIRED/round_deadline after the mandatory
quiet period and bounded waits. A fresh final evaluator returned4:
`quorum: pending (floor 1; gated by: none)`. The actual full enforce final gate,
using clean hub587c5e33210165d086cfa2928d96b5a87969ebe5 and author-vendor openai,
returned1: `resolve-gate independence floor unmet`. No merge was attempted.

Fresh commands and returned fields:

- `gh issue view 86 --repo agorokh/ac-copilot-trainer --json state,labels,title`
  returned OPEN, enhancement/epic/phase-5/python. Historical body label prose
  does not override those live labels.
- `gh pr view 862 --repo agorokh/ac-copilot-trainer --json headRefOid,state,isDraft,mergeStateStatus,statusCheckRollup`
  returned OPEN/non-draft/CLEAN, unchanged21e6c9a, required build/policy/conformance
  SUCCESS. Fresh complete reviews/inline/thread ledgers are empty, with no further
  pagination. The Qodo paused notice is advisory, not an eligible review.
- The daemon still reports round1 in_flight on21e6c9a; its latest lease expires
  2026-10-16T23:21:01Z. This is not a terminal refusal or clean review. Do not infer
  provider-wide capacity failure or ask the operator to configure credentials.

Exact logs: csp-final-{quorum.log,quorum-exit.txt,gate.log,gate-exit.txt,
 gate-summary.md}; fresh ledgers pr862-{reviews,comments,inline,threads,
 current-state}.json and issue86-final-state.json under .scratch/issue86/.
Quorum was evaluated with the original21:54:56Z boundary; it was not restarted.

Unblocker: the existing daemon round supplies an eligible independent review
of21e6c9a and its findings are settled. Then refresh the full ledger, quorum,
required checks, labels and actual enforce gate on that same head before merging.
Do not replay the unchanged expired round, create a trigger-only commit, or use
retired Codex/advisory reviews to replace the floor. A real adopted fix starts a
new normal round. Native service/install/car-load proof still follows deployment;
no physical checks should be requested from the operator before that proof.

Source changes are committed/pushed on PR862. This checkpoint and its small
Current Focus pointer are local vault SAVE changes, retained separately so the
pending code-review head stays unchanged. No additional carrier was created for
this review-capacity block. Publish this SAVE through the normal vault flow when
the delivery can continue. The existing issue86 owner record also receives the
bounded failure evidence. Main and the rig runtime remain unchanged.

Executed final preflight (PowerShell process environment, no permissive overrides):

```powershell
$env:WORKSTATION_OPS_ROOT = "C:/Users/arsen/.codex/worktrees/be60/ac-copilot-trainer/.scratch/issue86/waiter-runtime"
$env:RESOLVE_GATE_MODE = "enforce"
$env:RESOLVE_GATE_AUTHOR_VENDOR = "openai"
& C:/Users/arsen/Projects/ac-copilot-trainer/.venv/Scripts/python.exe C:/Users/arsen/.fleet-governance/scripts/ci_resolve_gate.py agorokh/ac-copilot-trainer 862
# Observed exit1: independence floor unmet.
```
