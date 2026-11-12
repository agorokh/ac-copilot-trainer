---
type: investigation
status: draft
created: 2026-11-12
updated: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-12-215700Z-post-merge-pr968-742c9e.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/invariants/persistence.md
---

# Proposed fully autonomous acceptance for956

**Preparation only.** The operator selected "Prepare fully autonomous acceptance
criteria." This draft grants no implementation, trial activation, extra budget
or issue closure. The experiment stays disabled and956 stays OPEN. Existing
acceptance remains controlling until the replacement below is explicitly adopted.

**Execution is blocked** until the owner adopts this protocol, authorizes the
specific temporary bench data use/actuation and budget increase, and the permit,
admission checks, sealed oracle and authoritative write instrumentation are
implemented, reviewed, tested and deployed. A document approval is not proof
that those implementation prerequisites exist. This draft implements none of them.

The proposed result is an autonomous engineering trial: correct bounded pressure
decisions, timely touchscreen execution, authoritative application and audit proof.
It makes no claim about human decision time, driver benefit, lap-time improvement,
general AI coaching eligibility or clinical/statistical reliability beyond12 cases.

## Changes requiring explicit adoption

| Existing condition | Proposed replacement |
|---|---|
|>=30% faster median human decision-to-apply vs report/raw spinners | Every scored autonomous workflow completes within90s of evidence reveal, including reasoning, rendering, input, logging and native readback. No human speed claim or paired historical replay. |
|Collect/adjudicate all12 snapshots before predictions | Pre-register12 slots, condition rules, candidate and oracle hashes first; freeze each real return and its independent label before its card is generated. No later candidate change or outcome-driven replacement. |
|Human-eligible native inputs through ordinary production admission | Explicit956-only native-AI bench admission, separately authorized and reviewed. Production AI restrictions remain unchanged. This mode does not exist yet. |
|Missing-target trap within the real12-case cohort | Six real traps cover cold, short stint and measured lock/scrub; missing-target coverage remains mandatory in a separately reported fault-injection suite. |
|60min cumulative rig cap;1.5 engineering days | Proposal:240min cumulative rig cap; at most2 additional engineering days. Previous consumption is retained, not reset. |

## A. Prerequisites before scoring

- Implement and document a visibly marked **956 AI BENCH** mode in normal Game
  Point/Pocket Technician. Use the existing sidecar, transport, journal and Lua
  setter; no parallel cockpit or second sidecar. Its default is disabled.
- Keep `tools/lap_qualification.py`, #529 modules and ordinary
  `qualify_archive(use="live_reference")` admission unchanged. AI stays AI and
  analysis-only in that policy. `analysis.allowed` alone never authorizes writes.
  A new owner-approved bench permit must separately authorize this data use and
  controlled actuation; it is a proposed policy extension, not an existing right.
- Extract one shared numerical evaluator if necessary; retain all current
  thermal, slip, completeness, setup and quantization checks in both wrappers.
  Bench admission requires valid canonical analysis qualification plus observed
  native-AI attribution, sealed run/case hashes, current session/car/track/layout/
  compound/setup identity, actual rig owner, expiry and explicit bench authority.
  Ordinary endpoints must reject bench cards. No export to coaching, progression,
  references or plant fitting. Test each boundary negatively before deployment.
- Use the existing authoritative `experiments.jsonl` store with explicit
  run_id/case_id/mode/authority metadata and deduplication; no competing decision
  store. Additional receipts are evidence, not authoritative application state.
  Disconnect/restart/owner loss/expiry/scope change disarms the permit; no auto-rearm.
- Review and deploy this implementation through exact-head review and green CI.
  Prove one excluded cold/short pilot and one excluded genuine pilot end to end.
  Pilot failures are retained and pilots never enter the12-case score. If the
  native AI cannot satisfy unchanged genuine-case guards, stop INCONCLUSIVE.
- Before launch, verify all185 preserved raw hashes and a retention mechanism
  that prevents rotation from deleting any original or newly enrolled archive.
  Copy-after-lap alone is insufficient: native rotation can delete old sources
  first. Use a documented capacity adjustment or reviewed preservation-aware
  retention change; otherwise do not collect. Never edit or fabricate raw laps.

## B. Twelve real cases and independent labels

Register slots G1-G6 and T1-T6 before collection, with a fixed enrollment order
and input-only exclusion rules. All slots are distinct actual pit returns with
disjoint measured lap windows. Choose the first admissible return for each slot;
retain every attempted/excluded return and reason. A candidate failure is never
excluded or replaced. No reused screenshot, overlapping stint or synthetic case
can fill a real slot. New cases start at0/12; the two earlier cold AI laps are pilots only.

G1-G6 require two consecutive complete valid native flying laps, both numbered
>=2, on one unchanged selected setup and compound. Setup path/hash/four cold
snapshots and target-content hashes must be captured contemporaneously. Require
>=0.6psi beyond the experimental +/-0.25psi deadband (>=0.85psi from authored
ideal) in the same direction on both laps for at least one corner. Retain current
thermal/slip/completeness gates: no broader temperature interval or lower quality
threshold to make the dataset pass. At least3 high-pressure and3 low-pressure
genuine cases are required, so both correction directions are exercised.

T1-T2 are real cold outlap returns; T3-T4 are real stints with fewer than two
flying laps; T5-T6 contain measured wheel-lock/scrubbing or transient-spike
evidence. Prescribe the intended condition in advance; label from actual native
measurements, not intended control commands. If a condition cannot be produced
through documented rig controls within the cap, leave it unfilled and report
INCONCLUSIVE. Missing targets, forged timestamps and deleted fields are not real traps.

An independent deterministic adjudicator reads preserved raw sensors and authored
targets without importing/calling the prescription evaluator. Freeze its rules
and code hash before enrollment. An independent reviewer checks its formulas and
test vectors before execution; no human adjudicator is required during the run.
For each slot it seals source hashes, measured conditions, expected per-corner
direction/abstention and admissible native step before the candidate sees data.
Disagreement or ambiguous ground truth prevents enrollment by the pre-set rule.
The acting agent receives neither the hidden label nor a precomputed answer;
enforce this with a fresh isolated acting context and restricted evidence access.

**Accuracy PASS:** all12 filled;0 wrong-direction or contraindicated actionable
cards;>=5/6 genuine cases produce at least one correctly directed bounded change
with0.5<=|delta|<=1.5psi, named corners, units and lap window;>=5/6 trap cards
explicitly abstain. Every proposed corner must be correct. A single wrong or
contraindicated recommendation FAILS and stops live application immediately.

## C. Autonomous time and actual application

Use only the current case/current session; no historical-to-live identity rewrite,
hidden card pre-generation or assumption that a replay/reset API exists. Separate
capture/adjudication from the acting agent; keep candidate outputs unavailable
until enrollment and label sealing finish. Hold the car in its actual pit box.

Start a monotonic timer immediately before the first case evidence is revealed to
the acting agent; include all subsequent inference, card requests, transport,
screen rendering, taps, decision logging and readback. Record model/version,
prompt hash, tool configuration and wall-clock/frame evidence. Stop only after:
(a) Accept has one durable decision and fresh authoritative values confirm all
four pressures, or (b) explicit abstention/rejection plus fresh unchanged values.
No human choices are needed. Do not stop at a tap, acknowledgement or health response.

**Workflow PASS:** all12 scored workflows reach a truthful terminal state in<=90s
**per case**, with a fresh timer at each case's first reveal;
the accuracy allowance above remains5/6 rather than silently becoming6/6. Every genuine
proposed card is accepted once and reaches `verified_applied`; abstentions make0
writes. Baseline and final values must agree exactly with the native supported
grid (0.001psi numeric tolerance). Actual current car uses1psi steps; do not
invent0.5psi clicks. Card TTL stays120s. A timeout/expired or unsuccessful scored
case FAILS workflow acceptance and is retained; never drop it from the denominator.
Report all12 durations, maximum and median. These are agent task durations, not
human savings or an end-to-end90s guarantee for capture/adjudication.

## D. Safety, retry and missing-data proof

In additional separately labeled trials, require all of the following. Retain
actual before/after native values, authoritative mutation-attempt/write counts
and durable journal state; unchanged values alone cannot prove0 transient writes.
If the current boundary cannot expose reliable counters, reviewed instrumentation
is a prerequisite, not a permission to substitute endpoint health as proof.

- Real pit exit after display and before Accept/retry:0 authoritative setup writes.
- Reject and TTL timeout:0 writes. Bounce/refresh/reconnect of one decision:
  exactly one immutable decision/id and no duplicate application. Reconnect may
  disarm rather than resume; replay still cannot write a second time.
- Partial/missing readback: never `verified_applied`; remain
  `accepted_unverified` until all values have genuinely been confirmed. Stop on
  uncertain application; no blind retry or speculative rollback.
- Separate software negative controls, at least one each: missing compound target,
  malformed/nonfinite target, unknown pressure units/bounds/step, changed setup,
  changed session/compound, and stale/missing native input. All must abstain or
  deny with0 writes. Reviewed faults are limited to derived/request boundaries;
  no deleting car content, rewriting raw archives or claiming live fault coverage.

## E. Budget, restoration and final verdict

Proposed total240min minus previously spent3139.772911s leaves11260.227089s
(187m40.23s), **only if the owner approves the increase**. Allocate20min for
setup/pilots,120min for capture plus scored interaction,35min for separate safety
trials and12m40.23s reserved for restoration. Every rig-held minute counts;
do not double-count the interaction budget or exclude waits/retries. Reserve the
restoration allowance before starting a run; stop earlier if teardown needs more.
Original60min cap and its460.227089s remainder remain current until adoption.

On any integrity loss, wrong action, uncertain application, lost owner or cap
boundary: stop, disarm, preserve evidence and use observed safe teardown. End by
removing the process-local trial permission, proving inactive ordinary and bench
paths, restoring exact settings/race/CSP bytes, verifying preserved archives,
releasing owned processes/listeners/lock and retaining other users' sessions.

**Overall PASS requires A-D plus observed restoration**, exact reviewed/deployed
source hashes and a complete scorecard. Fewer than12 usable cases is INCONCLUSIVE;
any retained threshold violation is FAIL. Missing proof is UNVERIFIED, never PASS.
Existing software/simulator proof may be reused only when unchanged and traceable.
Never close956 automatically or enable the normal experiment: publish the verdict
for the owner, with human UX and lap-time benefit explicitly unmeasured.

## Review status and current evidence

Grounding: current4d8eeed source, issue956, merged PRs968/969 and local
`operator-acceptance/postmerge-pit-probe/final-receipt.json`. Tier3 prefetch
succeeded with stale-endpoint warning; current source establishes current facts.
Council initial panel2/3 answered, quorum unmet; revised panel0/2 (provider
model/breaker/timeout failures). Final draft text review2/2 answered with dissent:
Codex found no textual contradiction; Mistral requested explicit blocking
prerequisites and per-case timing, now clarified. Its claims that hash freezing
and authoritative counters were absent were contradicted by B/D; its assertion
that1080s exceeds240min was arithmetically wrong. No implementation or full
architectural-panel approval is claimed. Accepted the warning
about unimplemented historical replay and explicit AI data-use authority. Rejected
unsupported suggestions to count two cold laps, shrink the real denominator, or
treat0.5psi minimum as incompatible with1psi native steps and1.5psi maximum.
Raw reviews are preserved under `.scratch/issue956/operator-acceptance/` as
`council-initial-final.json`, `council-revision-final.json` and
`council-draft-review.json`. Resolve the explicit
data-use extension during implementation review; "bench" labeling alone is no safeguard.
