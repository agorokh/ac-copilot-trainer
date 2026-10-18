---
type: investigation
status: active
created: 2026-10-18
updated: 2026-10-18
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-18-175107Z-backlog-steward-reconcile-bdd6d5.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-174032Z-backlog-steward-ledger-snapshot-e01865.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/pitfalls/linkage-autoclose-against-intent.md
---

# Backlog ledger snapshot — 2026-10-18 (run `bdd6d5`)

Report-only `/backlog-steward` run over `agorokh/ac-copilot-trainer` at merged `main` `8fade2c`.
Seven open issues reconciled; four issues the 2026-10-13 ledger carried as open have since closed.
Issue-only mode (no `ops/board_manifest.yml`); no label, comment, close or board mutation.

Verdicts: `live` 3 (#627, #401, #117) · `partially-delivered` 4 (#86, #815, #529, #534) · `stale` 0 ·
`drifted` 0 · `undetermined` 0. Closed since last run: #531, #804, #854 clean; **#813 closed by
GitHub closing-reference linkage two seconds after PR #848 merged, against that PR's own "does not
close #813" statement, with its retained P7 acceptance never dispositioned** — escalated to the
operator as a proposal.

Scope evolution accepted: #86 Setup Exchange leg (proxy → native CSP, operator-ratified 2026-10-16).
Body/label drift flagged (no verdict change): #86 and #529 headers still assert `not-this-cycle`
(removed by the operator 2026-10-16); #627's latest comment attributes the Stable AC loop to the
#876 Car0-probe branch that open PR #877 measured as never reached; #401 + `Roadmap.md` name
#813/#804/#531 as current work (all closed 2026-10-15) and omit #854/#858/#862/#876.

The repository's established investigation location is `03_Investigations/`.

```json
{
 "agorokh/ac-copilot-trainer#627": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 627,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [
   {
    "path": "tools/ac_harness/freeze_forensics.py",
    "purpose": "Only if a demonstrated wedge-instrumentation gap requires code",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_init_perturber_ab.py",
    "purpose": "Only if the analyzer schema refusal set changes again",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "C2",
  "files_to_touch": [
   {
    "path": "tools/ac_harness/resilient_launch.py",
    "purpose": "In-flight PR #877: classify() stall_seconds floor (20 s), schema v5->v6",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ac_harness/init_perturber_ab.py",
    "purpose": "In-flight PR #877: refuse superseded v5 reports",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_resilient_launch.py",
    "purpose": "In-flight PR #877: post-Start pause replay STABLE under floor",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "docs/10_Development/14_Game_Point_Launcher.md",
    "purpose": "In-flight PR #877: launcher behaviour rewrite",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 3,
   "evidence": [
    {
     "kind": "merged-pr",
     "anchor": "PR #876 / resilient_launch.REPORT_SCHEMA = resilient-launch-report/v5, SUPERSEDED_REPORT_SCHEMAS=(v3,v4), DEFAULT_POST_START_CAR0_PROBES=3",
     "detail": "Launcher-side false-freeze correction only; touches no CSP wedge cause.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/876"
    },
    {
     "kind": "open-pr",
     "anchor": "PR #877 head ff82b29 (BLOCKED on review) / classify(stall_seconds=DEFAULT_STALL_SECONDS), schema v6",
     "detail": "States #876 did not fix the loop: Stable AC still 12/12 froze on build 8fade2c; the kill is classify's post-go-live stall rule (stall_samples=4), not the Car0-probe branch. Contradicts the issue's 2026-10-18 comment.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/877"
    },
    {
     "kind": "issue-body",
     "anchor": "Body header 'Current investigation state \u2014 reconciled 2026-10-13' + C2 contract comment 5446782477",
     "detail": "Standalone block; successful launches and finite-stall fixes are explicitly insufficient closure evidence. Header still names v4 as the current schema.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5446782477"
    }
   ],
   "counterevidence": [
    "No merged PR addresses the CSP accRenderingAdv.dll init wedge; both #876 and #877 are harness classification fixes."
   ],
   "remaining_acceptance": [
    "Standalone C2 causal/symptom investigation of the sustained graphics-pinned / physics-advancing wedge with explicit denominators.",
    "Land PR #877 so Stable AC stops killing drivable sessions; then re-measure a current freeze rate on v6 reports only."
   ],
   "drift_flags": [
    "comment-level: issue comment 6252056576 (2026-10-18) attributes the Stable AC loop to the Car0-probe branch fixed in #876; PR #877 measures that branch was never reached. The latest comment misleads until corrected.",
    "body-level: header item 1 cites resilient-launch-report/v4 as current; v5 shipped (#876), v6 pending (#877)."
   ],
   "recommended_action": "keep; after #877 merges, one correction comment superseding the #876 root-cause claim and a narrow header refresh (schema v6; v3/v4/v5 superseded; Stable AC v4/v5 froze counts invalid as denominators). No split; C2 contract unchanged.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#86": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 86,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [
   {
    "path": "firmware/screen/src/ui/screen_setup_exchange.cpp",
    "purpose": "Only if the on-device smoke exposes a defect",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "firmware/screen/src/ui/screen_pocket_technician.cpp",
    "purpose": "Only if the on-device smoke exposes a defect",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "firmware/screen/src/ui/screen_ac_copilot.cpp",
    "purpose": "Only if the on-device smoke exposes a defect",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_screen_simulator.py",
    "purpose": "Regression for any such defect goes through the permanent simulator first",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "do_not_merge": true,
  "scope-evolution-accepted": true,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "partially-delivered",
  "confidence": "high",
  "block_id": "86-operator-smoke",
  "files_to_touch": [
   {
    "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-86-operator-smoke-photo-<date>.md",
    "purpose": "Evidence node for the four-leg smoke + on-glass photo when the operator session happens",
    "status": "new",
    "scope": "remaining"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 4,
   "evidence": [
    {
     "kind": "merged-pr",
     "anchor": "PR #862 076361a / tools/ai_sidecar/csp_setup_exchange.py:SetupExchangeBroker + src/ac_copilot_trainer/modules/setup_exchange.lua",
     "detail": "Setup Exchange leg re-routed through the trainer's native CSP signed HTTPS session; proxy no longer required for the normal path.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/862"
    },
    {
     "kind": "merged-pr",
     "anchor": "PR #858 5d6f218 / tools/screen_simulator.py, firmware/screen/tools/simulator_gate.py, firmware/screen/simulator/",
     "detail": "Permanent native LVGL simulator gates every firmware upload; agent-side screen verification before flashing.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/858"
    },
    {
     "kind": "vault",
     "anchor": "03_Investigations/issue-86-native-se-live-readback-2026-10-17.md (PR #875)",
     "detail": "Live service readback: se.search total=149 with real authors; download installed Extrapiramidal.ini without overwrite; setup.list 7 rows; setup.load fail-closed 'must be in pits'; packaged sidecar redistributed to build_commit 8907ddf (comment 6251239660)."
    },
    {
     "kind": "label-events",
     "anchor": "unlabeled status:blocked-on-rig + not-this-cycle by agorokh 2026-10-16T06:18",
     "detail": "Operator unparked the epic; the body header still asserts both labels."
    }
   ],
   "counterevidence": [
    "All three remaining checkboxes (four-leg touch flow on device, on-glass photo vs esp32_rig.png, artifact) are unchecked.",
    "setup.load positive branch (runtime screen-tap apply) is operator-only by construction: setup_library.lua gates loadByName on ac.isCarResetAllowed(), never true for an autonomously launched car (#466: 0 OK / 152)."
   ],
   "remaining_acceptance": [
    "Operator/camera session: Launcher -> AC Copilot live hints -> Pocket Technician setup load -> Setup Exchange browse/download/install, installed setup visible and loadable in PT.",
    "On-glass photo compared against docs/10_Development/design/racing-atelier-renders/esp32_rig.png incl. glyph readability; attach artifact."
   ],
   "scope_evolution": "Setup Exchange leg: separately configured proxy (PR #365 se_proxy) -> native CSP client (PR #862). Operator-ratified in comment 6225507996 ('the touchscreen should extend the already working in-game Setup Exchange experience'). Intent (four-leg smoke + photo) unchanged.",
   "drift_flags": [
    "body-level: 'Reconciliation status \u2014 2026-10-13' asserts status:blocked-on-rig and not-this-cycle (both removed 2026-10-16) and lists SE as proxy-based; no rows for #858/#862/#875."
   ],
   "recommended_action": "rewrite (github-issue-creator, body refresh only): add #858/#862 rows, correct the label statement, record the native-SE scope evolution and the operator-only setup.load positive branch; then schedule the operator smoke/photo session (the #534 SimHub plugin check can ride along). No closure proposed.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#815": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 815,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [
   {
    "path": "tools/ai_sidecar/voice/audible_latency.py",
    "purpose": "Only if the correlation/latency thresholds need a new anchor type",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/rig_launcher/app.py",
    "purpose": "Only if Game Point needs a new arming/selection control",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "do_not_merge": false,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "partially-delivered",
  "confidence": "high",
  "block_id": "815-live-acoustic-acceptance",
  "files_to_touch": [
   {
    "path": "tools/ai_sidecar/voice/live_acceptance.py",
    "purpose": "Calibrated microphone timing / complete-phrase evidence for the remaining clause",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ac_harness/live_voice.py",
    "purpose": "Bounded live run driver for the Porsche/Spa acceptance",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ai_sidecar/microphone.py",
    "purpose": "Reuse: PR #846 tablet AudioWorklet capture with gap/duplicate/rate-change rejection and chirp bands \u2014 candidate replacement for the failed ADC sync",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_live_acceptance.py",
    "purpose": "Acceptance-record regressions",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_ac_harness_live_voice.py",
    "purpose": "Harness regressions",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "docs/10_Development/16_MOZA_Qualification.md",
    "purpose": "Record the acceptance method and outcome",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 3,
   "evidence": [
    {
     "kind": "merged-pr",
     "anchor": "PRs #834 b9dda48 / #836 54a3915 / #839 744c72f / #843 c8dbfd4 \u2014 tools/moza_ingest/, session_review/moza.py, voice/shadow_replay.py, voice/live_acceptance.py, ac_harness/rig_watchdog.py",
     "detail": "Parts B, C and D-silent delivered and body checkboxes checked; packaged binary installed.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/843"
    },
    {
     "kind": "issue-body",
     "anchor": "Two unchecked clauses + 'Live acceptance checkpoint \u2014 2026-10-14' NO_GO",
     "detail": "Microphone sync failed (90 backward ADC steps, 5 loopback discontinuities); 2.3\u20133.3 s software lead is not acoustic lead.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6173147463"
    },
    {
     "kind": "code-search",
     "anchor": "git log --since=2026-10-14T17:00 on tools/ai_sidecar/voice, tools/ac_harness/live_voice.py, tools/moza_ingest, tools/session_review/moza.py",
     "detail": "Empty: nothing merged against the remaining paths since the body refresh; the body is current."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [
    "Verify the selected voice path through advancing AC telemetry -> advisory -> dispatch -> captured complete audio with calibrated mic timing (clause unchecked).",
    "Exercise the green Porsche at Spa autonomously, inspect rendered state, fix missing harness pieces (clause unchecked)."
   ],
   "sequencing": [
    "Depends on rig reliability: run after PR #877 lands (Stable AC false-freeze kill) or use auto_drive.",
    "Instrument reuse: #531's PR #846 microphone capture (microphone.py, voice/web/mic_worklet.js) is the available fix for the measured mic-sync failure."
   ],
   "recommended_action": "keep; no body change required beyond an optional pointer to the #846 microphone path; re-run acoustic acceptance after #877.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#529": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 529,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [
   {
    "path": "tools/ai_sidecar/coaching/between_lap.py",
    "purpose": "G3 channel: #854 residue \u2014 Coach v2 between-lap focus finds 0 canonical corners on the Magione reference",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ai_sidecar/track_map.py",
    "purpose": "Same residue: canonical corner catalogue on the reference",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_between_lap_advice.py",
    "purpose": "Regression if the gate changes",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "partially-delivered",
  "confidence": "high",
  "block_id": "529-g1-lever-decision",
  "files_to_touch": [
   {
    "path": "tools/ac_harness/plant_id.py",
    "purpose": "G1 lever: cross-session plant compounding / less-conservative measured prior (root-caused 2026-08-10)",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ac_harness/auto_alien.py",
    "purpose": "Ladder retention/compounding policy",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ac_harness/alien_scientist.py",
    "purpose": "meta_priors guards if the prior changes",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_plant_id.py",
    "purpose": "Regression for any prior/compounding change",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tests/test_auto_alien.py",
    "purpose": "Regression for ladder policy",
    "status": "exists",
    "scope": "remaining"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 4,
   "evidence": [
    {
     "kind": "issue-comment",
     "anchor": "comment 6210645490 (2026-10-16) + vault issue-529-g1-mclaren-magione-2026-10-16.md (PR #857 9f14155)",
     "detail": "Fresh G1 datapoint: ks_mclaren_650_gt3 @ magione, 9 autonomous laps, best 97.378 s vs TT P10 74.784 s (+30.2%) -> G1 NOT met; mechanics generalize; 1.15 rung falsified.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6210645490"
    },
    {
     "kind": "label-events",
     "anchor": "unlabeled not-this-cycle by agorokh 2026-10-16T06:55",
     "detail": "Operator unparked; body header (2026-10-13) still says 'keep OPEN and not-this-cycle'."
    },
    {
     "kind": "merged-pr",
     "anchor": "PR #856 70ed2fe / coaching/between_lap.py, coaching_runtime.py, track_map.py",
     "detail": "Coach v2 cues bound to canonical geometry \u2014 the G3 delivery channel moved under the epic; #854 closing comment 6239025526 records between-lap focus not triggering ('track.map \u2026 0 corners').",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/856"
    },
    {
     "kind": "issue-body",
     "anchor": "Gate table G0\u2013G4 (2026-10-13)",
     "detail": "G1 not met, G1b dated, G2 met by repeatable 81.505/81.519 s, G3 operator-gated, G4 honesty intact."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [
    "G1: unseen known-archetype combo within 5% of TT top-10 in <=20 laps at stationary environment \u2014 architecturally blocked on the compounding lever.",
    "G3: human multi-session delta shrink \u2014 operator-gated; its Coach v2 channel currently finds no canonical corners on the Magione reference (#854 residue, unowned)."
   ],
   "drift_flags": [
    "body-level: header asserts not-this-cycle (removed 2026-10-16) and predates the mclaren datapoint."
   ],
   "recommended_action": "keep; narrow header correction (unparked 2026-10-16; mclaren datapoint; the G1 lever decision is the operator's). Flag the #854 Coach-v2 0-corner residue as a candidate fold into G3 \u2014 operator call, not filed here.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#534": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 534,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [
   {
    "path": "tools/ai_sidecar/server.py",
    "purpose": "Part C only after #117 ships: per-class wind curve publish",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "tools/ai_sidecar/car_class.py",
    "purpose": "Part C only: class -> wind curve mapping",
    "status": "exists",
    "scope": "remaining"
   },
   {
    "path": "firmware/arduino_fan_oled/src/main.cpp",
    "purpose": "Shared with #117 (new)",
    "status": "new",
    "scope": "remaining"
   }
  ],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "partially-delivered",
  "confidence": "high",
  "block_id": "parked-534",
  "files_to_touch": [],
  "evidence_snapshot": {
   "signals_count": 3,
   "evidence": [
    {
     "kind": "code-search",
     "anchor": "git log --since=2026-10-13 -- tools/ai_sidecar/car_class.py car_class_overrides.json tools/simhub_car_enrichment tests/test_car_class.py tests/test_simhub_car_enrichment_contract.py",
     "detail": "Empty: no code moved under Parts A/B since the 2026-10-13 body refresh."
    },
    {
     "kind": "issue-body",
     "anchor": "Remaining checkbox: operator installs/enables the SimHub plugin and verifies property-picker/NCalc",
     "detail": "Operator-owned; body current."
    },
    {
     "kind": "tree",
     "anchor": "firmware/ contains only keypad/ and screen/",
     "detail": "Part C gate (#117 fan) still holds; Part D dormant by operator decision."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [
    "Operator SimHub plugin install/enable + property-picker/NCalc verification on the rig (can ride along with the #86 rig session)."
   ],
   "recommended_action": "keep; no body change.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#401": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 401,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "parked-401",
  "files_to_touch": [
   {
    "path": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md",
    "purpose": "Mandatory durable pair of the #401 body; metadata-only refresh",
    "status": "exists",
    "scope": "metadata-only"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 4,
   "evidence": [
    {
     "kind": "gh-state",
     "anchor": "#813 CLOSED 2026-10-15T01:43, #804 CLOSED 2026-10-15T16:20, #531 CLOSED 2026-10-15T03:13, #854 CLOSED 2026-10-17T18:56",
     "detail": "The body's 'Current diagnosis (2026-10-14)' names #813/#804/#531 as current work; all three closed the next day; #854 (coaching defaults off, remote inference, lap-save stall, narration fixes) is absent."
    },
    {
     "kind": "merged-pr",
     "anchor": "PRs #858, #862, #865, #868, #871\u2013#873, #876",
     "detail": "Simulator gate, native Setup Exchange, inference default-off + approved remote backend, agent-observed HUD capture, v5 launch schema \u2014 none reflected in the body or Roadmap.md."
    },
    {
     "kind": "label-events",
     "anchor": "#86 and #529 unlabeled not-this-cycle 2026-10-16",
     "detail": "Roadmap.md next-steps item 4 says 'Preserve \u2026 not-this-cycle on #529/#531/#534/#401/#117/#86'."
    },
    {
     "kind": "vault",
     "anchor": "Roadmap.md frontmatter updated: 2026-10-14; grep for 854/862/858/876 -> no hits",
     "detail": "Durable twin is behind the tracker."
    }
   ],
   "counterevidence": [
    "Intent (living roadmap + gap map) unchanged; this is normal refresh cadence, not drift of purpose."
   ],
   "remaining_acceptance": [
    "Paired #401 body + Roadmap.md refresh reflecting closures (#813/#804/#531/#854), new software (#858/#862/#865/#868/#876), and the operator unparking of #86/#529; preserve parked dispositions on #534/#117/#401."
   ],
   "recommended_action": "rewrite (github-issue-creator, paired body + Roadmap.md, metadata-only); preserve parked programme disposition.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#117": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 117,
  "issue_state": "open",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "parked-117",
  "files_to_touch": [
   {
    "path": "firmware/arduino_fan_oled/platformio.ini",
    "purpose": "Only on operator revival (decision 2C: after #627 resolves or is parked)",
    "status": "new",
    "scope": "parked-conditional-source"
   },
   {
    "path": "firmware/arduino_fan_oled/src/main.cpp",
    "purpose": "Fan PWM + SSD1306 tyre display; reuse SerialPeer newline-JSON transport",
    "status": "new",
    "scope": "parked-conditional-source"
   },
   {
    "path": "firmware/arduino_fan_oled/README.md",
    "purpose": "Transport contract + thermal/electrical safety notes",
    "status": "new",
    "scope": "parked-conditional-source"
   },
   {
    "path": "tests/test_arduino_fan_oled_protocol.py",
    "purpose": "Simulator-free protocol fixtures",
    "status": "new",
    "scope": "parked-conditional-source"
   }
  ],
  "evidence_snapshot": {
   "signals_count": 3,
   "evidence": [
    {
     "kind": "tree",
     "anchor": "firmware/ = {keypad, screen}; firmware/arduino_fan_oled absent; tools/ai_sidecar/serial_transport.py:SerialPeer present",
     "detail": "0 of 4 acceptance criteria delivered; the recommended transport exists for reuse."
    },
    {
     "kind": "gh-state",
     "anchor": "#627 OPEN (block:C2)",
     "detail": "Revival trigger (operator decision 2C) has not fired."
    },
    {
     "kind": "issue-body",
     "anchor": "Body already notes keypad firmware (#826) alongside the screen",
     "detail": "Body current."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [
    "All four checkboxes; revival gated on #627 per operator decision 2C (comment 5077070595)."
   ],
   "recommended_action": "keep; no change.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#813": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 813,
  "issue_state": "closed",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": true,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "closed_at": "2026-10-15T01:43:36Z",
  "last_verdict": "partially-delivered",
  "confidence": "medium-high",
  "block_id": "813-linkage-autoclose",
  "files_to_touch": [],
  "evidence_snapshot": {
   "signals_count": 3,
   "evidence": [
    {
     "kind": "timeline",
     "anchor": "closed 2026-10-15T01:43:36 by agorokh, commit=none; PR #848 mergedAt 2026-10-15T01:43:34Z with closingIssuesReferences=[813]",
     "detail": "Closed two seconds after the merge via GitHub closing-reference linkage; no closing comment on #813 (last comments 2026-10-13: ESP32-only waiver 6140089525; P7 disconnected 6140184970).",
     "url": "https://github.com/agorokh/ac-copilot-trainer/pull/848"
    },
    {
     "kind": "pr-body",
     "anchor": "PR #848 body: 'this does not close #813 or change MAP geometry/corner numbering'",
     "detail": "The author explicitly disclaimed closure; the linkage closed it anyway."
    },
    {
     "kind": "vault",
     "anchor": "handoffs/2026-10-15-020500Z-post-merge-pr848-57e89c.md: '#813 remains a separate owner'; PR #849 body: '#813 retains its separate scope'",
     "detail": "Written after the close; the owner believed #813 was still open."
    }
   ],
   "counterevidence": [
    "PR #849 records autonomous P7 acceptance for #531 (two valid Porsche/Magione laps, rendered electronics/intervention, numbered phase map, corner comparison, stale clearing) that overlaps most of #813's retained P7 clauses; the practical remainder may be only the operator-driven (vs autonomous) lap and the intentional-exit stale transition ('unverified automatic menu transition' kept as an explicit limit)."
   ],
   "remaining_acceptance": [
    "Explicit disposition by the owner: accept the #531/#849 autonomous evidence as satisfying #813's retained P7 clauses (and waive the operator-driven lap), or reopen and finish. Either is a tracker mutation \u2014 proposal only."
   ],
   "recommended_action": "escalate to operator: record a closing-disposition comment on #813 (preferred) or reopen; never leave an auto-closed issue with undispositioned acceptance.",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#531": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 531,
  "issue_state": "closed",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "closed_at": "2026-10-15T03:13:00Z",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "closed-531",
  "files_to_touch": [],
  "evidence_snapshot": {
   "signals_count": 2,
   "evidence": [
    {
     "kind": "issue-comment",
     "anchor": "closing comment 6183554559",
     "detail": "Closed by owner after reopen for the full-journal perf requirement (#851 1282a9d / #852); all assigned acceptance settled; Part H SimHub fusion struck by #846 (native vitals suffice).",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/531#issuecomment-6183554559"
    },
    {
     "kind": "gh-state",
     "anchor": "#531 CLOSED completed 2026-10-15T03:13",
     "detail": "State confirmed via gh issue view."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [],
   "recommended_action": "clean done; no action. (Residue noted on #854 is an operator call, not filed.)",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#804": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 804,
  "issue_state": "closed",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "closed_at": "2026-10-15T16:20:00Z",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "closed-804",
  "files_to_touch": [],
  "evidence_snapshot": {
   "signals_count": 2,
   "evidence": [
    {
     "kind": "issue-comment",
     "anchor": "closing comment 6196856627",
     "detail": "Closed by owner with a settled six-clause table; last clause satisfied by direct inspection of the 2026-10-12 phone video (ESP32 109/107/108 -> 170/170/169 km/h); vault SAVE #853.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/804#issuecomment-6196856627"
    },
    {
     "kind": "gh-state",
     "anchor": "#804 CLOSED completed 2026-10-15T16:20",
     "detail": "State confirmed via gh issue view."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [],
   "recommended_action": "clean done; no action. (Residue noted on #854 is an operator call, not filed.)",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 },
 "agorokh/ac-copilot-trainer#854": {
  "repo": "agorokh/ac-copilot-trainer",
  "number": 854,
  "issue_state": "closed",
  "group_with": [],
  "conditional_files_to_touch": [],
  "do_not_merge": true,
  "scope-evolution-accepted": false,
  "board_move": null,
  "run_ts": "2026-10-18T17:51:07+00:00",
  "run_id": "bdd6d5",
  "closed_at": "2026-10-17T18:56:00Z",
  "last_verdict": "live",
  "confidence": "high",
  "block_id": "closed-854",
  "files_to_touch": [],
  "evidence_snapshot": {
   "signals_count": 2,
   "evidence": [
    {
     "kind": "issue-comment",
     "anchor": "closing comment 6239025526",
     "detail": "Closed by owner: defaults off (#865), remote backend (#868/#869), agent-observed acceptance (#871), efficacy fixes (#872/#873). Honest limits recorded as unowned residue: Coach v2 0-corner gate on the Magione reference; HA-voice contention untested; NVIDIA 0x133 cause unknown.",
     "url": "https://github.com/agorokh/ac-copilot-trainer/issues/854#issuecomment-6239025526"
    },
    {
     "kind": "gh-state",
     "anchor": "#854 CLOSED completed 2026-10-17T18:56",
     "detail": "State confirmed via gh issue view."
    }
   ],
   "counterevidence": [],
   "remaining_acceptance": [],
   "recommended_action": "clean done; no action. (Residue noted on #854 is an operator call, not filed.)",
   "main_sha": "8fade2cfa83c7d7e48cdded7c304b1d4a32945e1"
  }
 }
}
```
