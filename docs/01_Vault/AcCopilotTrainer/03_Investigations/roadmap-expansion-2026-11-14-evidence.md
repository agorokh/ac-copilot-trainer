---
type: investigation
status: active
memory_tier: canonical
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
part_of: AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
relates_to:
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-135149Z-moza-observed-ai-capture-815-d84bb7.md
  - AcCopilotTrainer/01_Decisions/rl-reference-lap-generation.md
---

# Roadmap expansion 2026-11-14: evidence, research and council records

Annex to the [decision slate](roadmap-expansion-2026-11-14.md). Code was read at `486ff69b`
(worktree) with `origin/main` at `10e1f9b5`; all times UTC on 2026-11-14.

**Effort cap stated before investigation:** 12 web searches, 2 source fetches, one independent
council pass, one retry round for missing seats, one challenge round, one source-check pass.
**Used:** 10 searches, 1 fetch attempt (2 pages, both blocked), 3 council calls, 1 grounder call.

## Repository evidence

Class is one of documented, implemented, observed, hypothesis. "Observed" means observed working
on the rig in a dated record, which this run did not repeat.

| ID | Claim | Class | Source | Limit |
|---|---|---|---|---|
| E-001 | `qualify_archive` accepts `authority == "human"` only with an evidence item `kind == "verified_human_control"` carrying a SHA-256. | implemented | `tools/lap_qualification.py:590-599` | Consumer only. |
| E-002 | No producer of `verified_human_control` exists. `git grep` finds the string once outside `tests/`. `register_attribution` raises `registration_cannot_certify_human_control` for any authority outside `ai`, `shared`, `unknown`. | implemented (absence) | `tools/lap_qualification.py:595,721-722` | A negative grep; an out-of-repo producer is not excluded. |
| E-003 | Unmanaged native archives resolve to `legacy_unknown` and are allowed, so no lap is ever positively human. #957 requires `authority == "human"` sessions, which nothing can produce. | implemented | `tools/lap_qualification.py:575-576`; #957 body | #957's gate text is the issue's, not code. |
| E-004 | A read-only `OpenFileMapping` probe detected absence of the `Car0`/`CarControls0` sections used by the project's autonomous driver. | observed 2026-10-13 | `2026-10-13-135149Z-moza-observed-ai-capture-815-d84bb7.md` | One sample at one instant; continuous probing during capture is untested. |
| E-005 | A MOZA AI-driven lap produced a native archive with `source=in_game`, `is_pb=true`. MOZA's own practice record labelled it AI-intervened. The two share no session identifier. | observed 2026-10-13 | same note | One session. Vendor-record coverage for every session is unknown. |
| E-006 | No reference to a native game-AI state field (`isAIControlled` or similar) exists in `src/` or `tools/`, including `ac_schema.json`. | implemented (absence) | `git grep` at `486ff69b` | Whether CSP exposes such a field was not verified. |
| E-007 | `CoachingLedger` is in-memory with no I/O. Delivered or withheld cue exposure is not written to lap archives, `journal/` or the lake. | implemented (absence) | `tools/ai_sidecar/coaching_ledger.py:17`; grep of `coaching_lake/`, `session_journal.py` | A cue timeline exists only in `voice/instrumented_sidecar.py` for acceptance runs. |
| E-008 | `CoachRuntime` peeks with `ledger.armed_root()` and commits with `ledger.due_prime()`. A withhold decision placed between them leaves the corner `ARMED` and spends no lap budget. | implemented | `tools/ai_sidecar/coaching_runtime.py:484,517`; `coaching_ledger.py:151-175` | Not exercised this run. |
| E-009 | #529 G3 owns "a human driver's delta to their own frontier measurably shrinks across sessions", with a 10-lap drill test that has no randomization, control or exposure log. | documented | #529 body; [comment 6388379995](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995) | G3 waits on operator-identified human sessions. |
| E-010 | PR #986 (open) edits `tools/lap_qualification.py` and adds `tools/ac_harness/native_attribution.py`, a hash and session-bound producer for native AI evidence. | implemented (unmerged) | `gh pr view 986` | Not merged; file overlap with card 01. |
| E-011 | #956 spent `12349.04 s` of a `14400 s` rig cap with 0/12 cases scored. #529 REX-01 stopped at its offline prerequisite with 0 bins recovered. | documented | `Roadmap.md`; #529 comment 2026-11-14T06:59Z | Explains why rig time on the autonomous driver is the scarce resource. |
| E-012 | The rig's inference GPU was removed on 2026-10-16 with no replacement. RL training was deferred on 2026-06-16. | documented | issue-854 notes; `rl-reference-lap-generation.md` | Blocks on-rig RL training. |

## Fresh external search log

| ID | Lens | Query | Extracted claim | Support limit |
|---|---|---|---|---|
| W-001 | Frontier | assetto_corsa_gym TD-MPC2 human demonstrations follow-up 2025 2026 | Remonda et al., NeurIPS 2024 D&B: SAC with human demonstrations reaches professional pace; about 6 h to beat most humans, about 4 days to match the best. | Search summary of [the NeurIPS page](https://neurips.cc/virtual/2024/poster/97499). No 2025-26 follow-up found. Needs a GPU. |
| W-002 | Counterevidence | guidance hypothesis concurrent feedback retention driving simulator | Van Leeuwen et al.: concurrent lane-keeping feedback improved practice, the effect vanished at retention, workload rose at delayed retention. | [TU Delft thesis chapter](https://pure.tudelft.nl/ws/portalfiles/portal/47866021/Thesis_v55_PMvanLeeuwen.pdf). Lane keeping, not racing. |
| W-003 | Prior art | sim racing AI coach 2026 trophi Track Titan Coach Dave | trophi.ai Mansell gives one live voice correction at a time. | Vendor pages. No published efficacy data found. |
| W-004 | Frontier | Gran Turismo Sophy coaching humans study | Drivers anecdotally learned from Sophy. | No coaching study found. |
| W-005 | Prior art | Assetto Corsa CSP custom ghost from reference lap | No documented route to inject a custom ghost found. | Negative search; proves nothing. |
| W-006 | Counterevidence | sim racing telemetry coaching randomized study (extended) | No well-powered randomized study. A 2026 Entropy paper with 6 iRacing drivers was non-randomized and an uncoached driver also improved. | Search summary only. [MDPI](https://www.mdpi.com/1099-4300/28/9/960) and PMC returned 403 or a CAPTCHA. |
| W-007 | Practitioner | reddit AI coach plateau or reliance | No first-hand threads returned; vendor and reviewer pages only. | Lens effectively uncovered this run. |
| W-008 | Frontier | micro-randomized trial within-person causal effect | Klasnja et al. 2015: re-randomize at each decision point; estimand is the proximal causal excursion effect. | [PMC4732571](https://pmc.ncbi.nlm.nih.gov/articles/PMC4732571) surfaced; the grounder could not re-verify it. |
| W-009 | Prior art | CSP Lua control of AI cars | Track option `ALLOW_CUSTOM_AI_MANIPULATION` exists in CSP docs. | Specific AI-control functions unverified. |
| W-010 | Counterevidence | lead-follow pacer or faster ghost learning study | No study found; hobbyist claims only. | Negative search. |

**Correction from the source check.** The evidence packet given to the council said bandwidth
feedback "retained better" (de Groot et al., *Human Factors* 53, 2011,
[doi:10.1177/0018720810393241](https://doi.org/10.1177/0018720810393241)). The abstract says the
practice advantage diminished at retention. The claim is withdrawn, and with it the main external
support for a faded or bandwidth cue policy.

## Council record

Convener: Claude Fable 5.2. The convener's own first pass was written to
`.scratch/roadmap-expansion/2026-11-14/pass0-convener-lock.md` before any seat output was read.
Run ids are in the council run store.

| Pass | Seat | Requested / served model | Status |
|---|---|---|---|
| 1 independent (`c5f534e7`) | chatgpt-projects | gpt-6-astra / gpt-6-astra (measured 2026-10-01) | answered |
| 1 | perplexity-sub | `turbo` / unverified | answered |
| 1 retry (`cdc456a2`) | mistral-sub | magistral-medium-latest / mistral-medium-2604 | answered |
| 1 + retry | gemini-sub | gemini-4-argon | skipped twice, circuit breaker open after 23 failures |
| 1 + retry | kimi-sub | kimi / unknown | auth 404, then breaker open |
| 1 + retry | grok-sub | grok-4.6 | promise-only reply, then late |
| 2 challenge (`b5c3afe0`) | chatgpt-projects, mistral-sub | as above | answered, shared context |
| 2 | grok-sub | grok-4.6 | CLI timeout after 80 s |
| Source check | perplexity grounder | unverified | answered; verified 2 of 4 claims, refuted part of one |

Pass 1 seats saw the same raw evidence packet and no candidates. All three ranked a
coaching-effect experiment first and human-control provenance second, matching the convener lock.
**Coverage gap:** Gemini, Kimi and Grok never answered; the challenge round had 2 of 3 seats; the
Perplexity model identity is unverified; two papers were unreadable at source. The run is
**provisional** and both cards are capped at **explore**.

### Adjudication of pass-2 contributions

| Contribution | Seat | Verdict |
|---|---|---|
| Baseline-to-retention gate is confounded by practice | chatgpt | Adopt. Retention is descriptive, never part of pass or fail. |
| Pass-level randomization is primary; ~7 corners is too few units | chatgpt, mistral | Adopt. |
| 40 opportunities are not 40 independent observations | chatgpt | Adopt. Analysis is randomization inference over the logged assignments. |
| Regression to the mean needs a third-pass rule | mistral | Narrow. Randomization already balances it; it only biased the retention gate, now removed. |
| Error magnitude is not lap time | mistral | Adopt as a corner-time guardrail. |
| Procedural attestation with abstention, not a telemetry classifier | chatgpt, mistral | Adopt. Reverses the classifier tests that perplexity and mistral proposed in pass 1. |
| Probe the control map throughout capture; declaration is not proof | chatgpt | Adopt. |
| Fund attestation first, defer the trial | chatgpt | Adopt for the human session; the offline stage needs no seat time and runs in parallel. |
| Third card: faded or bandwidth policy | mistral | Reject for now; its retention evidence was refuted above. |
| Third card: none | chatgpt | Adopt. |
