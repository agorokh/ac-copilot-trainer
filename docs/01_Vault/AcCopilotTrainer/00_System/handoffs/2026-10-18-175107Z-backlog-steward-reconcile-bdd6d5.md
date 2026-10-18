---
type: handoff
status: active
created: 2026-10-18
updated: 2026-10-18
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-18-175107Z-backlog-steward-ledger-snapshot-bdd6d5.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-13-174032Z-backlog-moza-research-complete-e01865.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/pitfalls/linkage-autoclose-against-intent.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
---

# Backlog reconciliation 2026-10-18 — seven open owners, one premature auto-close

Report-only `/backlog-steward` over `agorokh/ac-copilot-trainer` at merged `main` `8fade2c`
(PR #876). Issue-only mode: the repo has no `ops/board_manifest.yml`, so no `gh project` call
was made. Tier-3 (`ac_copilot`, naive) returned prior-decision context; the verdicts rest on
`gh` state, merged-PR file lists, symbol greps on the tree and the 2026-10-13 ledger. Nothing
was labelled, commented, closed or moved.

## Verdicts (all evidence-grounded, ≥2 signals each)

| Issue | Verdict | What moved since 2026-10-13 | Next move (proposal) |
|---|---|---|---|
| #627 C2 | live | PR #876 shipped launch-report v5; open PR #877 (`ff82b29`, blocked on review) measures that #876's Car0-probe branch was never reached and moves the kill to `classify`'s post-go-live stall rule (`stall_seconds` 20 s floor, schema v6) | land #877; then one correction comment superseding the #876 root-cause claim; narrow header refresh (v6; v3/v4/v5 superseded) |
| #86 | partially-delivered | PR #858 permanent LVGL simulator gate; PR #862 native CSP Setup Exchange (`csp_setup_exchange.SetupExchangeBroker`, `setup_exchange.lua`) replacing the proxy; live service readback verified; packaged sidecar redistributed to `8907ddf`; operator removed `status:blocked-on-rig` + `not-this-cycle` 2026-10-16 | body refresh (rows for #858/#862, label statement, native-SE scope evolution accepted, `setup.load` positive branch operator-only by construction); then the operator four-leg smoke + on-glass photo |
| #815 | partially-delivered | nothing merged on the remaining acoustic path since the 2026-10-14 NO_GO; #531's PR #846 shipped `microphone.py` tablet capture — the available instrument for the failed mic sync | re-run acoustic acceptance after #877 using the #846 capture path |
| #529 | partially-delivered | mclaren 650 GT3 @ magione G1 datapoint (97.378 s vs TT P10 74.784 s, +30.2%, G1 not met); operator removed `not-this-cycle` 2026-10-16; PR #856 rebound Coach v2 to canonical geometry; #854 closed noting Coach v2 finds 0 canonical corners on the Magione reference | narrow header correction; operator decision on the G1 lever (cross-session plant compounding); the 0-corner residue is a candidate fold into G3 |
| #534 | partially-delivered | no code churn on `car_class.py` / SimHub plugin | keep; the operator SimHub plugin check can ride along with the #86 rig session |
| #401 | live | #813/#804/#531/#854 closed; #858/#862/#865/#868/#876 merged; #86/#529 unparked — none reflected in the body or `Roadmap.md` (updated 2026-10-14) | paired body + `Roadmap.md` metadata refresh |
| #117 | live | `firmware/` still `{keypad, screen}`; #627 still open so decision 2C's revival trigger has not fired | keep |

## Closed since the last ledger

- **#813 — premature auto-close.** PR #848 merged `2026-10-15T01:43:34Z` with `closingIssuesReferences=[813]`; the issue closed at `01:43:36` with no closing comment. The PR body says "this does not close #813"; the post-merge handoff (`2026-10-15-020500Z-post-merge-pr848-57e89c.md`) and PR #849 both say #813 keeps its separate scope. Its retained P7 clauses (operator-driven valid lap, moving numbered MAP, intentional-exit stale transition) were never dispositioned. Counter-signal: #531's autonomous P7 evidence in PR #849 covers most of them. **Operator decision:** record a closing-disposition comment accepting that evidence (preferred) or reopen.
- #531, #804, #854 — clean closes by the owner with settled tables. #854's honest limits are unowned residue (Coach v2 0-corner gate on the Magione reference; HA-voice contention untested; NVIDIA 0x133 cause unknown).

## Consolidation by files touched

No `merge-into-one-issue` block: every open owner except #815 carries `do_not_merge`, and no two
remaining deltas share a non-catalog source file. `sequence-only`: #117 → #534 Part C
(`firmware/arduino_fan_oled/` is the shared new tree); #877/#627 → #815 (rig reliability for the
autonomous Porsche/Spa run); #86 ↔ #534 (one operator rig session serves both). Everything else
`keep-separate`.

## Advisory order (ICE)

1. #627 land PR #877 (unblocks the operator's Stable AC button; measured; PR exists).
2. #401 paired refresh (cheap; the roadmap currently misleads on four closed issues).
3. #86 body refresh, then the operator smoke/photo session (software is live-verified).
4. #815 acoustic acceptance re-run with the #846 microphone path.
5. #529 G1-lever decision before more rig time.
6. #534 operator SimHub check (ride-along). 7. #117 parked.

## Artifacts

Ledger overlay `.scratch/backlog-steward/ledger.json` (gitignored); durable snapshot linked above
(fenced JSON, `run_id bdd6d5`); scratch report `.scratch/backlog-steward/report-2026-10-18-175107Z.md`.
New pitfall node `pitfalls/linkage-autoclose-against-intent.md`; dated variant appended to
`pitfalls/epic-body-delivery-drift.md`. `Next Session Handoff.md` deliberately untouched (gov-hub#467).
