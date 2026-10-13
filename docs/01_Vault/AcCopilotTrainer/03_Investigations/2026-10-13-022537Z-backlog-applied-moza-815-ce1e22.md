---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-015456Z-moza-backlog-research-9ed2f3.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-022537Z-backlog-steward-ledger-snapshot-ce1e22.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-024319Z-moza-passive-qualification-815-2e7b78.md
---

# MOZA carrier and shipped-state backlog corrections

The operator authorized creation and backlog application on 2026-10-12 PDT.
[Issue #815](https://github.com/agorokh/ac-copilot-trainer/issues/815) now owns four Parts:
A passive identity/qualification; B normalized import/provenance; C existing diagnosis consumers;
D offline voice shadow/replay. Only Part A has begun; the importer and live activation have not shipped.

Eight preexisting issue bodies were updated with fresh pre-write concurrency checks and exact readback:
#401, #529, #531, #534, #627, #804, #86 and #813. Titles, states, labels, assignees and milestones were preserved.
#117 was left alone. #813 received a status prefix after PR #814 merged; its specification and checkboxes remain. No issue closure or Project board move occurred.

- #401 and its paired Roadmap now credit Coach V2 (#687), L0/L4/META (#682), enrichment (#689/#692),
  screen/HUD/voice polish (#680/#681/#690), finite scan fixes (#730/#809) and C1 evidence (#812).
- #529 retains the original cold-start budget/pace and human-learning gates. The conservative retained
  1.10 experiment and corrected falsified scientist comparison do not prove a faster setup or G1/G3.
- #534 credits A/B software while preserving installed-plugin acceptance and C/D/E operator decisions.
- #531 and #804 retain original acceptance checkbox states and distinguish historical deployment evidence.
- #86 follows the existing operator 1C smoke/photo gate; font/Setup Exchange/polish code is not pixel proof.
- #627 retains standalone C2, with current classification and parser corrections over the historical brief.

Exact originals, current bodies, planned actions, readbacks and inverse commands are in
`.scratch/moza-qualification/backlog-updates/`; creation evidence is in `tracker/`.
#529 has a second receipt correcting PR #800 attribution to matched measured margins.
The initial #531 verification normalized Windows line endings; byte-preserving comparison confirmed the
published text exactly matched the intended file, without another mutation.

The two earlier drifted entries (#401/#627) are now valid `live` carriers; all parked/C2 dispositions remain.
The resulting ten-issue ledger has four live and six partially delivered entries. This is not ten active jobs.

Validation is delegated to GPT-6 Astra with Extra High effort, with an independent rubric and review.
Selected MOZA/native inputs are read-only; credentials, control, opaque model decoding and raw trace
redistribution are excluded. PR #814 merged as b513d05 during this pass. A final refresh corrected every active/unmerged reference,
and the docs branch fast-forwarded to it. #815 now reuses track_map provenance/trace/phase/comparison
guards; future production work must refresh these seams. The dated owner checkpoint reports distribution
verified and retains physical acceptance; no independent review is credited for its operator-excepted merge.
Post-merge originals, updates and inverse receipts are in `backlog-updates/post814/`.
The prior delegated Tier-3 result was loaded; a fresh issue815/ac_copilot query succeeded at
2026-10-13T02:24:34Z and is saved in `passive/tier3-context.json`.
The parent runtime exposes no query tool. No memory/code gate was disabled. Skills used: backlog-steward,
github-issue-creator, start-task and vault-memory. This turn applies approved prior analysis; no new council
quorum is claimed. Passive qualification results will be linked in a separate dated node.
