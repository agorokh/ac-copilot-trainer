---
type: handoff
status: active
created: 2026-11-11
updated: 2026-11-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/955
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-11-184220Z-issue955-shadow-aa3553.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
---

# Issue 955 CI recovery and autonomous input search

Current branch is feat/issue-955-traffic-coaching-eligibility, PR #960.
ci_policy rejected the app-default codex/ prefix. GitHub's supported branch rename
closed draft #959; #960 carries the same initial commit dc52285 on the valid prefix.
No competing delivery exists. Refs #955 remains, without a closing keyword.

The operator explicitly instructed this session to find inputs autonomously across
the machine and council/public sources; do not ask the operator to locate them.
The no-driving/no-live-actuation experiment boundary is retained.

CI attempts and corrections:

- System Python's installed MCP SDK lacked the required v2 Client export. The
  existing primary project venv has MCP 2.3.0 and the export; use it without
  changing shared dependencies.
- Full Windows run: 5403 passed, 34 skipped, three failures. Two Git-root tests
  were caused by my backslash-containing PYTEST_ADDOPTS: pytest shlex removed
  backslashes and made the temp root relative to the checkout. Use a forward-slash
  absolute --basetemp. Both original failing tests pass with that correction.
- The remaining setup callable fixture compared a Windows backslash path with
  setup_library's normalized forward-slash path. Normalize only that fixture's
  three injected paths with as_posix(); the original test then passes.
  No setup implementation or #956 prescription/firmware files changed.
- Expanded traffic + async archive suite: 60 passed. It covers stale/occupied/
  clear PRIME behavior and sticky contamination that resets on the next pass.
- Stock LuaJIT's whole-entry compile probe rejects BOTH pinned base bc1c935 and
  candidate at the 60-upvalue limit. The existing Lua 5.5 harness compiles the
  whole entry, and the new collector runs under LuaJIT. This does not prove CSP.
  LuaJIT assertions run in an isolated interpreter to avoid pytest faulthandler
  logging caught Windows SEH exceptions; nonzero/crash exits still fail the test.

Input evidence at 18:56:49Z: configured OneDrive AC replay directory has two
version-16 files, each cars=1. Hash receipt: .scratch/issue955-replay-inventory.json.
Broader C: filename scan found 3710 candidates; access-denied directories are
recorded in .scratch/issue955-machine-replay-scan-errors.txt, so this is not a
claim that every machine path was readable. Candidate triage continues.
AIST's primary page offers structured race data but requires an application;
AssettoCorsaGym's primary card shows single-vehicle fields, not a verified roster.
Do not use unsupported council suggestions as API evidence: one voice contradicted
the AIST page and proposed unverified CSP hooks.

Retained clauses: accuracy (45 real approaches) unverified; same-clock unknown
handling verified synthetically with transport age unverified; quarantine verified
for captured synthetic inputs, legacy archives unassessed; actual CSP 20-car timing
unverified, mock LuaJIT timing below 1 ms. Full corrected ci-fast, exact-head review,
distribution and input acquisition remain. None created outside assigned PRs.
