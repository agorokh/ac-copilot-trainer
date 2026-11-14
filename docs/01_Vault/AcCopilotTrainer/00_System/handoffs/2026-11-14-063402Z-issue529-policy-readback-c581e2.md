---
type: handoff
status: active
created: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-184420Z-issue529-retained-diagnostic-f793a1.md
  - AcCopilotTrainer/03_Investigations/issue-529-g1-mclaren-magione-2026-10-16.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Issue 529: current policy readback; operator decisions pending

**INCOMPLETE.** Operator invoked `autonomous-deliver 529` on 2026-11-13 Pacific.
No plant policy change, training, rig launch, G3 promotion or product-source edit occurred.
Owner record: https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6873161570.
Authoring harness: OpenAI Codex desktop, GPT-6 family; exact model build unavailable.

## Authority and current evidence

`gh issue view 529 --repo agorokh/ac-copilot-trainer --json state,labels` returned
`state=OPEN`, labels `enhancement,epic`; no protected start-gate label.
The operator-started creation budget is 2. No new issue/chat/task/helper agent was created.
This assignment's own handoff PR is not a creation under the skill's budget definition.
No independent finding was filed or assigned to another session.

Live #529 body, original gate comment 4952909767, and comments 6388233038/6388379995
retain operator decisions on native `authority="ai"` / `use="plant_fit"`,
REX-20261024-01 authorization, and qualified human session selection / G3 promotion.
Current #815 is CLOSED on engineering PASS; its Part B still isolates AI/shared/unknown
records from plant fitting and its body explicitly assigns this policy decision to #529.
#815 closure therefore does not supply the requested exception. No supersession was found
in the live #529 body or its 19 returned comments.

At source HEAD `3448597c00bf1ea00a0e7b38cba2116a5899c782`, the command
`git grep -n 'authority != "human"' HEAD -- tools/lap_qualification.py` returned line 590:
`if authority != "human" and use != "analysis":`.
The unchanged production `qualify_archive` and `observe_lap_tyre_state` were exercised
on all nine original Oct24 McLaren650/Magione archives through the canonical ledger.
Result: 9/9 `authority=ai`, plant-fit denied `control_authority_not_human:ai`,
human progression denied; thermal consumer 9/9 `fit_eligible=false` and
`temperature_aware_fit_eligible=false`, reason
`archive_qualification:control_authority_not_human:ai`.
These thermal results stop at qualification; they do not measure physical tyre eligibility.

The original 97.369 s flying archive retains SHA-256
`00b77d984b9975079ca542df54026cacb36d260578b40d061227894b8f4dadfa`.
All nine raw hashes and the canonical ledger hash matched before/after this probe.
The read-only rig-owner probe returned null; this is ownership evidence, not hardware acceptance.
Receipt: this worktree's `.scratch/issue529/20261113-policy-readback.json`.
Raw source: AC OneDrive Documents `cfg/extension/state/lua/app/AC_Copilot_Trainer/`
`ac_copilot_trainer/journal/laps/lap_20261024*.json`.

Additional result: all nine restrictive envelopes explicitly set `plant_fit=false` and
have empty `channels`; even `analysis` is refused with `unsupported_channel_unit:brake`
and further missing channel-unit/measurement reasons. A narrow authority exception alone
would not qualify these records. This is observed fail-closed behavior, not proof that
native channel units are wrong. Keep the existing ledger restrictions and raw bytes intact;
any future eligibility design needs explicit producer/evidence requirements.
The live-reference probe omitted expected_combo and is not a complete reference acceptance test.

## Retained requirement / output pairs

| Clause and controlling requirement | Settled status / next action |
|---|---|
| G0: measured sign, steer ratio and shifts in <=2 laps, measured origins | Historical handshake evidence retained; no new universal pass. |
| G1: unseen known-archetype combo within 5% of TT top-10 in <=20 autonomous laps, stationary environment; P2 asks three unseen combos | Unmet in retained Oct16 cold-start record (97.378 s, nonstationary). Oct24 95.226 s was seen-combo training. Today's qualification readback confirms the policy boundary, not new pace evidence. Await native-AI policy and REX-01 decisions. |
| G1b: novel archetype <=50 laps, uncertainty gating and safe-QSS fallback | Historical E30 fallback evidence retained; no fresh universal acceptance. |
| G2: beat combo/setup-specific 82.7 s Magione floor | Historical repeatable 81.505/81.519 s pair retained. Unrepeatable 80.791/95.122 s batch remains excluded from retained-capability proof. |
| G3: envelope/frontier cues and debriefs; human delta shrinks across sessions | Unmet/operator-gated. #938 and #815 issue dependencies are settled; select qualified human AC sessions and explicitly promote REX-03 before implementation/evaluation. |
| G4: one harness, false-green <5%, uncertainty/provenance, propagated falsifications | Restrictive attribution verified on these nine records; no global false-green rate or new physical acceptance measured. Preserve existing guards. |

The operational-DoD state file `.operational-dod.json` is absent in this checkout.
The unrelated #956 cap and disabled experiment were read in the newest handoff and preserved.
No product capability or owner status changed, so the #401/Roadmap pair was not rewritten.

## Resume decisions and coverage limits

Two questions are pending in this chat: authorize a narrow hash/session-bound native AI
plant-fit opt-in and the REX-01 experiment (max one engineering PR, two sessions / ten laps),
and whether to promote G3 with identified existing human sessions. Preserve human
PB/progression/reference and MOZA/import restrictions. Session selection requires dates/IDs,
driver (operator/son), combo and assistance; do not infer human control from legacy labels.
No answer is an approval. Once answered, refresh issue decisions, source and rig ownership,
then implement only the authorized unit through normal review/distribution and real verification.
The decision card's MP4-12C wording conflicts with the measured `ks_mclaren_650_gt3` identity;
use exact archive/content IDs when defining the next frozen experiment.

Direct Tier-3 MCP was unavailable. Documented task-specific prefetch queried `ac_copilot`,
returned limited historical context and warned of a possible stale endpoint. Vault/live
tracker/source evidence controlled. Council advice returned 2/6 with 4 provider errors,
quorum 2/3 unmet. No quorum, design ratification or PR review is claimed; irrelevant external
citations were discarded. The two answered voices recommended respecting the existing gates.

The initial probe imported the wrong private function name and failed before execution;
it was rerun successfully using public `default_attribution_path`. Windows literal-glob
searches were replaced with actual paths. Neither failure changed source or runtime state.

Verification: `make PYTHON=python ci-vault` passed (117 passed, 3 expected skips).
A consumer scenario loaded this exact node, parsed frontmatter and graph links, retained
all six gates, and reconciled qualification/immutability claims against the live readback
receipt: 12/12 checks passed. `git diff --cached --check` passed before submission.
