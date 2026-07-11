---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-11
updated: 2026-07-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/512
relates_to:
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/03_Investigations/issue-459-harness-product-2026-07-02.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
workspace: "ac_copilot"
---

# #512 — false-green-rate KPI: EPIC #154 Part-G residual delivered, #154 CLOSED

`/autonomous-deliver 154` (ultracode, maximum ownership). Reconciled EPIC #154 against **live** state
(its body's "Current Scope" list was ~3 weeks stale): children **#277/#278/#305 all CLOSED**, #459
and #244 CLOSED, and the determinism-lock preset shipped in **#460**. The one genuinely-undelivered
Closure-Criterion item was the **false-green-rate < 5% KPI shadow-mode report** — no artifact existed.

## What shipped — PR #513 (MERGED `28185e2`, closes #512)

`tools/ac_harness/false_green_kpi.py` — the **CI-measurable "known-failure discrimination" arm** of
the ADR's `false-green rate vs human reality (<5%)` bar. Runs a labeled corpus of the real failure
classes the harness exists to catch (each tagged with its historical bug) through the **real
production oracles** (imported, never reimplemented):

- `sequence_probe.evaluate_sequence` — #170 missing peer, #180 tire-temps, dead coaching,
  #182 lap-before-session, envelope spoof, #191 lap-timeout, empty stream
- `trace_replay.load_schema().car_fields` membership — out-of-schema read (mock-fallacy / L0 gate)
- `auto_drive.PhysicsStallDetector` — sim-death frozen packet, #460 physics-gone
- `hud_capture.liveness_score` — HUD blank / frozen
- `self_test.run_self_test` end-to-end — **report-path swallowing** (oracle FAIL must reach
  `SelfTestReport.ok`)

Extracted the sim-death rule from `rig_drive`'s inline loop into a unit-tested `PhysicsStallDetector`
(single source of truth; added coverage to previously rig-only logic).

## Key facts / decisions

- **Honest scope (Council-reviewed before build):** this is the off-sim arm; the live "vs human
  reality" arm stays the rig-gated `self_test`. An `out_of_scope` list names what only the rig can see
  (semantic coaching validity, audio, render correctness, long-run perf, persistence).
- **Gate is ZERO-LEAK, not a rate.** A 4-agent adversarial review caught that `false_red` was gated
  at `==0` but `false_green` at a *rate* (<5%) — dilutable as the corpus grows. Fixed: `ok` requires
  `broken_false_green == 0`; the `<5%` is the reported / live-arm bar only.
- **Anti-vacuity via test monkeypatch, not a production knob.** The self-hosted daemon flagged the
  `weaken` param as test-only instrumentation in the public API; removed it — the anti-vacuity
  guarantee is proven by patching an oracle symbol in the test suite.
- **`--json` output is contained under cwd** (`_resolve_output_path`) per repo convention (#204).

## Verification (observed, from merged `main` @ `28185e2`, own unmodified path)

`python -m tools.ac_harness.false_green_kpi` → **PASS, false_green_rate 0.0%**, 13/13 broken caught
(0 leaked), 8/8 healthy pass, all 13 classes covered; 22 KPI tests green; `make ci-fast` OK.

## Review rounds

3 bot rounds (Codex ×2: coverage-from-RED + sim-death timer-anchor regression; Qodo: `--json` path;
self-hosted daemon: test-only `weaken` knob) + the adversarial workflow. All fixed-forward, each with
a locking test. **EPIC #154 CLOSED** 2026-07-11 with a reconciliation comment.
