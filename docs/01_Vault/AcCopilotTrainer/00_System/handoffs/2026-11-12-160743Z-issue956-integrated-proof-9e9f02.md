---
type: handoff
status: active
created: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-155004Z-issue956-prototype-9e9f01.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
---

# Issue956 integrated prototype proof

Source carrier PR964, branch feat/issue-956-pit-prescription-cards. This is the
bounded explore experiment, not live feature qualification. Preserve956 open;
use Refs only. All original acceptance clauses remain, none waived. No outside
issue/PR/chat created; three in-run helpers returned their assigned evidence.

## Integration and corrected failures

Python GET/decision and pinned authenticated trainer RPC now use the actual
Lua setup library. Strict separate axle data supplies pressure/thermal targets.
Actual pit-box state is checked immediately before each CSP setter; broader
reset permission is insufficient. Complete batch validation precedes writes;
fresh complete final readback precedes verified_applied. Reject/expiry do not
write. Uncertain/partial application stays accepted_unverified; reconnect only
reads back and never automatically retries application.

Default-off AC_COPILOT_PRESSURE_EXPERIMENT=1 trial switch prevents GET from
issuing proposals and Accept from applying unless explicitly armed. Safe Reject
and accepted-result readback remain available. No permanent environment change,
firmware upload, rig start, driving or live setup mutation occurred here.

Independent review reproduced a P1 introduced store race: documented CLI rebuild
could overwrite a just-accepted row with its stale proposed copy. Exact receipt:
.scratch/issue956/review-store-race-c85e5a0f/receipt.json. Fixed by a shared OS
transaction lock covering complete journal/save/upsert/rebuild operations, nested
within the thread lock. Fsync precedes authorization. Subprocess regression proves
rebuild and acceptance serialize and the accepted row cannot be authorized twice.
The persistent .lock companion is retained; OS ownership releases on process exit.

Also corrected an overconstraint in the prototype: requiring a managed human
certificate would exclude normal driver archives, while canonical attribution
registration explicitly cannot certify human control. The engine now follows
qualify_archive.allowed with current expected combo; known AI/shared restrictions
still deny. Legacy allowance is not experimental human-source certification.
The prior checkpoint's stricter authority wording is historical, superseded here.

## Observed software/device emulation

- Real-token WebSocket registration/import, temporary journal files, production
  loader/engine, strict FRONT/REAR tyres.ini/LUT reader, actual Lua modules and
  disk journal exercised together. Only absent/unsafe CSP SDK calls are adapters.
  Four-corner mixed direction applies once with complete cold readback; touch
  duplicates/reconnect keep4 setter calls and1 decision row. Pit-exit control and
  reconnect keep0 setters and accepted_unverified. Both synthetic tests pass.
- Domain/optimizer/transport/Lua/tyre/screen targeted suite117 passed. Synthetic
  positives validate integration and safety branches, not real discrimination.
- Full ci-fast second run passed5483 tests,34 skipped,87.38% coverage. Initial
  global-Python attempt failed installed MCP-v1 export collection. Reused the
  repository's established venv (MCP2.3.0); no global package changes or skips.
  Final integrated full-CI run remains pending at this checkpoint.
- First capacity test demonstrated actual64KiB LVGL exhaustion:12 spinner rows
  left2776B before saved rows/card; malloc assertion caused30s native timeout.
  Fixed by rendering4 spinner and4 setup rows/page, preserving12/64 caches.
  Native pointer navigation reaches all3/16pages, preserving full name/path ACK
  correlation for duplicate names across destroyed/rebuilt widgets.
- Final native run908 assertions passed; full card plus64 setups/12 controls
  coexists with minimum16992B free at measured page boundaries. This is not an
  exact transient high-water. Allocator integrity passes; pool remains65536B.
  Final PNGs personally inspected by helper and root, including first/last pages:
  .scratch/screen-simulator/runs/20261112T160615Z-f35113fe/.
- Final serial firmware build passed, RAM145428/327680, flash760145/6553600.
  Only public template headers used for compilation, hash-checked then removed.
  Real credentials untouched; no upload. Source provenance is in native receipt.
- Hosted draft CI initially caught41 entropy false positives in the frozen
  inventory. Audited every finding as a source SHA/ledger SHA or lap/session ID;
  added only that file's baseline rows. No existing baseline row/metadata changed,
  no detector disabled, no frozen source bytes changed. Final hosted CI pending.

## Retained real acceptance and next action

Frozen inventory remains INCONCLUSIVE:0 usable adjudicated pit returns, not12.
183 original files lack cold setup binding and pit-return event observations.
No retrospective repair or prediction-tuned relabeling. Manifest hash remains
ce7cf4a7816c703a2658ff46fa88a15a9d7ba9a90f0647a484424c9044764c24.
The >=30% actual counterbalanced operator timing has not run. Neither synthetic
integration, screenshots nor fast scripted touches substitutes for that result.

Read-only rig probe: lock owner null; SimHub/Steam present; no ACS in the scoped
process list. Existing sidecar /health reports status ok and screen_peers1;
omitted/null projection fields prove nothing further. Preserve those processes.
.operational-dod.json absent. Next: finish full CI, exact-head self-hosted review,
merge/barrier and distribution checks, then the physical-only operator boundary.
Native flash prerequisite must be rerun if firmware changes. Keep trial inactive
outside the authorized bench; no physical acceptance has been inferred.
