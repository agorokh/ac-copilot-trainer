---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T19:17:00Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/764
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-11-230443Z-post-merge-pr800-c1-21e389.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-11-212100Z-c1-issue751-live-scope-9d7b82.md
  - AcCopilotTrainer/01_Decisions/cold-side-temperature-tagged-friction-refit-2026-08-28.md
---

# C1 retained acceptance observed on the released rig

User invoked autonomous-deliver 764, manually closed the October 11 baseline, and held
rig runs while playing Minecraft. On October 12, "continue rig is yourth" released the
rig and revoked that hold. All four block:C1 issues (#749/#750/#751/#764) remain one unit.
After this SAVE's review, merge and distribution, close them together; no further C1
physical probe is needed. Final lifecycle receipt belongs on the existing owner #764.

## Pre-loaded substrate context

Task-specific direct Tier-3 naive/context-only query succeeded in ac_copilot; returned
context was truncated and mostly unrelated, so decisions were grounded in current issue
bodies/comments, ADR and dated vault nodes. No bypass. Harness: Codex desktop, Windows
AG_PC, native primary venv, authenticated gh and normal auto-alien. Secrets never output.
No new issues/chats/helpers; independent creation budget zero. This is the assigned SAVE.

## Original case, settled separately

Recovered original [#529 input](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-5237326977)
SHA256 b8895a2267ce5673c865ec186cfff3d2bf5993f17ae1719a5151ac3fba3915fa:
Huracan/Spa, laps 3, ggv-scale 1.0, scale-step 0.15, iterations 4, max-scale 1.2.
Read saved argv unchanged except fresh evidence path/current provenance. Code 3a4a1b0,
strict installed-app match. Entry retained plant had two merges, fit d9fa6dd00790,
SHA256 9aebda80f6c5a85e9571412589d826b48de305442b4cf886950907b102e4362a.

Baseline: 191237/180372/180377 ms, three archives, zero recoveries; thermally eligible,
refit no-op (adopted 0/raised 0). Scale 1.15 completed only its 172571 ms out-lap,
then seven recovery attempts exceeded the six-recovery cap. The envelope was falsified;
inherited plant remained byte-identical. Pipeline exit 0 means bounded falsification
handled correctly, not adoption acceptance. This original replay did not compound.
No thermal refusal was implicated. Interrupted October 11 evidence remains preserved.

## Conservative variant, actual retained compounding

Separately named variant on b0a296390a2540139906783fedb50d9a062255fe: same retained
Huracan/Spa plant, laps 3, baseline 1.0, step 0.10, two iterations, max-scale 1.10.
No thermal/pressure/validity/recovery threshold changed, no replacement plant or forced fit.
Normal pipeline completed, exit 0; each batch had three exact scoped archives and no recoveries.

| Stage | Scale | Lap times ms | Session | Driven fit |
|---|---|---|---|---|
| baseline | 1.0 | 192403, 180375, 180373 | 488da2c092ac | d9fa6dd00790 |
| envelope | 1.1 | 176811, 165951, 165960 | 67c685d83895 | d9fa6dd00790 |
| plant validation | 1.1 | 179151, 166715, 166745 | a33dd495abd7 | b403e5d5ac37 |

Refit adopted three lateral bins (130-140, 160-170, 220-230 km/h) and raised five
existing bins. Independently driven plant step AC-valid, flying spread 0.018%; retained
merges 2 -> 3. Actual persisted fit equals last valid drive; candidate and retained SHA256
dc6e90737b7128b446c947cb15ffe9d7454d3d6acce38792f6577b6e08b687a8.
Readback confirms eight monotone safe_g changes; longitudinal bins unchanged.
Fit mode thermally_stable, 4000 tagged rows, core cohort 65.91 C, pressure 22.386 PSI.
Historical cold-side cycle admission is separate off-rig evidence, not triggered here.
Final stage needed one bounded launch retry; final-attempt archive attribution stayed exact.
Refit flyers were slightly slower than the preceding envelope flyers; no pace-gain claim.

## Retained clauses and distribution

| Controlling requirement | Observed verdict |
|---|---|
| #749: refused thermal refits name term/value per lap | VERIFIED: shipped #766/#770/#776 diagnostics and tests; historical cycle reconstruction/refit evidence retained. Current batch did not trigger thermal refusal. |
| #749: recorded physics decision | VERIFIED: accepted cold-side ADR and cooling-cycle revision, no guard weakening. |
| #749: second-session already-refined plant adopts at least one lateral bin | VERIFIED: conservative variant inherited two merges, adopted three bins, drove valid plant step, persisted third merge on the identical driven fit. Original 1.15 replay remains falsified. |
| #750: flying-only, minimum two flyers, no under-evidenced durable verdict | VERIFIED: shipped #800 and full CI; original row preserved/ignored by production prior. |
| #750: corrected live rear-wing variance comparison | VERIFIED: October 11 original constraint, two flyers per arm, measured 0.95/0.95 margins, sample variances 24.5/924.5 ms^2; falsified, not promoted. August 10 correction withdrew the suppression-clearing claim. |
| #751: exact final-attempt scope, duplicate identity fail-closed | VERIFIED: PR #799 historical collision proof and 446 focused tests; new variant has three scoped archives per three timed laps even after final launch retry. |
| #764: MCP consumer compatibility | VERIFIED: primary MCP 2.3.0; fresh production bash wrapper lists five tools and query_file_patterns call_is_error=False, one block. No DB freshness claim. |
| Production scientist source/ledger | VERIFIED: primary b0a2963 imports match reviewed source hashes; actual drive margins 0.95/0.95, ledger two rows, historical row untouched, only eb598b9c2638a71d:0 selected. |

No C1 product source changed this turn; repair #800 and adjudication #801 remain deployed.
Prior make ci-fast: 4127 passed, 89 declared skips, coverage 86.70%. New SAVE make ci-vault
passed: 91 tests, three declared skips. Hosted required checks, independent exact-head
review and full pinned vault final gate precede merge. Prior council consultation had
1/6, no quorum/ratification.
Evidence is attributed telemetry, archives and reports; saved HUD captures do not prove UI.

## Clean rig and evidence pointers

Owned AC PID 17852 closed gracefully; native inventory found no AC or driving harness.
Existing Game Point sidecar PID 7712 remains owned by its launcher. Audio/SimHub ownership,
external control plans and other chat worktrees preserved. No further autonomous run armed.
Evidence (ignored): .scratch/issue764/huracan-resumed-20261012T181844Z,
huracan-original-falsification-receipt.json, huracan-step010-variant-20261012T184555Z,
huracan-variant-receipt.json, distributed-readback.json, scientist-receipt.json.
[Owner acceptance receipt](https://github.com/agorokh/ac-copilot-trainer/issues/764#issuecomment-6130957331).
Stop after C1 closure; this does not assert EPIC #529 G1 pace or unrelated #804 acceptance.
