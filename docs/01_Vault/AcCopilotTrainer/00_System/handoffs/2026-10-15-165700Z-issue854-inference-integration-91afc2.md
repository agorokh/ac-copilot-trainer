---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-15
updated: 2026-10-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/854
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-15-155525Z-issue804-acceptance-b0dc.md
---

# Issue 854: provider boundary and bounded inference admission

The operator authorized strict 3050 inference, AC integration repair, LM Studio
qualification before switching, actual panel/game acceptance and continued GPU
monitoring. Application implementation is isolated under
`.claude/worktrees/issue-854-inference`, branch `fix/issue-854-inference`.
The runtime implementation is owned by workstation-ops#4004; root orchestrator
owns distribution, the global rig lock, real panel observations and driving.
No game/application was started/stopped by this implementation agent.

Canonical Tier-3 ac_copilot prefetch initially failed: the M4 service was enabled
but stopped, and degraded budget was exhausted. Root restored the normal service
with launchctl; this worktree's canonical hook then succeeded with issue/file
context before any code edit. No bypass or fabricated stamp was used.
The substrate recalled historical protocol/brain and configured-rig test context;
vault plus current source grounded decisions.

Implemented: required between-lap endpoint/model; native Ollama/common chat boundary;
finite/bounded generation profile; fresh exact-model/3050 placement attestation;
shared one-active/one-latest queue with corner priority; request-receipt deadlines;
worker ownership across waiter cancellation; existing lap/corner and Lua narration
semantics; state-consistent corner vocabulary and deterministic between-lap action;
CPU brain independent from narration enable; cached health readback; Game Point and
Lua-launch child profiles pointing at supervised loopback11435, without pretending
client CUDA env restricts server placement. Main 3060 rendering is not modified.

Actual frame-performance proof required instrumentation because normal unprivileged
ETW returned AccessDenied and automatic approval review rejected root's admin helper.
No alternate privileged bypass was attempted. Added opt-in `capturePerformance`
through existing authenticated action dispatch and `performance.frames` snapshots.
The documented installed CSP `ac.getUI().dt` is unaffected by pause/replay speed;
`sim.frame` is render-frame identity. Captures are <=120 seconds/20000 samples,
128 raw samples per chunk. Gaps/reset/invalid/missing chunks fail distribution proof;
paused samples remain recorded and are excluded from active percentiles. These are
CSP UI/render intervals, not OS presentation timings. Normal capture is disabled.

Verification at initial checkpoint: existing focused suite199 passed; inference
admission23 passed; render capture/topic guards24 passed; CSP API/UI checks passed.
Full make ci-fast completed4957 passed/26 declared skips/14 failures,86.93% coverage.
Five path-sensitive failures came from placing isolated temp under Git/.scratch;
all five passed with outside-Git cache temp. One legacy brain-off assertion was
updated to the required independent CPU behavior and passed. Eight native firmware
tests require `cc`, absent from PATH and checked standard compiler locations on this
Windows host; no firmware tests were weakened/skipped/changed. Authoritative full
Linux CI and independent review remain required, rather than claiming local fullCIgreen. Global Python had incompatible
MCP1.26; existing primary .venv has requiredMCP2.3 and is used without repointing an
editable install. Isolated explicit pytest basetemp avoids unrelated sharedTemp ACLs.
Branch policy rejects codex/ on this spoke, so compliant fix/ prefix is used.

Retained acceptance: independent exact-head review/full CI; host qualification and
fail-closed service deployment; same-artifact LM Studio verdict; actual panel and
normal-game frame distribution comparisons; build/install source proof. Issue854
stays OPEN and PR uses Refs. The previous NVIDIA0x133 is unresolved; this change
cannot certify PSU/noise/physicalRGB persistence or a hardware/driver cure.
Detailed configuration and capture instructions: docs/10_Development/15_Local_Inference.md.


Root live capture rules-2 initially failed closed invalid_frame with zero samples.
Added guarded LuaJIT FFI scalar conversion and exact 2^53-1 counter bound, plus
bounded raw scalar type/value diagnostics. Real LuaJIT uint64 fixtures now cover
conversion, duplicate handling and rejection beyond exact integer precision.
Root's rules-3 live capture confirmed cdata `713ULL` and numeric UI delta:
90.0088 seconds,5206 consecutive active samples,0 gaps/invalid/paused;
p50 17.2242,p95 18.4169,p99 18.9083,max20.5598 ms. This is rules-only proof;
inference comparison and actual model-panel consumption remain acceptance work.
Corrected Settings connection caption to sidecar coaching, avoiding an unproved
LLM-active claim while rules-only is selected. Focused Lua42 passed and CSP guards
passed. Root preserves all actual evidence and owns subsequent capture acceptance.

The consumer audit found between-lap NEXT LAP replies were entering the immediate
corner cache. The repaired route preserves a separate bounded focus, merges every
CPU brain hint/debrief, and projects only an applied, validated model focus into
existing coaching.snapshot with lap/ID/countdown/source. The existing P7 COACH
fallback renders its exact text without renewing repeated stale payloads; full
session.review still owns that screen. Real Lua receive/consume/projection tests
and executable shipped browser-function tests cover source, lap, expiry and review
priority. The prompt now includes the exact approved command required by validation.
Python and embedded HTML changes require a fresh Game Point build before acceptance.

Root recovered a preservation incident during autonomous acceptance: a later game
restarted with archives enabled and quota rotation removed four old files. Root
restored them create-new, byte-verified/backed-up all186 original archives totaling
532873576 bytes, and moved its own AI lap outside the personal journal with provenance.
Receipt: local GPUHealth/delivery-854/archive-restoration.json. This agent performed
read-only recovery comparison, no personal-data mutation. Each new game now requires
authenticated set/get boolean-false archive proof before the first lap plus before/
after journal hashes and preserved combo snapshot. Persistence alone is insufficient.
The restored 102183ms native Porsche/Magione archive builds five reference corners
but qualifies legacy_unknown; using it for transport acceptance certifies no human PB.
