---
type: handoff
status: active
created: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-163323Z-issue956-review-held-96a852.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-160743Z-issue956-integrated-proof-9e9f02.md
---

# Issue956 review repairs and candidate verification

PR964 round1 was terminal-reviewed on3a1643d at2026-11-12T16:33:04Z.
Independent cursor review5878205548 found a MEDIUM stale Reject queue bug.
Exact-head quorum passed, but pinned77fd081 full enforce gate correctly exited1
on the body finding despite zero inline comments. No merge or bypass occurred.
Record .scratch/issue956/gate-round1.log. This demonstrates why quorum alone
is not admission. The prior review-held node is a historical checkpoint.

Literal original sequences were frozen before modifying UI:
.scratch/issue956/review-5878205548/frozen-cases.json,
SHA5623d7c2906baa0e3c051216592e487786e23e0594db8049a8692ceebc963460.
At3a both Reject+Refresh and Reject+disconnect/reconnect dropped the explicit
Reject (0delivered,0mutations). Disconnect left stale pending1. Refresh actually
showed Refreshing because refresh flags mask the receipt message; this wording
refinement does not negate the lost decision.

Fix preserves safe Rejects with their original prescription/epoch for durable
logging, clears only superseded display-owned pending state, and scopes stale
Accept cleanup to its owning epoch. On identical frozen inputs both Rejects now
deliver1, mutations remain0, fresh GET remains1/pending, and disconnected stale
pending becomes0. New GET/current inflight decisions survive old replies/drains.
Final native run1002 assertions passed and all new review PNGs inspected:
.scratch/screen-simulator/runs/20261112T164518Z-db98faa9/.
Minimum capacity page-boundary free space remains16992B; not transient high-water.
Serial compile passes RAM145452/327680,flash760241/6553600; no upload.

An additional introduced input mismatch was reproduced with the literal
compound_index1.0 JSON context at unchanged3a: real loader produced no targets,
so the engine abstained. Saved context, archives and tyres.ini were replayed
unchanged after accepting finite non-bool integral numbers and casting only at
the strict axle reader: card proposes four correct mixed-direction changes.
Fractional/nonfinite/negative/bool remain rejected. E2E9passed; combined targeted
suite124passed, Ruff and diff checks pass. Evidence .scratch/issue956/compound-
float-exact-replay.json and compound-float-before/after logs. These are synthetic
integration cases, not the unperformed real12-case experiment.

## Candidate artifact and teardown scope

Candidate3a executable built before these repairs:
SHA326e7e052f046816e85441b2ab34e8346ab38d9ce1105a1c3fef3b0a63a111c5.
Five PYZ modules match committed3a code. Candidate --self-test exits0 with no
candidate process/listener afterward. Real isolated bundled WS GET returns
abstained/Pressure experiment inactive/changes[] and tablet routes return200.
All child configuration/environment isolated; no COM6/voice/tablet/SimHub action.
This artifact is not the repaired current revision and is not installed.

Extra source-interpreter frozen-supervisor harness left an owned onefile worker;
exact executable/create-time/argv cleanup was required and recorded. That failed
input is retained, not claimed repaired. Actual normal frozen GUI was then
exercised independently: returned exact candidate window, START, HEALTHY ownport
61879 and build3a, then actual Close. All3candidate processes exited without
manual cleanup; refreshed window inventory omitted the candidate, exclusive port
bind succeeded. Socket/HTTP probes timed out, not connection-refused. Primary
16088/12264/29236 identities remained unchanged. supervisor.py blob identical at
baseabcf1a9/head3a (783b0c6f68baefbfd74e2cd5e890666907e69c6e). No normal GUI
teardown defect observed; no unrelated source fix/carrier created. Receipts:
.scratch/issue956/candidate-proof.json and candidate-gui-teardown.json.

Next: single coherent repair push with fresh automatic exact-head review/CI;
keep its head fixed, audit feedback and execute full enforce final gate again.
Real discrimination stays INCONCLUSIVE0usable/12required; actual counterbalanced
operator timing unperformed. No retained clause waived, no activation/flash/rig
start/live pressure mutation. Preserve active chat and all diagnostic failures.
No outside-assignment issue/PR/chat created; helpers returned within this run.
