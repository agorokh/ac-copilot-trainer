---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-022537Z-backlog-applied-moza-815-ce1e22.md
---

# Applied backlog ledger

Issue-only reconciliation; no board resolved or changed. `live` means a valid carrier, not permission to resume parked work. Original drift evidence remains under `prior_audit`; #401/#627 bodies now reflect that evidence. #117 was not edited. #813 received a status prefix after its PR merged; its original specification and checkbox states remain. No issues were closed or dispositions changed.

```json
{
  "agorokh/ac-copilot-trainer#813": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 813,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "existing-813-carrier",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "firmware/screen/include/ui/coaching_semantics.h",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tests/test_rig_coaching_semantics.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tools/ai_sidecar/dash/web/tablet_dash.html",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tools/ai_sidecar/server.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tools/ai_sidecar/track_map.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "src/ac_copilot_trainer/modules/coaching_publisher.lua",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "src/ac_copilot_trainer/modules/setup_library.lua",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "src/ac_copilot_trainer/modules/telemetry_publisher.lua",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "firmware/screen/src/ui/screen_ac_copilot.cpp",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "firmware/screen/src/ui/screen_pocket_technician.cpp",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tests/test_tablet_dash_endpoint.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tests/test_track_map.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "tests/test_setup_library_summary.py",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      },
      {
        "path": "docs/10_Development/design/tablet-dashboard/DESIGN_SPEC.md",
        "purpose": "Shipped by PR814; retained physical acceptance requires verification, not reimplementation",
        "status": "exists",
        "scope": "delivered-reference"
      }
    ],
    "conditional_files_to_touch": [],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 3,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged b513d05; shared display/electronics/MAP software present on fetched main."
        },
        {
          "kind": "owner-acceptance-record",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6134453203",
          "detail": "Dated reported launcher/screen distribution, explicitly retaining operator-driven physical valid-lap and intentional-exit acceptance; not a fresh device inspection by this task."
        },
        {
          "kind": "exact-readback",
          "anchor": ".scratch/moza-qualification/backlog-updates/post814/applied/issue-813.receipt.json",
          "detail": "Status prefix applied; original body and acceptance checkbox states retained; all issue metadata preserved."
        }
      ],
      "counterevidence": [
        "Candidate software/replay/native-render claims are extensive but no merge, firmware flash or promoted EXE deployment is evidenced.",
        "An on-glass operator lap is not interchangeable with the staged EXE self-test or browser replay."
      ],
      "remaining_acceptance": [
        "Recover eligible independent review and complete existing carrier's exact-head gate; no bypass/no parallel implementation.",
        "Merge and verify actual sidecar/tablet/firmware identities.",
        "Operator-driven valid Porsche/Magione lap with supported electronics changes, agreement of commands/targets, unwrapped distances, numbered/segmented MAP, valid same-combo comparisons, and intentional exit/stale transitions."
      ],
      "recommended_action": "Continue existing PR #814 when its reviewer capacity gate permits, then real rig acceptance.",
      "issue_source_sha256": "509c2f930991388ba0ee4cf914ba166658800f7d55960e36b912cdff2e9ba3c1", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    },
    "run_ts": "2026-10-13T02:31:39.546055+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "live",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 3,
        "evidence": [
          {
            "kind": "current-code",
            "anchor": "firmware/screen/src/ui/screen_ac_copilot.cpp:command_for_snapshot",
            "detail": "Main maps generic line to LIFT and has narrow distance label; coaching_publisher lacks separate action/approach identity."
          },
          {
            "kind": "current-code",
            "anchor": "tools/ai_sidecar/dash/web/tablet_dash.html:renderMap / mapSvg / min target strings",
            "detail": "Main still has fixed 620x380 viewbox and min labels for target_speed_kmh."
          },
          {
            "kind": "open-pr",
            "anchor": "PR #814 @ c2c7a121920a757e6437817071c84feada29890e",
            "detail": "At 2026-10-13T01:48:34Z OPEN/BLOCKED, not merged; 35 files. New-head build IN_PROGRESS, Canonical docs/conformance successful. Earlier reviewed diff at 0a2559f implemented the stated software; new-head independent review not established.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/814"
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comment 6134453203",
            "detail": "At earlier 0a2559f: waiter 124, evaluator 4 and absent admitted independent seat; current-head gates must be refreshed. Physical E:2 remains unverified.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6134453203"
          }
        ],
        "counterevidence": [
          "Candidate software/replay/native-render claims are extensive but no merge, firmware flash or promoted EXE deployment is evidenced.",
          "An on-glass operator lap is not interchangeable with the staged EXE self-test or browser replay."
        ],
        "remaining_acceptance": [
          "Recover eligible independent review and complete existing carrier's exact-head gate; no bypass/no parallel implementation.",
          "Merge and verify actual sidecar/tablet/firmware identities.",
          "Operator-driven valid Porsche/Magione lap with supported electronics changes, agreement of commands/targets, unwrapped distances, numbered/segmented MAP, valid same-combo comparisons, and intentional exit/stale transitions."
        ],
        "recommended_action": "Continue existing PR #814 when its reviewer capacity gate permits, then real rig acceptance.",
        "issue_source_sha256": "509c2f930991388ba0ee4cf914ba166658800f7d55960e36b912cdff2e9ba3c1", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "remaining_acceptance": "Owner-reported distribution checkpoint retained; actual operator-driven valid lap, physical displays/electronics, MAP comparisons and intentional-exit states remain.",
    "post814_receipt": {
      "issue": 813,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/813",
      "planned_at": "2026-10-13T02:30:31.207019+00:00",
      "before_sha256": "938d1ddedd7840d8af578f5ecdbca6bc7659cda7fdc615a1d1f3edf8b9cae9ab", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "b1a652480ba2bbada03ec0d0ccdaf5a3dc1561296594a511aad797b5315a16a6", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-813.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-813.md",
      "inverse_command": "gh issue edit 813 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-813.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:32.861595+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "b1a652480ba2bbada03ec0d0ccdaf5a3dc1561296594a511aad797b5315a16a6", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#804": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 804,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "804-acceptance",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-13-804-acceptance-followup.md",
        "purpose": "New dated evidence receipt; exact name proposed",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/rig_launcher/supervisor.py",
        "purpose": "Only if remaining Stable AC symptom reproduces and is assigned",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/resilient_launch.py",
        "purpose": "Only after diagnosing automatic session-start failure",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_resilient_launch.py",
        "purpose": "Only for a demonstrated launcher defect",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 4,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/804",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-804.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        }
      ]
    },
    "run_ts": "2026-10-13T02:31:39.540847+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "partially-delivered",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 3,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #805 / LauncherView.fit_window",
            "detail": "Content sizing shared with preview; real Tk layout regressions cover all controls and minimum geometry.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/805"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #809 / setup_library.bestForSetups + lap_metadata.read",
            "detail": "One bounded metadata scan per request replaces repeated full JSON telemetry decode; tests/test_setup_library_best.py preserves matching semantics.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/809"
          },
          {
            "kind": "vault",
            "anchor": "handoffs/2026-10-12-174325Z-post-merge-pr809-dc1d25.md",
            "detail": "Deployed 6d2e1ee identity, all archives restored, advancing packets, actual P7 screenshots; Stable AC automatic session.start still not_drivable/unacknowledged."
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comment 6132771281",
            "detail": "Phone video physically proves moving ESP32 and tablet ~170/170/169 km/h; explicitly retains #804 ownership and routes display defects to #813.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/804#issuecomment-6132771281"
          }
        ],
        "counterevidence": [
          "The issue's only remaining checkbox is physical consumption/rendering; later video now supports that narrow clause but owner explicitly did not change checkbox/closure.",
          "Manual drive is not proof of Stable AC automatic start. Static screenshots and screen_peers=1 alone never sufficed."
        ],
        "remaining_acceptance": [
          "Reconcile the later physical motion video against the exact retained checkbox and current deployed identities; retain any launch/verification residue.",
          "Record an explicit acceptance disposition; coordinate #813 defect fixes without rebuilding launcher sizing or setup-list scan."
        ],
        "recommended_action": "Keep separate as acceptance owner; amend evidence only through its owner. No immediate close proposed.",
        "issue_source_sha256": "3a6d8c3f67245ef78a0488478ba4e8c44b261047d1822529ab176f0fe99e1b8f", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 804 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-804.before.md\""
    },
    "post814_receipt": {
      "issue": 804,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/804",
      "planned_at": "2026-10-13T02:30:27.586448+00:00",
      "before_sha256": "55ee3de40c41fb838e83ac52f64e20d40511fde5ac0d941ead4d773df6dc126e", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "f4605cda54e2b892f9006ea84e5c40acbab43ff84409fc6d343506ed4ebce830", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-804.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-804.md",
      "inverse_command": "gh issue edit 804 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-804.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:29.478897+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "f4605cda54e2b892f9006ea84e5c40acbab43ff84409fc6d343506ed4ebce830", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#627": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 627,
    "last_verdict": "live",
    "confidence": "high",
    "block_id": "C2",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-627-current-evidence-2026-10-13.md",
        "purpose": "New reconciled evidence/method node",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "docs/10_Development/18_Autonomous_Harness.md",
        "purpose": "Keep current v4 instrument and failure-class runbook coherent if brief update requires it",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/ac_harness/freeze_forensics.py",
        "purpose": "Only if a demonstrated instrumentation gap requires code",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/resilient_launch.py",
        "purpose": "Only if current v4 evidence reveals misclassification",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/init_perturber_ab.py",
        "purpose": "Experiment method/receipt changes if warranted",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_resilient_launch.py",
        "purpose": "Classifier regression if actual defect",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 4,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/627",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-627.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        }
      ]
    },
    "run_ts": "2026-10-13T02:31:39.535235+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "drifted",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 4,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #726 / LaunchVerdict.NOT_DRIVABLE + FREEZE_VERDICTS + REPORT_SCHEMA v4",
            "detail": "Rendering pre-drive menu is excluded from freeze bucket; v3 experiment reports rejected by init_perturber_ab loader; tests/test_resilient_launch.py exercise delayed real wedge and advancing menu.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/726"
          },
          {
            "kind": "vault",
            "anchor": "issue-627-strtod-unbounded-loop-2026-07-29.md",
            "detail": "Decimal-to-double parser, not float printer/hash loop; potential unbounded limb normalization remains distinct from finite workload."
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #730 / refreshActiveReference + SC-04",
            "detail": "Disabled imported-reference path no longer eagerly scans full journal; observed 21.945 s -> 3.017 s log gap for post-lap workload.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/730"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #809 / setup_library.bestForSetups",
            "detail": "Separate setup-list full archive parse stall repaired and normal corpus restored.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/809"
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comment 5446782477",
            "detail": "Standalone block:C2; whole-issue boundary, no splitting review residue into new issues.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5446782477"
          }
        ],
        "counterevidence": [
          "Three historical pinned-graphics/advancing-physics hot-thread captures remain real wedge evidence; menu misclassification does not erase them.",
          "A successful manual drive or C1 batch is not a condition-matched failure-rate/root-cause closure.",
          "No current controlled v4 boot-arm experiment, upstream resolution or accepted root-cause closure was established by this audit."
        ],
        "remaining_acceptance": [
          "Rewrite current brief around v4 instrument, parser direction, proven finite scan stalls and remaining terminal-init-wedge question.",
          "Use current packet advancement and held-process evidence for future reliability measurements; do not reuse v3 rates.",
          "Keep C2 and rig ownership/operator gates; no rig action performed here."
        ],
        "recommended_action": "Refresh master evidence narrative before any C2 experiment. Keep open and independent.",
        "issue_source_sha256": "40c9c91b9cdc76590b62609d2d5712705b0a802f037ccf0f1bf9decd0a7d908b", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 627 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-627.before.md\""
    },
    "post814_receipt": {
      "issue": 627,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/627",
      "planned_at": "2026-10-13T02:30:23.938292+00:00",
      "before_sha256": "1ff277bf4d06b9132b6a29a79476c19332b5c5a4711ee1cf77236191a58f15a2", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "86b19560c75d67f2bbdee43e4782f363ed57418a59f01bfcfef44c8f9e2edc7f", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-627.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-627.md",
      "inverse_command": "gh issue edit 627 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-627.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:25.501133+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "86b19560c75d67f2bbdee43e4782f363ed57418a59f01bfcfef44c8f9e2edc7f", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#534": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 534,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "parked-534",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "tools/simhub_car_enrichment/README.md",
        "purpose": "Record any future verified installation procedure/acceptance",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/2026-10-13-534-acceptance.md",
        "purpose": "New dated live property/decision receipt when authorized",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "firmware/arduino_fan_oled/src/main.cpp",
        "purpose": "Only Part C after #117 hardware/transport contract; illustrative new location",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/car_class.py",
        "purpose": "Only if a real class-resolution delta is identified",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_car_class.py",
        "purpose": "Only for resolver delta",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/simhub_car_enrichment/AcCopilot.CarEnrichment/AcCopilotDataPlugin.cs",
        "purpose": "Only for proven adapter gap",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_simhub_car_enrichment_contract.py",
        "purpose": "Only for adapter behavior delta",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 3,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/534",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-534.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        }
      ]
    },
    "run_ts": "2026-10-13T02:25:37.573375+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "partially-delivered",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 3,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #689 / car_class.classify_car + resolve_installed_car + CarClassResolution.wire_fields",
            "detail": "Override-first resolver, safe fallback/provenance, enriched session stream and tablet consumer; installed-fleet 217/217 audit is dated PR evidence.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/689"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #692 / AcCopilotDataPlugin lifecycle/heartbeat generation handling",
            "detail": "Bridge rejects stale epochs/old workers and requests Lua session replay; source and tests/test_simhub_car_enrichment_contract.py present.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/692"
          },
          {
            "kind": "current-code",
            "anchor": "tests/test_car_class.py:test_override_wins_with_differential_proof; test_unknown_metadata_uses_default_provenance",
            "detail": "Actual JSON registry and resolver tests remain on main; do not implement original YAML literally."
          },
          {
            "kind": "vault",
            "anchor": "car-class-enrichment-authority-2026-07-25.md; issue-534-car-enrichment-simhub-audio-2026-07-25.md",
            "detail": "One identity authority; plugin install/enable/operator profiles not auto-mutated; Part E options/default already analyzed."
          }
        ],
        "counterevidence": [
          "Compiled DLL and wire/reflection testing do not prove installed/enabled SimHub property-picker/NCalc acceptance.",
          "Part C fan prerequisite #117 is still unbuilt.",
          "Part D remains dormant: existing TT25 hardware does not authorize reviving dropped Arduino pedal scope.",
          "Part E preserve AC/FMOD recommendation exists; no class-gated physical experiment claimed."
        ],
        "remaining_acceptance": [
          "Reconcile Part A as done and Part B as software-delivered, live installation/property acceptance unverified.",
          "Retain C -> #117; D explicit operator decision; E preserve existing AC/FMOD unless a bounded seat-only experiment is requested."
        ],
        "recommended_action": "Keep not-this-cycle. Narrow body to deployment/hardware/operator residue; no new resolver/bridge.",
        "issue_source_sha256": "3595c84be5b7c170535892dfe4765facbb5fc0d071e5faea3f52f24fb8140503", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 534 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-534.before.md\""
    }
  },
  "agorokh/ac-copilot-trainer#531": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 531,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "parked-531",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "tools/ai_sidecar/voice/web/tablet_voice.html",
        "purpose": "Native playback/mic integration",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/voice/audible_latency.py",
        "purpose": "Real target latency measurement/capture",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/server.py",
        "purpose": "Mic or optional vitals transport contract",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/external_protocol.py",
        "purpose": "Bounded optional upstream frames",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/registers.py",
        "purpose": "Only if measured latency permits route change",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/dash/web/tablet_dash.html",
        "purpose": "Remaining approved mic/vitals/verification adjustments",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_voice_tablet_endpoint.py",
        "purpose": "Playback/mic behavior",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_audible_latency.py",
        "purpose": "Latency interpretation",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_audio_routing.py",
        "purpose": "Critical route gate",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_tablet_dash_endpoint.py",
        "purpose": "Consumer contract",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "docs/10_Development/design/tablet-dashboard/DESIGN_SPEC.md",
        "purpose": "Resolve explicit motion/spec and accepted optional changes",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 4,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/531",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-531.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        }
      ]
    },
    "run_ts": "2026-10-13T02:31:39.529440+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "partially-delivered",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 3,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #618 / build_track_map + tablet_dash COACH/MAP/STINT + dev_feeder",
            "detail": "Map geometry, spline dot, queue, session review and stint fields shipped.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/618"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #615 / RaceStatusTracker + ShiftObserver + audio_routing_for_register",
            "detail": "Fuel/predicted/shift/audio policy shipped; PC critical route remains authoritative.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/615"
          },
          {
            "kind": "current-code",
            "anchor": "voice/web/tablet_voice.html:armAudio / playDispatch",
            "detail": "Existing WebAudio endpoint with warm HAL and echo timestamps; rg tools/src finds no fully.playSound, getUserMedia, AudioWorklet or SimHubPropertyServer implementation."
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comments 5076669149 and 6132771599",
            "detail": "Audio latency, optional H build-or-strike, mic, Part F target proof, glass intervention, >=10min soak retained; not-this-cycle explicitly preserved.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/531#issuecomment-6132771599"
          }
        ],
        "counterevidence": [
          "Car-swap electronics proof already passed live; do not reopen it as unbuilt.",
          "A 149-second video cannot prove >=10-minute <=15Hz A133 perf-soak, dispatch-to-audible latency, all modal pages or mic upstream.",
          "#534's class property plugin is not the optional SimHub-to-sidecar computed-vitals bridge: directions/contracts differ."
        ],
        "remaining_acceptance": [
          "G: Fully native audio plus measured dispatch-to-audible wired P7 <450ms before critical routing changes.",
          "H: explicit build-or-strike optional SimHub vitals fusion decision.",
          "I: mic upstream/proof-capture approach; #381 is closed so refresh obsolete pointer without assuming I delivered.",
          "Part F full live page/lap-count/stint verification, on-glass intervention capture, >=10-minute perf-soak, explicit canonical motion/spec decision."
        ],
        "recommended_action": "Keep parked and separate from #813; refresh remaining checklist after new display acceptance.",
        "issue_source_sha256": "17a268fc3eeecccd9e610ab80d927186cd4dfdadf7830cd716206c29eb34d317", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 531 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-531.before.md\""
    },
    "post814_receipt": {
      "issue": 531,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/531",
      "planned_at": "2026-10-13T02:30:19.840693+00:00",
      "before_sha256": "9b04b2ae1e9661fa7b89e82612c477d0904d2ad2a48b6ff7c4d26ba4ca435e01", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "a049e65180c91432e8cba0b6417980d8fbbce81b0da0cbebf949509c4c30231b", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-531.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-531.md",
      "inverse_command": "gh issue edit 531 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-531.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:21.601712+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "a049e65180c91432e8cba0b6417980d8fbbce81b0da0cbebf949509c4c30231b", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#529": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 529,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "parked-529",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/2026-10-13-529-gate-reconciliation.md",
        "purpose": "New dated gate/accounting node",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/ac_harness/auto_alien.py",
        "purpose": "Only after explicit remaining pace experiment/requirement decision",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/plant_id.py",
        "purpose": "Only evidence-driven fit delta",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/alien_scientist.py",
        "purpose": "Only evidence-driven experiment/prior delta",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/track_reference.py",
        "purpose": "Reference/frontier acceptance integration if needed",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/driver_progression.py",
        "purpose": "Longitudinal human frontier evidence if needed",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_auto_alien.py",
        "purpose": "Pace/validity pipeline regressions",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_plant_id.py",
        "purpose": "Plant provenance/refit regressions",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_alien_scientist.py",
        "purpose": "Experiment attribution/decision regressions",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_track_reference.py",
        "purpose": "Human/alien frontier semantics",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 3,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/529",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-529.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        }
      ]
    },
    "run_ts": "2026-10-13T02:25:37.573375+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "partially-delivered",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 4,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #682 / env_observer.environment_from_archives + stint_optimizer.plan_stint + alien_scientist.meta_priors",
            "detail": "L0/L4/META previously described as unbuilt now exist and have focused tests.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/682"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #748 / auto_alien.flying_lap_consistency + evaluate_selfplay_iteration",
            "detail": "Repeatability oracle withdraws retention of 80.791/95.122s batch; G2 still rests on repeatable 81.505/81.519s.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/748"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #766/#770/#776 / plant_id.selfplay_refine_result and thermal eligibility",
            "detail": "Temperature-tagged retained refit and evidence attribution hardening delivered.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/776"
          },
          {
            "kind": "merged-vault",
            "anchor": "PR #812 / handoff 2026-10-12-191700Z-c1-live-acceptance-87ff.md",
            "detail": "Conservative 1.10 Huracan/Spa inherited two merges, adopted three lateral bins, drove valid plant step and retained third merge. Original 1.15 replay falsified; no pace-gain claim.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/812"
          },
          {
            "kind": "current-code",
            "anchor": "track_reference.CornerReference / add_corpus_lap; tt_normalize.build_reference_archive",
            "detail": "Human reference technique already feeds coaching; exact full-lap identity/coverage/provenance guards exist. External reference adapters should reuse these seams."
          }
        ],
        "counterevidence": [
          "G1 remains cold unseen known archetype within 5% current TT top-10 in <=20 laps, not retained-plant improvement.",
          "Inherited TT P10 number is dated/unverified; do not relabel current performance using it.",
          "C1 conservative variant flyers were slightly slower than prior envelope flyers; successful adoption is not pace improvement.",
          "G3 requires a human across sessions; cannot be manufactured by autonomous runs or MOZA reference availability.",
          "MOZA does not replace measured local plant dynamics, setup/tyre/environment provenance, controller or validity oracle."
        ],
        "remaining_acceptance": [
          "Fresh eligible same-combo benchmark and explicit decision whether original cold-start pace/budget remains governing; no silent redefinition.",
          "Evidence-backed G1 pace under retained original requirements if not re-scoped.",
          "G3 human frontier shrink over multiple sessions, live cue/debrief connection.",
          "Keep G4 honesty/provenance/false-green contract with corrected repeatability and current scientist/retained-fit evidence."
        ],
        "recommended_action": "Keep not-this-cycle; update gate ledger, retire #749 blanket blocker narrative, preserve unmet G1/G3.",
        "issue_source_sha256": "c4fee6b60abf58bd23d57d6bd8f3acb06ef2f547fd859d4e195d317460b28e6b", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 529 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-529.before.md\""
    }
  },
  "agorokh/ac-copilot-trainer#401": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 401,
    "last_verdict": "live",
    "confidence": "high",
    "block_id": "parked-401",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md",
        "purpose": "Canonical durable pair of issue #401 body",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-13-roadmap-reconciled.md",
        "purpose": "New supporting receipt",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 4,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/401",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-401.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        }
      ]
    },
    "run_ts": "2026-10-13T02:31:39.524430+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "drifted",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 4,
        "evidence": [
          {
            "kind": "current-doc",
            "anchor": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md:Vertical status map + Invariant",
            "detail": "Still says #675 open, #674 unbuilt, #534 zero-built, #627 blocks all live gates and first real scientist batch pending."
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #687 / coach V2 phase-slot/calibration/between-lap advice",
            "detail": "Contradicts #675 open capability premise.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/687"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #682 / L0+L4+META",
            "detail": "Contradicts unbuilt #674.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/682"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #689/#692 / car-class authority and bridge",
            "detail": "Contradicts #534 zero-built.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/689"
          },
          {
            "kind": "merged-vault",
            "anchor": "PR #812 / retained C1 acceptance",
            "detail": "Latest original-versus-conservative variant and corrected scientist facts replace old broad rig-blocked state.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/812"
          }
        ],
        "counterevidence": [
          "Thin driver model and strategy depth may still be open questions; function presence alone does not establish robust pedagogy or strategy depth.",
          "Roadmap is a live coordination object, not a stale issue to close.",
          "Potential MOZA opportunity is new evidence, not authorization to overwrite original program or reopen all parked tracks."
        ],
        "remaining_acceptance": [
          "Refresh #401 body and Roadmap.md together, keeping current main delivery plus explicit remaining acceptance distinct.",
          "Add #804 and #813 ownership, mark closed successor capabilities shipped, correct #534 and #529 status and #627 non-universal blocker.",
          "Adjudicate actual future capability priorities only after preserving historical not-this-cycle/operator decisions."
        ],
        "recommended_action": "Prepare paired roadmap rewrite; retain not-this-cycle until operator selects it.",
        "issue_source_sha256": "31f2fef4406b53ea5aa2562e1d3c2b696677b74b8f0d6478ae683651f3dff8bf", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 401 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-401.before.md\""
    },
    "post814_receipt": {
      "issue": 401,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/401",
      "planned_at": "2026-10-13T02:30:16.300465+00:00",
      "before_sha256": "13e2cfff36f8663abf5a232f5389d13513ea2707d736dc6a115dd007af35d9c9", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "790bd7c8c683775a5247db727377cda96fb08ece5b4c9307a91e5efdc6fe0638", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-401.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-401.md",
      "inverse_command": "gh issue edit 401 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-401.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:18.004333+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "790bd7c8c683775a5247db727377cda96fb08ece5b4c9307a91e5efdc6fe0638", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#117": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 117,
    "last_verdict": "live",
    "confidence": "high",
    "block_id": "parked-117",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "firmware/arduino_fan_oled/platformio.ini",
        "purpose": "Proposed distinct UNO project; exact location selected before implementation",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "firmware/arduino_fan_oled/src/main.cpp",
        "purpose": "Bounded PWM and OLED consumer",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "firmware/arduino_fan_oled/README.md",
        "purpose": "Transport/bench/electrical safety",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/arduino_fan_oled.py",
        "purpose": "Proposed bounded PC bridge if sidecar-owned",
        "status": "new",
        "scope": "remaining"
      },
      {
        "path": "tests/test_arduino_fan_oled_protocol.py",
        "purpose": "Simulator-free contract/limits fixtures",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 2,
      "evidence": [
        {
          "kind": "current-tree",
          "anchor": "firmware/ contains only screen/ ESP32 project",
          "detail": "No Arduino UNO fan PWM/SSD1306 firmware or corresponding transport tests found."
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #689 scope gates",
          "detail": "Explicitly retains Part C dependency on #117 and does not simulate absent fan actuator.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/689"
        },
        {
          "kind": "current-issue",
          "anchor": "issue #117 closure condition",
          "detail": "Bench test frame must drive bounded fan PWM and tyre OLED through documented transport.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/117"
        }
      ],
      "counterevidence": [
        "ESP32 screen is a different hardware surface.",
        "TT25/SimHub pedal hardware and class adapter do not implement fan PWM or SSD1306 tyre OLED.",
        "Live hardware/electrical availability was not inspected by this read-only audit."
      ],
      "remaining_acceptance": [
        "UNO bounded fan PWM, OLED temperature/pressure/wear test frame.",
        "Document PC transport plus electrical/thermal safety.",
        "Real bench proof under documented transport."
      ],
      "recommended_action": "Keep parked; do not fold into active display/MOZA work.",
      "issue_source_sha256": "dd5ab2967ecf4d6d7b20db4c846d534736363c600c9dee333980d7e98f299a78", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    },
    "run_ts": "2026-10-13T01:54:56.485895+00:00",
    "run_id": "9ed2f3"
  },
  "agorokh/ac-copilot-trainer#86": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 86,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "block_id": "parked-86-smoke",
    "group_with": [],
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-13-86-device-smoke.md",
        "purpose": "New dated actual device proof",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "firmware/screen/src/ui/screen_setup_exchange.cpp",
        "purpose": "Only if full smoke reveals a concrete defect",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/se_proxy.py",
        "purpose": "Only if full smoke reveals a concrete proxy/install defect",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_setup_exchange_proxy.py",
        "purpose": "Only for demonstrated proxy defect",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "preserve_existing_disposition": true,
    "board_move": null,
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 4,
      "evidence": [
        {
          "kind": "prior-audit",
          "anchor": "prior_audit.evidence_snapshot",
          "detail": "Dated code/merged-PR evidence retained; stale-body descriptions there are historical, superseded by this update."
        },
        {
          "kind": "github-body-readback",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/86",
          "detail": "Authorized shipped-state correction applied; exact body verified and title/state/labels/assignees/milestone preserved."
        },
        {
          "kind": "mutation-receipt",
          "anchor": ".scratch/moza-qualification/backlog-updates/applied/issue-86.receipt.json",
          "detail": "Original body, metadata, hashes and inverse command retained; #529 additionally has an attribution-correction receipt."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        }
      ]
    },
    "run_ts": "2026-10-13T02:31:39.556285+00:00",
    "run_id": "ce1e22",
    "prior_audit": {
      "last_verdict": "partially-delivered",
      "run_id": "9ed2f3",
      "evidence_snapshot": {
        "main_sha": "a71ad9ccf92942b6a6c69583639c1c90b6da4526", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
        "signals_count": 4,
        "evidence": [
          {
            "kind": "merged-pr",
            "anchor": "PR #365 / SetupExchangeClient.search + download_and_install_setup + firmware screen_setup_exchange",
            "detail": "Search/download/install and PT path shipped; tests/test_setup_exchange_proxy.py cover bounded response/path safety/no overwrite.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/365"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #430 / generated font_saira_* and font_spline_* + tests/test_rig_screen_racing_atelier.py",
            "detail": "Racing Atelier fonts supersede original body faces; actual generated files committed.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/430"
          },
          {
            "kind": "merged-pr",
            "anchor": "PR #680 / persist.cpp + link_stats.cpp + screen_debug.cpp",
            "detail": "Nonblocking #677 polish shipped too; do not rebuild from old body checklist.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/pull/680"
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comment 5077070536",
            "detail": "Operator 1C narrows epic to four-leg on-device flow plus photo comparison.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-5077070536"
          },
          {
            "kind": "issue-current-disposition",
            "anchor": "issue comment 6132771922",
            "detail": "New video proves physical Copilot motion but defects go to #813; Setup Exchange/full gate retained.",
            "url": "https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6132771922"
          }
        ],
        "counterevidence": [
          "Phone video does not show full Launcher -> Copilot -> Pocket Technician setup load -> Setup Exchange browse/download/install.",
          "#813 semantics/readability corrections must pass before crediting related Copilot/PT smoke legs.",
          "No present rig state, firmware flash or on-device acceptance was executed in this audit."
        ],
        "remaining_acceptance": [
          "After #813 correction/distribution, operator four-leg touch flow including Setup Exchange browse/download/install and PT loaded result.",
          "On-glass photo against Racing Atelier target and explicit evidence receipt."
        ],
        "recommended_action": "Keep not-this-cycle and status:blocked-on-rig; coordinate a shared evidence session but do not merge issue ownership.",
        "issue_source_sha256": "67455bfba6abbb288f9ac939109f41cf133121acb8f4b69630a516c42e5db1a8", "issue_source_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    },
    "tracker_action": {
      "body_updated": true,
      "closed": false,
      "labels_changed": false,
      "inverse": "gh issue edit 86 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\applied\\issue-86.before.md\""
    },
    "post814_receipt": {
      "issue": 86,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/86",
      "planned_at": "2026-10-13T02:30:37.907198+00:00",
      "before_sha256": "e962d03686656167083ed7a16422925a7d3685600abe64aac271364c693c2a9c", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "93582cae1c0874392c6d6dddea5d13f40c3d6066a37d92ea9825fd53cdc694b9", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-86.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-86.md",
      "inverse_command": "gh issue edit 86 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-86.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:39.380488+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "93582cae1c0874392c6d6dddea5d13f40c3d6066a37d92ea9825fd53cdc694b9", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    }
  },
  "agorokh/ac-copilot-trainer#815": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 815,
    "last_verdict": "live",
    "confidence": "high",
    "block_id": "815-moza-qualification-import",
    "group_with": [],
    "do_not_merge": false,
    "scope-evolution-accepted": false,
    "operator_selected": "Part A passive validation; production integration awaits qualification and PR814 resolution",
    "board_move": null,
    "run_id": "ce1e22",
    "run_ts": "2026-10-13T02:44:09.225836+00:00",
    "files_to_touch": [
      {
        "path": "tools/moza_ingest/__init__.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tools/moza_ingest/__main__.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tools/moza_ingest/reader.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tools/moza_ingest/normalize.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tests/test_moza_ingest.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tests/test_moza_qualification.py",
        "status": "new",
        "scope": "planned-production",
        "purpose": "Provider reader/normalization and synthetic qualification coverage"
      },
      {
        "path": "tools/ac_harness/reference_lap.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/realtime_observer.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/coaching_runtime.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/coaching_oracle.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/driver_profile.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/lap_dynamics.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/server.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/session_review/report.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/rig_launcher/supervisor.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/rig_launcher/app.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/rig_launcher/view.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_reference_lap.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_coaching_oracle.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_coaching_v2.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_driver_progression.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_session_review.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_server_observer_wiring.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tests/test_rig_launcher.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse shared reference, diagnosis, voice and launcher acceptance boundaries after refreshed seam check"
      },
      {
        "path": "tools/ai_sidecar/track_map.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse merged814 provenance, measured timing/coverage, canonical corners and comparison guards"
      },
      {
        "path": "tests/test_track_map.py",
        "status": "exists",
        "scope": "planned-production",
        "purpose": "Reuse merged814 provenance, measured timing/coverage, canonical corners and comparison guards"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "src/ac_copilot_trainer/modules/persistence.lua",
        "status": "exists",
        "scope": "conditional-production",
        "purpose": "Only if Lua reference activation is selected"
      },
      {
        "path": "tests/test_reference_activation.py",
        "status": "exists",
        "scope": "conditional-production",
        "purpose": "Only if Lua reference activation is selected"
      }
    ],
    "current_allowed_work": ".scratch/moza-qualification/passive/ scripts and sanitized evidence; dated vault notes",
    "sequence_after": [
      {
        "pr": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
        "applies_to": "shared production-file edits",
        "release": "Merge gate satisfied; future production work must refresh shared consumer/provenance seams and retain #813 physical ownership",
        "state": "MERGED",
        "merge_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "merge_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
      }
    ],
    "evidence_snapshot": {
      "main_sha": "b513d05f80a1ed32bcbd2b68f5ffec76ffa3df7c", "main_sha_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "signals_count": 5,
      "evidence": [
        {
          "kind": "created-issue",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/815",
          "detail": "User-selected four-Part carrier, created after current issue/PR seam and pitfalls checks."
        },
        {
          "kind": "local-inspection",
          "anchor": ".scratch/backlog-steward/moza-local/journal-correlation-summary.json",
          "detail": "Four readable view caches, two strong native trajectory candidates, unknown control and reference origin; qualification started."
        },
        {
          "kind": "reuse-contract",
          "anchor": ".scratch/backlog-steward/architecture-review.md",
          "detail": "TT ingest and CoachV2 exist; source-neutral acceptance/provenance remains needed."
        },
        {
          "kind": "merged-pr-current-refresh",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Merged at 2026-10-13T02:07:07Z as b513d05; source fetched/branch fast-forwarded. Owner checkpoint reports distribution, retains physical acceptance. Bodies corrected with exact readback."
        },
        {
          "kind": "passive-qualification",
          "anchor": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\docs\\01_Vault\\AcCopilotTrainer\\03_Investigations\\2026-10-13-024319Z-moza-passive-qualification-815-2e7b78.md",
          "detail": "Reviewed bounded negative first pass. Unknown authority/conditions/reference origin and channel semantics; all import/live/PB/plant/event uses false. No source or rig action."
        }
      ]
    },
    "post814_receipt": {
      "issue": 815,
      "url": "https://github.com/agorokh/ac-copilot-trainer/issues/815",
      "planned_at": "2026-10-13T02:30:34.622910+00:00",
      "before_sha256": "19c8a4b3257a7de93b61f89a802683d9455cd9db131536671b06ba51323ad76b", "before_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "proposed_sha256": "2d710643674b4e2b7f421cb42eb459f51aa2647de5dea3dc57b15159b0f5dbc6", "proposed_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret",
      "original_snapshot": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-815.before.json",
      "draft": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\drafts\\issue-815.md",
      "inverse_command": "gh issue edit 815 --repo agorokh/ac-copilot-trainer --body-file \"C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\backlog-updates\\post814\\applied\\issue-815.before.md\"",
      "applied": true,
      "applied_at": "2026-10-13T02:30:36.132064+00:00",
      "readback_matches": true,
      "metadata_preserved": true,
      "readback_sha256": "2d710643674b4e2b7f421cb42eb459f51aa2647de5dea3dc57b15159b0f5dbc6", "readback_sha256_provenance": "Git commit or recorded issue-body digest; # pragma: allowlist secret"
    },
    "qualification_progress": {
      "part_a_complete": false,
      "bounded_first_pass": "completed and independently reviewed",
      "artifacts": 4,
      "native_candidates": 28,
      "stable_real_inputs": 193,
      "reader_synthetic_checks": "4/4",
      "slower_views": "ambiguous close native candidates under exploratory method",
      "faster_views": "no adequate match among tested candidates",
      "production_uses_qualified": false,
      "note": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\docs\\01_Vault\\AcCopilotTrainer\\03_Investigations\\2026-10-13-024319Z-moza-passive-qualification-815-2e7b78.md",
      "report": "C:\\Users\\arsen\\.codex\\worktrees\\ad67\\ac-copilot-trainer\\.scratch\\moza-qualification\\passive\\report.md"
    }
  }
}
```
