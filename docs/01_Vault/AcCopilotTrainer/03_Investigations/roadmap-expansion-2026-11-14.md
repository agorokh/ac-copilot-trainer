---
type: investigation
status: active
memory_tier: canonical
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14-evidence.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
---

# Roadmap expansion decision slate (2026-11-14)

- **Repository:** `agorokh/ac-copilot-trainer`, code read at `486ff69b`, `origin/main` `10e1f9b5`.
- **Tracker:** umbrella [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401) ([summary comment](https://github.com/agorokh/ac-copilot-trainer/issues/401#issuecomment-6873846486)); finalists [#988](https://github.com/agorokh/ac-copilot-trainer/issues/988) (`REX-20261114-01`) and [#989](https://github.com/agorokh/ac-copilot-trainer/issues/989) (`REX-20261114-02`).
- **Qualification cap:** `explore`. The run is **provisional**: 3 of 6 council seats answered and one challenge seat timed out. Detail and all sources are in the [evidence annex](roadmap-expansion-2026-11-14-evidence.md).

## Residual opportunity

The 2026-11-11 slate is spent: #955 closed, #956 is inconclusive on a rig-cap stop, #957 is held.
Every acceptance so far is engineering acceptance. Two links between the software and a faster
human are missing, and neither is owned:

1. **No lap can be positively human.** The policy checks for `verified_human_control` evidence
   that nothing produces (E-001 to E-003). #957's promotion gate is therefore unreachable, and
   #529 G3 depends on the operator hand-picking sessions.
2. **No record of what coaching the driver received.** Cue exposure is never persisted (E-007),
   so no analysis, however careful, can relate coaching to driving.

Two cards follow. A third was considered and declined.

## Card 1: `REX-20261114-01` capture-time human-control attestation

```yaml
id: REX-20261114-01
revision: 1
parents: []
decision: advance
qualification: explore
council_status: provisional
beneficiary: "The operator as driver, and every consumer of human evidence (#957, #529 G3, card 02)."
current_problem: "authority == 'human' is unreachable; human laps are indistinguishable from vendor-AI laps by their own labels."
changed_outcome: "A human-driven lap leaves capture with hash-bound verified_human_control evidence or an explicit unverified(reason)."
assets_to_mechanism: >
  Existing consumer (lap_qualification.py:590-599), the read-only control-map probe (E-004), the
  vendor practice record's AI-intervened label (E-005), a cockpit declaration on the accepted
  touchscreen or a spare button, and the hash/session-bound producer pattern in PR #986. A
  default-off producer combines them and abstains on any missing, stale or ambiguous signal.
missing_prerequisites:
  - "Native game-AI state signal is unverified (E-006)."
  - "Vendor-record coverage for every session is unknown (one observation)."
  - "PR #986 is unmerged and edits lap_qualification.py; sequence after it."
mundane_substitute: "The operator hand-picks human sessions, as #529 G3 waits on today."
prior_art: "Not searched this run. An internal prerequisite; no external novelty is claimed."
hardest_assumption: "Each known non-human control path is observable at capture with a fail-closed signal, so absence of evidence never certifies. Vendor AI driving is the weak one: its only evidence is a separate record joined by time and combo."
dissent: "Pass 1 (perplexity, mistral) proposed a telemetry classifier. Pass 2 (chatgpt, mistral) rejected it: smooth humans and human-like AI are confusable, and the 174 known AI laps test rejection only. chatgpt: a declaration does not establish absence of assistance, and zero observed errors is not zero risk."
discriminating_test:
  inputs: "One rig session, labels fixed in a manifest before the producer runs: >= 6 human laps, >= 4 project-autonomous laps, >= 4 vendor-AI laps (>= 2 with AI enabled mid-lap, >= 1 with the vendor record missing or ambiguous), native-AI laps if a signal is found. Offline: the 174 attributed laps."
  comparator: "Current policy (everything legacy_unknown) and operator hand-picking."
  prediction: "0 non-human or mixed laps certified; >= 5/6 human laps certified; every degraded case abstains with a reason."
  pass_if: "Prediction holds, evidence is bound to the archive payload hash, and qualify_archive(use='human_progression') allows certified laps and denies the rest."
  fail_if: "Any non-human or mixed lap is certified, or any certification lacks hash binding."
  inconclusive_if: "Fewer than 6 human or 4 per non-human arm captured, or the vendor record is unavailable for the session."
  resource_cap: "1.5 engineering days and one rig session <= 45 min with the operator present. Proposed, not granted."
  stop_rule: "First false certification halts the test and the producer stays disabled."
  allowed_actions: "Feature-branch code and tests, read-only probes, default-off producer. No edits to raw archives and no relabelling of legacy laps."
  retained_evidence: "Label manifest, per-lap attestation records, and the 174-lap offline scorecard."
reopening_or_change: "If the vendor-AI arm cannot be excluded, the producer abstains globally and the card returns to hold."
next_owner: "orchestrate, after operator approval of the bench session."
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
evidence_ids: [E-001, E-002, E-003, E-004, E-005, E-006, E-010]
```

## Card 2: `REX-20261114-02` coaching-effect trial layer

```yaml
id: REX-20261114-02
revision: 1
parents: []
decision: advance (stage 0 only; stage 1 gated)
qualification: explore
council_status: provisional
beneficiary: "The driver, and the operator deciding where scarce seat time and roadmap effort go."
current_problem: "Nothing measures whether a cue changes the driving it targets."
changed_outcome: "Every session records the coaching delivered, and one randomized session yields the first causal estimate of whether a cue reduces its targeted error."
assets_to_mechanism: >
  The peek/commit seam in CoachRuntime (E-008), per-pass diagnosis, and the replay harness.
  (a) An append-only exposure journal: each ARMED approach with corner, root, lap, eligibility,
  assignment and outcome. (b) An opt-in trial mode that randomizes speak versus withhold at each
  eligible ARMED approach, logged before the corner. (c) Randomization-inference analysis.
missing_prerequisites:
  - "Card 01 must pass before the human session counts."
  - "Stage 0 must show the trial can be informative for this driver."
mundane_substitute: "Equal-duration uncoached practice plus the existing session review."
prior_art: "Micro-randomized trials (W-008). No randomized sim-racing coaching study was found (W-006), which does not show none exists."
external_provocation: "Concurrent feedback gains vanished at retention in a driving simulator (W-002). Evidence status: one lane-keeping study, not racing."
hardest_assumption: "A cue's effect on its targeted error is large enough to separate from this driver's pass-to-pass variation within one affordable session."
dissent: "chatgpt: defer the whole card until attestation passes and feasibility is shown, since #529 G3 already owns a weaker drill test. perplexity and mistral: fund this first. Resolved by staging. mistral: error magnitude is not lap time; adopted as a guardrail."
discriminating_test:
  stage_0: "Offline, zero seat time. Replay >= 3 retained analysis-eligible sessions through CoachRuntime with the journal on. Report ARMED approaches per lap and targeted-error variance, then simulate the minimum detectable effect for a 90-minute session. Proceed only if >= 40 ARMED approaches are projected and the detectable effect is <= 25% of baseline error at 80% power. Stop if it exceeds 50%."
  inputs: "Stage 1: one car and track, one session <= 90 min, all laps attested by card 01, 5 uncued laps before and after the randomized block."
  comparator: "Withheld ARMED approaches in the same session."
  prediction: "Cued passes show >= 10% lower targeted-error magnitude than withheld passes."
  pass_if: ">= 40 usable randomized approaches, a >= 10% reduction with one-sided randomization p <= 0.05, and cued passes not slower through the corner by more than 0.05 s on average."
  fail_if: ">= 40 usable approaches and the 95% randomization interval excludes a 10% benefit, or cued passes are slower by more than 0.05 s with p <= 0.05."
  inconclusive_if: "Fewer than 40 usable approaches, missing attestation, or an interval spanning both."
  retention: "Reported descriptively. It is confounded by practice and is never part of pass or fail."
  resource_cap: "2 engineering days, half a day for stage 0, one human session <= 90 min, 0 s of autonomous-driver rig time. Proposed, not granted."
  stop_rule: "Do not schedule stage 1 if stage 0 stops. Abort the session if any assignment is logged after its cue anchor."
  allowed_actions: "Feature-branch code and tests, offline replay. Trial mode is default-off and default coaching is unchanged."
  retained_evidence: "Exposure journal, seed and assignment log, stage 0 feasibility report, randomization-inference scorecard."
what_success_changes: "Per-root effects decide which cue families earn further work and give #529 G3 a control it lacks."
what_failure_stops: "New real-time cue types pause until cue content is revised; effort moves to debrief."
file_seam: "New tools/ai_sidecar/coaching_trial.py and tools/coaching_lake/coaching_effect.py; a hook in coaching_runtime.py. Avoids coaching_ledger.py (#529 G3) and build_analytics.py (#957)."
next_owner: "orchestrate for stage 0 after operator approval; stage 1 needs a separate go-ahead."
issue: https://github.com/agorokh/ac-copilot-trainer/issues/989
evidence_ids: [E-007, E-008, E-009, E-011, W-002, W-006, W-008]
```

## Declined and parked

| Candidate | Decision | Reason | Reopen when |
|---|---|---|---|
| Faded or bandwidth cue policy | park | Its retention evidence was refuted at source this run. | Card 02 stage 1 shows a proximal benefit with flat or worse uncued laps. |
| Off-rig corner-decision rehearsal (chatgpt) | park | A second unproven intervention competing for the same seat time. | Card 02 reports a verdict either way. |
| Learned RL bench driver (assetto_corsa_gym) | park | No GPU on the rig (E-012); #529 owns driver pace; W-001 has no follow-up. | A GPU host is available and #529 G1 is formally stopped. |
| Synthetic student (autonomous cue compliance) | park | The driver is 27% off pace and fragile (E-011). | The autonomous driver holds a repeatable lap within 5% of a human reference. |
| Frontier ghost or pacer car | reject | No learning evidence (W-010), no injection route found (W-005), close to `REX-20261111-R2`. | A study or a working ghost route appears. |
| Reference-lap quality review (perplexity) | reject | `qualify_archive` and `lap_trace_validity` already serve it. | A bad reference is shown to pass both. |
| Grip-bin recovery (mistral) | reject | Owned by #529 and stopped at its prerequisite on 2026-11-14. | Not this skill's to reopen. |

**For `backlog-steward`:** live activation of the traffic gate (`traffic_gate_mode`) is still unowned.
