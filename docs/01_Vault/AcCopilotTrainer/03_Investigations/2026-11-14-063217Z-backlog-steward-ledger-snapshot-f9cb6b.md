---
type: investigation
status: active
created: 2026-11-14
updated: 2026-11-14
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-063217Z-backlog-steward-reconcile-f9cb6b.md
  - AcCopilotTrainer/03_Investigations/2026-11-10-185600Z-backlog-steward-ledger-snapshot-c4a91e.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
---

# Backlog ledger snapshot — 2026-11-14 (run `f9cb6b`, settled after the #401 and #956 refreshes)

`/backlog-steward` run `f9cb6b` over `agorokh/ac-copilot-trainer` at merged `main` `3448597c`,
diffed against snapshot `c4a91e` (`145c07a`). The run itself was read-only. Afterwards, on
operator instruction, the #401 body and `Roadmap.md` were refreshed as a pair and the #956
body was refreshed; no label, comment or close was made on any issue. No Council was convened; verdicts rest on the artifacts cited per entry. No GitHub
Project board is declared for workspace `ac_copilot` (fleet `board_manifest.yml` lists it as
intentionally undeclared), so board reconciliation was skipped.

| Issue | State | Verdict | Change vs `c4a91e` | Proposed move |
|---|---|---|---|---|
| #956 | open | `partially-delivered` | new | escalate: operator decision on spent rig cap (body refreshed 2026-11-14) |
| #401 | open | `live` (pair was stale) | flag added, then settled | pair refreshed 2026-11-14 on operator instruction |
| #529 | open | `partially-delivered` | unchanged, not re-flagged | keep |
| #957 | open | `live` (Hold) | new | keep on Hold |
| #117 | open | `live` (parked) | unchanged, not re-flagged | keep parked |
| #86 | closed 2026-11-11 | clean done | was `partially-delivered` | none |
| #955 | closed 2026-11-12 | clean done | new | none |

## Recurring drift pattern

A new shape of [epic-body-delivery-drift](../pitfalls/epic-body-delivery-drift.md): the #401
body and `Roadmap.md` agree with each other, so a pair-consistency check passes, yet both are
stale against the tracker. Issues filed by `/roadmap-expansion` (#955, #956, #957) and
delivered by `/autonomous-deliver` never passed through a #401 reconciliation, so the pair
still counts three open issues while five are open. Checking the pair against itself is not
enough; check it against `gh issue list`.

Second occurrence in the same window: #956's body budget line (`leaves 11260.227089s`) was
left behind by eight later comments that track the real remainder (`2050.9643220 s`).

## Delivery blocks

- `sequence-only` #956 ↔ #529 on `tools/ac_harness/auto_drive.py` and `racing_driver.py`
  (plus the rig lock). Not a merge candidate: different goals, both operator-gated.
- `keep-separate`: #957 (`tools/coaching_lake`, `tools/session_review`), #117
  (`firmware/arduino_fan_oled`), #401 (metadata only).

## Ledger payload

```json
{
  "agorokh/ac-copilot-trainer#956": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 956,
    "issue_state": "open",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [529],
    "block_id": "956-acceptance-cap-stop",
    "block_shape": "sequence-only",
    "do_not_merge": true,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-956-acceptance-verdict-<date>.md",
        "purpose": "Published overall verdict node (issue rule: publish actual verdict before any closure)",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/ac_harness/racing_driver.py",
        "purpose": "Only if the operator funds another registration and the post-#981 driver still fails natively",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/auto_drive.py",
        "purpose": "Same condition; shared with #529 via auto_alien delegation (sequencing overlap)",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_ac_harness_racing_driver.py",
        "purpose": "Regression coverage for any further driving repair",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_ac_harness_auto_drive.py",
        "purpose": "Regression coverage for any further driving repair",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "evidence_snapshot": {
      "signals_count": 4,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PRs #964 8e153bc, #966 e889e70, #968 4d8eeed / tools/ai_sidecar/setup_prescription.py:build_prescription, PrescriptionJournal; tools/ai_sidecar/server.py 'Pressure experiment inactive' + AC_COPILOT_PRESSURE_EXPERIMENT; firmware/screen/src/ui/screen_pocket_technician.cpp; firmware/screen/simulator/scenarios.cpp",
          "detail": "Prescription-card prototype shipped default-off with simulator-gated screen; Screen acceptance checkbox is the only one ticked.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/964"
        },
        {
          "kind": "merged-pr",
          "anchor": "PRs #971 44b5833, #973 6e1af80, #974 71131b8, #975 cd500a4, #978 a3e5d07, #980 35004de, #981 0241c92 / tools/ai_sidecar/pressure_bench.py, tools/pressure_bench_oracle.py, tools/pressure_bench_actor.py, tools/ac_harness/pit_return.py, tools/ac_harness/auto_drive.py:slip_compound_index, tools/ac_harness/racing_driver.py:RacingDriver.step",
          "detail": "Isolated AI bench acceptance, natural pit return and opt-in wheel-speed slip feedback shipped; none of the ten PRs carries a closing reference, so the issue stays open by intent.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/981"
        },
        {
          "kind": "issue-comment",
          "anchor": "comment 6872074899 (2026-11-14T04:59:41Z)",
          "detail": "Native acceptance INCONCLUSIVE, 0/12 scored. Rig use 12349.0356780 s of 14400; 2050.9643220 s remain, while one genuine unit plus reserve needs 2610.227089 s, so no further trial fits. Post-#981 driver not rerun natively.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/956#issuecomment-6872074899"
        },
        {
          "kind": "vault",
          "anchor": "00_System/handoffs/2026-11-14-050035Z-post-merge-pr981-slip-transition.md",
          "detail": "Handoff records cap-based stop, installed source 0241c92, normal experiment disabled, restoration verified."
        }
      ],
      "counterevidence": [
        "Acceptance A, B, C, D and E/overall-verdict checkboxes remain unchecked; hardest assumption (correctly directed cold-pressure prescriptions on genuine cases) has never been scored."
      ],
      "remaining_acceptance": [
        "A: genuine end-to-end excluded pilot (short pilot passed once under an earlier registration; cannot substitute).",
        "B/C: 12 scored cases, 0 so far.",
        "D: native safety trials not run.",
        "E/overall: publish actual verdict before closure."
      ],
      "scope_evolution": "Human 30% timing criterion replaced by autonomous 90 s-per-case protocol (operator adopted PR #970, body section 'Adopted autonomous acceptance'); owner authorized the driving repair in comment 6869681438.",
      "drift_flags": [
        "budget-creep: explore card budget went 1.5 engineering days + 60 rig minutes -> 2 more days + 240 rig minutes; both exhausted without a scored case.",
        "seam-migration: last five PRs changed the shared autonomous driver (tools/ac_harness), the surface #529 G1 runs on."
      ],
      "resolved_flags": [
        "body-stale (found by this run): the body said 240 min 'leaves 11260.227089s' and its checkpoint and file list predated the bench and harness work. Body refreshed 2026-11-14 on operator instruction with a current-state section; acceptance criteria and checkboxes unchanged (1 checked, 5 unchecked)."
      ],
      "recommended_action": "escalate: operator decides between (a) publishing INCONCLUSIVE as the explore verdict and closing or parking, (b) a new bounded rig cap, (c) human-driven stints for the 12 cases. Do not re-attempt under the spent registration.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#957": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 957,
    "issue_state": "open",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "hold-957",
    "block_shape": "keep-separate",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [
      {"path": "tools/coaching_lake/progression_audit.py", "purpose": "Offline common-support and calibration audit", "status": "new", "scope": "held-until-promoted"},
      {"path": "tools/coaching_lake/build_analytics.py", "purpose": "Expose strata needed by the audit", "status": "exists", "scope": "held-until-promoted"},
      {"path": "tools/session_review/report.py", "purpose": "cannot_identify abstention reasons and support counts", "status": "exists", "scope": "held-until-promoted"},
      {"path": "tests/test_progression_audit.py", "purpose": "Audit unit tests", "status": "new", "scope": "held-until-promoted"}
    ],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "tree",
          "anchor": "tools/coaching_lake/progression_audit.py and tests/test_progression_audit.py absent; no merged PR references #957",
          "detail": "0 of 3 acceptance criteria delivered; nothing built ahead of the Hold gate."
        },
        {
          "kind": "code-search",
          "anchor": "tools/lap_qualification.py:USES contains 'human_progression'; tools/ai_sidecar/traffic_eligibility.py:CLEAN_USES contains 'human_progression'; tools/coaching_lake/build_analytics.py lap_features / stint_deg",
          "detail": "Premises hold. The traffic-clean clause became enforceable when #955 shipped (PRs #960, #962)."
        },
        {
          "kind": "gh-state",
          "anchor": "#957 body HOLD GATE; #401 has no promotion comment after 6801783432",
          "detail": "Operator promotion not given. Gate (1), six or more human-qualified sessions on one combo, is not verifiable from this host: the corpus lives on the rig."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": ["All three criteria, behind the Hold gate."],
      "drift_flags": [],
      "recommended_action": "keep on Hold. Cheapest next fact is a read-only count of human-qualified traffic-clean sessions per combo on the rig.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#529": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 529,
    "issue_state": "open",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [956],
    "block_id": "529-g1-policy-and-rex",
    "block_shape": "sequence-only",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [
      {"path": "tools/ac_harness/ggv_profile.py", "purpose": "REX-20261024-01 (G1): row-level thermal probe eligibility in ggv_from_lap_archives / merge_selfplay_model", "status": "exists", "scope": "remaining"},
      {"path": "tools/ac_harness/auto_alien.py", "purpose": "REX-20261024-01 (G1): per-corner capability stepping", "status": "exists", "scope": "remaining"},
      {"path": "tests/test_auto_alien.py", "purpose": "Regression coverage for per-corner stepping", "status": "exists", "scope": "remaining"}
    ],
    "conditional_files_to_touch": [
      {"path": "tools/lap_qualification.py", "purpose": "Only on an operator ruling about authority='ai' for use='plant_fit'", "status": "exists", "scope": "remaining"},
      {"path": "tools/ai_sidecar/coachable_frontier.py", "purpose": "REX-20261024-03 (G3) drill sequencer", "status": "exists", "scope": "remaining"},
      {"path": "tools/ai_sidecar/driver_progression.py", "purpose": "REX-20261024-03 (G3) corner mastery state", "status": "exists", "scope": "remaining"},
      {"path": "tools/ai_sidecar/coaching_ledger.py", "purpose": "REX-20261024-03 (G3) drill outcome ledger", "status": "exists", "scope": "remaining"},
      {"path": "tools/ai_sidecar/coaching/between_lap.py", "purpose": "REX-20261024-03 (G3) between-lap focus", "status": "exists", "scope": "remaining"}
    ],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "git-log",
          "anchor": "git log 145c07a..3448597c -- tools/ac_harness/ggv_profile.py tools/ac_harness/auto_alien.py tools/ai_sidecar/coachable_frontier.py tools/ai_sidecar/driver_progression.py",
          "detail": "Zero commits on the REX-20261024-01 and -03 surfaces since ledger c4a91e; nothing new delivered toward G1 or G3."
        },
        {
          "kind": "code-search",
          "anchor": "tools/lap_qualification.py:qualify_archive 'if authority != \"human\" and use != \"analysis\"' -> control_authority_not_human",
          "detail": "The plant_fit policy guard the body names is still present. The only change to the file since the ledger is #955's traffic gating (b3f4e82a, +13 lines), which also adds plant_fit to CLEAN_USES."
        },
        {
          "kind": "gh-state",
          "anchor": "#529 body dated 2026-11-10; #401 comment 6789173790",
          "detail": "G1 and G3 unmet; the three operator decisions (ai plant_fit eligibility, REX-20261024-01 go, human session selection for REX-20261024-03) are still pending."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [
        "Operator ruling on authority='ai' archives for use='plant_fit'.",
        "G1 cold-start generalization (REX-20261024-01) and G3 human multi-session validation (REX-20261024-03)."
      ],
      "drift_flags": [
        "shared-driver-moved: #956 PRs #975/#978/#980/#981 changed tools/ac_harness/auto_drive.py and racing_driver.py, which auto_alien delegates to. Slip feedback is default-off, so G1 behavior is unchanged unless opted in; its effect on G1 pace is untested."
      ],
      "recommended_action": "keep; unchanged since c4a91e and not re-flagged. Add a one-line body note about the new opt-in slip feedback and the plant_fit traffic gate when the body is next touched.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#401": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 401,
    "issue_state": "open",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "umbrella-401",
    "block_shape": "keep-separate",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [
      {"path": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md", "purpose": "Paired refresh with the #401 body: add #955 (closed), #956 (open, INCONCLUSIVE cap stop), #957 (Hold) and the REX-20261111 slate", "status": "exists", "scope": "metadata-only"}
    ],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "gh-state",
          "anchor": "#401 body: 'Open backlog is now 3 issues (#529, #401, and parked #117)', shipped-state refresh 2026-11-11 through 9f8a3b0",
          "detail": "Tracker now has 5 open issues. The body contains zero mentions of #955, #956, #957 or REX-20261111."
        },
        {
          "kind": "git-log",
          "anchor": "git log -- docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md -> last commit 9f8a3b0a (PR #953)",
          "detail": "Roadmap.md also has zero mentions of #955/#956/#957. The pair agrees with itself and is stale against the tracker. PRs #954 and #958 added a handoff and the annex only."
        },
        {
          "kind": "issue-comment",
          "anchor": "comment 6801783432 + 03_Investigations/roadmap-expansion-2026-11-11.md",
          "detail": "The 2026-11-11 slate exists only as a comment and an annex; since then #955 shipped traffic-aware eligibility and #956 gave the setup-intelligence endpoints their first UI caller, both capability flips the pair invariant says must be mirrored."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": ["Standing umbrella; keep body and Roadmap.md synchronized on every owner or capability change."],
      "drift_flags": [],
      "resolved_flags": ["pair-stale (found by this run): #401 body and Roadmap.md both omitted #955, #956, #957 and counted 3 open issues instead of 5. Refreshed as a pair on 2026-11-14 on operator instruction (issue body edited the same day; Roadmap.md in the follow-up vault PR after #983)."],
      "recommended_action": "keep; pair refreshed 2026-11-14. Next refresh is owed when #956 or #957 changes state.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#117": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 117,
    "issue_state": "open",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "parked-117",
    "block_shape": "keep-separate",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [
      {"path": "firmware/arduino_fan_oled/platformio.ini", "purpose": "Only on explicit operator unpark", "status": "new", "scope": "parked-conditional-source"},
      {"path": "firmware/arduino_fan_oled/src/main.cpp", "purpose": "Fan PWM + SSD1306 tyre display reusing SerialPeer", "status": "new", "scope": "parked-conditional-source"},
      {"path": "firmware/arduino_fan_oled/README.md", "purpose": "Transport contract + electrical safety notes", "status": "new", "scope": "parked-conditional-source"},
      {"path": "tests/test_arduino_fan_oled_protocol.py", "purpose": "Protocol unit tests", "status": "new", "scope": "parked-conditional-source"}
    ],
    "conditional_files_to_touch": [
      {"path": "tools/ai_sidecar/car_class.py", "purpose": "Former #534 Part C per-class wind curve if unparked", "status": "exists", "scope": "parked-conditional-source"}
    ],
    "evidence_snapshot": {
      "signals_count": 2,
      "evidence": [
        {
          "kind": "tree",
          "anchor": "firmware/ = {keypad, screen}; tools/ai_sidecar/serial_transport.py:SerialPeer present",
          "detail": "0 of 4 acceptance criteria delivered; unchanged since c4a91e."
        },
        {
          "kind": "gh-state",
          "anchor": "labels enhancement,not-this-cycle",
          "detail": "Operator park label intact."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": ["All four hardware/firmware checkboxes, behind operator-owned not-this-cycle."],
      "drift_flags": [],
      "recommended_action": "keep parked; unchanged and not re-flagged.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#86": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 86,
    "issue_state": "closed",
    "closed_at": "2026-11-11T02:58:56Z",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-86",
    "block_shape": "keep-separate",
    "do_not_merge": false,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PRs #949 185414d, #951 3c746a3, #953 9f8a3b0 / firmware/screen/src/ui/ascii_fold.cpp, screen_pocket_technician.cpp",
          "detail": "PR #953 carries the closing reference and its title states the intent to close the epic, so this is not a linkage auto-close against intent.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/953"
        },
        {
          "kind": "gh-state",
          "anchor": "#86 body checkboxes 4 checked / 0 unchecked",
          "detail": "The three hardware checkboxes open at c4a91e are now ticked."
        },
        {
          "kind": "issue-comment",
          "anchor": "closing comment 2026-11-11T02:58:54Z",
          "detail": "Four-leg physical COM6 pit acceptance with PNG receipts; the five render differences vs esp32_rig.png were accepted as shipped, which settles the c4a91e remainder."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "clean done; no action.",
      "main_sha": "3448597c"
    }
  },
  "agorokh/ac-copilot-trainer#955": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 955,
    "issue_state": "closed",
    "closed_at": "2026-11-12T06:50:38Z",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-955",
    "block_shape": "keep-separate",
    "do_not_merge": false,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-14T06:32:17+00:00",
    "run_id": "f9cb6b",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PRs #960 b3f4e82, #962 5d7af40 / tools/ai_sidecar/traffic_eligibility.py:CLEAN_USES, archive_traffic_eligibility; tools/lap_qualification.py import",
          "detail": "Traffic-aware eligibility and quarantine are on main and wired into qualification.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/962"
        },
        {
          "kind": "gh-state",
          "anchor": "#955 body checkboxes 4 checked / 0 unchecked; closed COMPLETED by owner, no closing PR reference",
          "detail": "Manual close after the acceptance table was posted."
        },
        {
          "kind": "issue-comment",
          "anchor": "closing comment 2026-11-12T06:50:37Z",
          "detail": "All four explore clauses pass; closer recorded the limits (one known false mute A035; 20-car replay is a native derivation; primary labels unblinded)."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "clean done as an explore experiment; not yet mirrored in #401 / Roadmap.md (see #401).",
      "main_sha": "3448597c"
    }
  }
}
```
