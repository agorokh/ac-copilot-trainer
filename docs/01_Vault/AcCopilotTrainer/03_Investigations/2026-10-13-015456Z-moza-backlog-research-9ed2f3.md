---
type: investigation
status: active
created: 2026-10-12
updated: 2026-10-12
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-015456Z-backlog-steward-ledger-snapshot-9ed2f3.md
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# MOZA local data and current backlog — research, not delivery

Operator invoked backlog-steward and requested parallel GPT-6 Astra extra-high analysis.
All nine open issues were inspected against live GitHub and main `a71ad9ccf92942b6a6c69583639c1c90b6da4526`.
Mode report-only; no GitHub/source/device changes. No board manifest or override: board audit skipped.

## Findings

| Issues | Verdict | Remaining ownership |
|---|---|---|
| #813, #117 | live | #813 has open PR #814; #117 remains deferred hardware work. |
| #804, #534, #531, #529, #86 | partially-delivered | Preserve operator acceptance and not-this-cycle dispositions. |
| #627, #401 | drifted | Refresh unresolved-wedge brief and roadmap; no closure proposed. |

#534 A/B already shipped in PRs #689/#692; do not build another car-class authority/SimHub bridge.
#529 L0/L4/META shipped in #682; C1 retained-compounding acceptance in #812 does not prove G1 pace or G3 human improvement.
Finite-stall fixes (#730/#809) do not close the permanent CSP-wedge investigation #627.
Coordinate #813/#804/#531/#86 evidence sessions but keep issue ownership separate.
No new accepted scope evolution was minted; ledger preserves existing dispositions.

## MOZA evidence, local 2.1.7 release

`%LOCALAPPDATA%/MOZA Racing Lab/official/resource-catalog.json` has 52 resources, 51 downloaded.
`h5-view-artifact-cache` contains four readable `tracecore.view.v1` lap artifacts:
Spa/Huracan 161.793s and 191.116s; Magione/Porsche 911 GT3 R 2016 82.250s and 101.956s.
Numeric time/distance/position/speed/throttle/brake/steering/gear are present.
Distinct lap IDs verified; no human/AI/shared-control or condition provenance established.
All claim valid/finished, but Spa begins at ~1.75% progress and the slower Spa cache ends 1s early.
Rendered detail point counts differ from source sample counts: these are chart artifacts, not proven raw exports.
Official coach CSV/line/map/model payloads have opaque .moza bytes; no decryption attempted.
Training-evaluation snapshot summary is null; reusable coaching advice or logic has not been established.
185-file trainer journal inspection found exact same-combo matches for Spa191.116s and Magione101.956s.
Both are source=in_game/valid with 2000 samples; nearest-spline speed MAE is ~0.269/0.114 km/h.
Position correspondence is sub-metre on average; same-lap simultaneous capture is strongly supported.
Time origins/lap numbers differ; controller provenance remains unknown. Faster caches have no exact match.
Observed MOZA/trainer steering ratios differ by car (~2.50 Huracan, ~1.25 Porsche); no universal conversion established.
Cached drivingEvents include tyre-slip/counter-steer intervals: candidate diagnostic outputs, not causal coaching advice.

MOZA documents AI/shared control for AC/ACC, while [its AC settings](https://support.mozaracing.com/en/support/solutions/articles/70000686033-game-settings-required-for-ai-driving)
specify Stability Control 100%, ABS on, TC off, tyre blankets and optimum grip.
These recommendations do not establish the actual conditions of cached laps.
The [hardware SDK](https://mozaracing.com/pages/sdk) is not a documented Racing Lab export contract.
Voice absence and reference-redistribution permission are unverified.

## Proposed boundary

One future issue with Parts: passive qualification/import, source-neutral acceptance, offline report/oracle, shadow voice.
Reuse Coach v2/voice scheduler. Keep unknown/assisted laps out of human PB and driver progression.
`persistence.bestImportedReference` only accepts motec_csv; TT partial guards are source-specific;
`reference_lap.build_archive_record` defaults is_valid=true. None is sufficient MOZA qualification.
`driver_profile._is_driver_lap` excludes reference sources but does not prove control authority for in_game recordings.
Keep #529 and device-control integration separate. MOZA is a promising additional provider, not a verified TT replacement.

## Evidence and limitations

Full local report `.scratch/backlog-steward/backlog-and-moza-review.md`; per-issue records in `backlog-audit/`;
sanitized local schemas/hashes/validation in `moza-local/`; official sources in `moza-research/`.
These scratch files are host-local; durable issue evidence is in the linked ledger snapshot.
Tier-3 ac_copilot query succeeded through the local-data delegate after initial tool unavailability;
truncated older TT context was corroborative, not fresh backlog ratification.
Perplexity unavailable; official sources inspected directly. One Mistral critique adjudicated; no council quorum.
No live driving, voice acceptance, product implementation or external publication occurred.
