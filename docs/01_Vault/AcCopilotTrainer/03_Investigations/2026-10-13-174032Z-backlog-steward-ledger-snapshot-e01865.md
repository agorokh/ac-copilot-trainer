---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-174032Z-moza-reuse-decision-815-e01865.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-022537Z-backlog-steward-ledger-snapshot-ce1e22.md
---

# Backlog ledger after completed MOZA qualification research

Ten open owners: seven partially delivered and three live; zero closure candidates.
Issue-only reconciliation: no board configured or moved. No issue was closed or unparked.
Part A research is complete; Parts B–D and per-use production eligibility remain open.
Native control provenance/shared eligibility precedes incremental cache adaptation; retain TT.
The narrow #813 ESP32 waiver does not discharge P7 or another issue's acceptance.
The parent refreshed Tier-3 successfully; its generic context did not newly ratify dispositions.
Current operator records and exact acceptance clauses ground these decisions.

Paired #401/Roadmap and #815 changes, plus narrow factual references in #804/#531/#86/#627/#117,
are the publication set. Exact originals, inverses, body hashes and readback receipts remain
under `.scratch/moza-qualification/original-directive-resume/publication/` and
`.scratch/backlog-steward/original-directive-resume/`. Earlier ledger snapshots preserve the
full historical chain; this compact overlay preserves current evidence, owners and dispositions.
The repository's established investigation location is `03_Investigations/`.

```json
{
  "agorokh/ac-copilot-trainer#813": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 813,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Display semantics/MAP source shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/819",
          "detail": "Merged vault-only recording attempt; does not certify retained physical gates."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/track_map.py:build_corner_comparison",
          "detail": "Current measured reference/canonical corner path exists."
        },
        {
          "kind": "operator-disposition",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6140089525",
          "detail": "Explicit ESP32 physical waiver only; retained P7/lap requirements unchanged."
        }
      ],
      "remaining_acceptance": "P7 recording plus operator-driven valid Porsche/Magione lap, retained electronics/action/target/MAP comparisons and Android stale transition. ESP32 physical portion is explicitly waived only here. P7 disconnected is dated last-owner evidence, not this audit probing hardware.",
      "counterevidence_to_close": "P7 recording plus operator-driven valid Porsche/Magione lap, retained electronics/action/target/MAP comparisons and Android stale transition. ESP32 physical portion is explicitly waived only here. P7 disconnected is dated last-owner evidence, not this audit probing hardware.",
      "recommended_action": "keep open; No duplicate body/comment needed: current body already records the waiver and remaining scope. Optionally link merged #819 without changing acceptance.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "existing-813-carrier",
    "do_not_merge": true,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#804": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 804,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/805",
          "detail": "Startup sizing shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/809",
          "detail": "Finite setup archive scan fixed."
        },
        {
          "kind": "current-code",
          "anchor": "src/ac_copilot_trainer/modules/setup_library.lua:bestForSetups",
          "detail": "Metadata scan behavior exists; keep finite-stall fix separate from terminal freeze."
        },
        {
          "kind": "tracker",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/804",
          "detail": "Five checked clauses and one rendering clause retained in fresh body."
        }
      ],
      "remaining_acceptance": "Only live rig-screen consumption/actual rendering checkbox remains unchecked. New MOZA native capture and the #813-only waiver do not complete this checkbox.",
      "counterevidence_to_close": "Only live rig-screen consumption/actual rendering checkbox remains unchecked. New MOZA native capture and the #813-only waiver do not complete this checkbox.",
      "recommended_action": "keep open; Correct only the cross-reference that still describes ESP32 on-glass as retained under #813; preserve #804 own screen criterion. Replace #815 passive-only wording with current bounded qualification status if touched.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "804-acceptance",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#627": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 627,
    "last_verdict": "live",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/726",
          "detail": "NOT_DRIVABLE distinguished from terminal freeze."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/809",
          "detail": "Finite setup scan fixed separately."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ac_harness/resilient_launch.py:LaunchVerdict / FREEZE_VERDICTS / classify",
          "detail": "Current main retains explicit symptom classification."
        },
        {
          "kind": "operator-disposition",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5446782477",
          "detail": "C2 remains one standalone whole-issue block, no successors/split."
        }
      ],
      "remaining_acceptance": "Standalone C2 symptom/causal investigation remains. Successful MOZA launches/lap and finite scan fixes establish neither a current denominator nor sustained render-wedge cause.",
      "counterevidence_to_close": "Standalone C2 symptom/causal investigation remains. Successful MOZA launches/lap and finite scan fixes establish neither a current denominator nor sustained render-wedge cause.",
      "recommended_action": "keep open; No substantive rewrite or new progress comment needed. Keep C2 and standalone no-split contract; narrowly fix #813 cross-reference only if parent consolidates all such references.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "C2",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#534": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 534,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/689",
          "detail": "Class resolver/SimHub bridge software shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/692",
          "detail": "Plugin lifecycle/replay hardening shipped."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/car_class.py:resolve_installed_car",
          "detail": "Current class resolver persists."
        },
        {
          "kind": "current-code",
          "anchor": "tools/simhub_car_enrichment/AcCopilot.CarEnrichment/AcCopilotDataPlugin.cs:AcCopilotDataPlugin",
          "detail": "Publisher is distinct from reverse vitals fusion."
        }
      ],
      "remaining_acceptance": "A/B software delivered; installed SimHub property/NCalc proof still operator-owned. C depends on #117, D dormant, E optional physical/audio experiment.",
      "counterevidence_to_close": "A/B software delivered; installed SimHub property/NCalc proof still operator-owned. C depends on #117, D dormant, E optional physical/audio experiment.",
      "recommended_action": "keep open; No body/comment change needed. Keypad firmware/controller delivery is not fan, SimHub class acceptance or audio/haptic activation.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "parked-534",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#531": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 531,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/618",
          "detail": "Delivered modal COACH/MAP/STINT depth."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Bounded new MAP/display software under separate #813."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/690",
          "detail": "Critical articulation does not satisfy mic or native latency."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/voice/scheduler.py:Scheduler",
          "detail": "Existing scheduling is a reusable seam, not P7 audible-latency evidence."
        }
      ],
      "remaining_acceptance": "G native critical audio/P7 <450ms, H build-or-strike SimHub vitals decision, I mic transport, broader Part F/device/10-minute <=15Hz soak and intervention/spec-motion proof remain parked.",
      "counterevidence_to_close": "G native critical audio/P7 <450ms, H build-or-strike SimHub vitals decision, I mic transport, broader Part F/device/10-minute <=15Hz soak and intervention/spec-motion proof remain parked.",
      "recommended_action": "keep open; Only refresh #815 completed-research/Part-B and #813 narrow-waiver cross-references; retain all G/H/I and broader physical criteria, not-this-cycle, and separate ownership.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [
      {
        "path": "tools/ai_sidecar/voice/web/tablet_voice.html",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tools/ai_sidecar/voice/audible_latency.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tools/ai_sidecar/server.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tools/ai_sidecar/external_protocol.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tools/ai_sidecar/registers.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tools/ai_sidecar/dash/web/tablet_dash.html",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tests/test_voice_tablet_endpoint.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tests/test_audible_latency.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tests/test_audio_routing.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      },
      {
        "path": "tests/test_tablet_dash_endpoint.py",
        "status": "exists-main",
        "scope": "parked-conditional-source",
        "purpose": "Only if operator revives parked Phase3/verification; these overlapping seams require sequencing"
      }
    ],
    "group_with": [],
    "block_id": "parked-531",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#529": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 529,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/682",
          "detail": "L0/L4/META shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/687",
          "detail": "Coach v2 shipped, not G3 outcome."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/812",
          "detail": "C1 acceptance and corrected falsification already accounted for."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ac_harness/auto_alien.py:flying_lap_consistency / evaluate_selfplay_iteration",
          "detail": "Current main retains repeatability guard."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ac_harness/alien_scientist.py:meta_priors",
          "detail": "Matched evidence and flying-lap requirements retained."
        }
      ],
      "remaining_acceptance": "G1 cold-start within 5% TT top-10 in <=20 laps remains unmet; G1b original budget/fallback scope retained; G3 human improvement remains operator-gated. G2 uses repeatable81.505/81.519s; C1 closure is already reconciled.",
      "counterevidence_to_close": "G1 cold-start within 5% TT top-10 in <=20 laps remains unmet; G1b original budget/fallback scope retained; G3 human improvement remains operator-gated. G2 uses repeatable81.505/81.519s; C1 closure is already reconciled.",
      "recommended_action": "keep open; No body/checkbox change needed. MOZA research does not replace plant/controller, TT pace baseline, cold-start budget or human G3. Keep not-this-cycle and do_not_merge.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "parked-529",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#401": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 401,
    "last_verdict": "live",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/819",
          "detail": "Dated display capture evidence, no acceptance closure."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/825",
          "detail": "Game Point keypad worker/status changes landed after prior base."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/826",
          "detail": "Managed keypad firmware prepared, physical adoption still withheld."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/driver_profile.py:_is_driver_lap",
          "detail": "MOZA native provenance gap is a specific next shared-consumer need."
        },
        {
          "kind": "tracker",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/401",
          "detail": "Body explicitly declares paired Roadmap invariant."
        }
      ],
      "remaining_acceptance": "Living roadmap remains open; paired body/Roadmap must reflect bounded #815 research completion, next PartB, #813 narrow waiver, and newer keypad software without claiming physical acceptance.",
      "counterevidence_to_close": "Living roadmap remains open; paired body/Roadmap must reflect bounded #815 research completion, next PartB, #813 narrow waiver, and newer keypad software without claiming physical acceptance.",
      "recommended_action": "keep open; Update #401 and Roadmap.md together: Part A research complete with positive/negative findings; PartB next; #813 ESP32 waived/P7 retained; source-currentness through #825/#826 with keypad physical owner external #3863. Preserve parked programme disposition.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md",
        "status": "exists-main",
        "scope": "metadata-only",
        "purpose": "Mandatory durable pair of issue401 metadata"
      }
    ],
    "group_with": [],
    "block_id": "parked-401",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#117": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 117,
    "last_verdict": "live",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/203",
          "detail": "Existing sidecar protocol/cues do not supply Arduino firmware."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/826",
          "detail": "New keypad firmware is not Arduino fan/OLED."
        },
        {
          "kind": "tree",
          "anchor": "main-tree.json",
          "detail": "No firmware/arduino_fan_oled implementation; new firmware/keypad exists."
        },
        {
          "kind": "operator-disposition",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/117#issuecomment-5077070595",
          "detail": "Decision2C preserves revival trigger and firmware+USB CDC scope."
        }
      ],
      "remaining_acceptance": "Arduino UNO fan/OLED firmware + USB CDC still absent; operator-deferred until #627 resolved or parked. Keypad is distinct hardware/function.",
      "counterevidence_to_close": "Arduino UNO fan/OLED firmware + USB CDC still absent; operator-deferred until #627 resolved or parked. Keypad is distinct hardware/function.",
      "recommended_action": "keep open; Optional one-line evidence correction: firmware now also contains keypad, so only-ESP32 sentence is obsolete; do not rewrite acceptance or unpark.",
      "prior_snapshot_run_id": "9ed2f3",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [
      {
        "path": "firmware/arduino_fan_oled/platformio.ini",
        "status": "new-proposed",
        "scope": "parked-conditional-source",
        "purpose": "Only on operator revival; reuse existing transport rather than duplicate sidecar protocol"
      },
      {
        "path": "firmware/arduino_fan_oled/src/main.cpp",
        "status": "new-proposed",
        "scope": "parked-conditional-source",
        "purpose": "Only on operator revival; reuse existing transport rather than duplicate sidecar protocol"
      },
      {
        "path": "firmware/arduino_fan_oled/README.md",
        "status": "new-proposed",
        "scope": "parked-conditional-source",
        "purpose": "Only on operator revival; reuse existing transport rather than duplicate sidecar protocol"
      },
      {
        "path": "tests/test_arduino_fan_oled_protocol.py",
        "status": "new-proposed",
        "scope": "parked-conditional-source",
        "purpose": "Only on operator revival; reuse existing transport rather than duplicate sidecar protocol"
      }
    ],
    "group_with": [],
    "block_id": "parked-117",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#86": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 86,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/430",
          "detail": "Atelier fonts/theme code shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/365",
          "detail": "Setup Exchange/PT integration shipped."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/680",
          "detail": "Optional polish shipped."
        },
        {
          "kind": "current-code",
          "anchor": "firmware/screen/src/ui/screen_setup_exchange.cpp:screen_setup_exchange_create",
          "detail": "Existing implementation is not full physical smoke proof."
        },
        {
          "kind": "operator-disposition",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-5077070536",
          "detail": "Decision1C retains sole smoke/photo closure gate."
        }
      ],
      "remaining_acceptance": "Own four-leg on-device Launcher->Copilot->PT load->Setup Exchange browse/download/install and on-glass photo/glyph comparison remain operator gated. #813 waiver does not transfer.",
      "counterevidence_to_close": "Own four-leg on-device Launcher->Copilot->PT load->Setup Exchange browse/download/install and on-glass photo/glyph comparison remain operator gated. #813 waiver does not transfer.",
      "recommended_action": "keep open; Correct only #813 cross-reference for its ESP32-only waiver; do not weaken this issue own photo/device clauses. Keep blocked-on-rig and not-this-cycle.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [],
    "group_with": [],
    "block_id": "parked-86-smoke",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  },
  "agorokh/ac-copilot-trainer#815": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 815,
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "evidence_snapshot": {
      "main_commit": "6321ce4",
      "signals": [
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/359",
          "detail": "Existing TT provider remains a reuse seam; no TT replacement."
        },
        {
          "kind": "merged-pr",
          "anchor": "https://github.com/agorokh/ac-copilot-trainer/pull/814",
          "detail": "Measured MAP/corner consumer already delivered."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/driver_profile.py:_is_driver_lap",
          "detail": "Excludes imported/reference tags but accepts native in_game; actual MOZA native lap has is_pb=true."
        },
        {
          "kind": "current-code",
          "anchor": "tools/ai_sidecar/track_map.py:_reference_provenance_valid / _valid_trace / _normalise_finish_wrap",
          "detail": "Same blobs as current main; read-only protected-copy probe accepted native format and 1999-sample finish-trimmed trace; not a human-authority gate."
        },
        {
          "kind": "direct-artifact",
          "anchor": ".scratch/moza-qualification/part-a3-live/attempt2/evaluation-linkage.json",
          "detail": "Practice cache lapId exactly joins evaluation id/recordUid; aiIntervened=true and eligibility=ai-debug-only. Native association is prospective/numeric, not shared session ID."
        },
        {
          "kind": "research-evidence",
          "anchor": ".scratch/moza-qualification/part-a2/report.md#Part A acceptance accounting",
          "detail": "A1-A5 allow bounded negative/unknown conclusions; historical origins need not become production-qualified to finish research."
        },
        {
          "kind": "acceptance-audit",
          "anchor": ".scratch/moza-qualification/original-directive-resume/part-a/decision.json",
          "detail": "Parent and independent Astra review confirm unchanged A1-A5 permit bounded research conclusions. Earlier incomplete wording conflated later production gates with Part A."
        }
      ],
      "remaining_acceptance": "Part A bounded qualification research is evidenced; Parts B-D adapter, source-neutral policy, report/launcher integration, silent replay and activation decision remain. No human/reference/plant/voice qualification is implied.",
      "counterevidence_to_close": "Part A bounded qualification research is evidenced; Parts B-D adapter, source-neutral policy, report/launcher integration, silent replay and activation decision remain. No human/reference/plant/voice qualification is implied.",
      "recommended_action": "keep open; Replace start/continue passive status with completed bounded Part A; map all five clauses to evidence, preserve negative findings; Part B next. Clarify B3 covers known observed AI/shared native in_game records as well as imports, without relabeling unrelated history. Refresh integration base beyond #814 to current main including #825.",
      "prior_snapshot_run_id": "ce1e22",
      "tier3": "Parent fresh query succeeded with older generic context; dispositions grounded in live operator records, not newly ratified by substrate."
    },
    "files_to_touch": [
      {
        "path": "tools/moza_ingest/__init__.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tools/moza_ingest/__main__.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tools/moza_ingest/reader.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tools/moza_ingest/normalize.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tests/test_moza_ingest.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tests/test_moza_qualification.py",
        "status": "new-proposed",
        "scope": "remaining-source",
        "purpose": "Versioned adapter and synthetic input qualification"
      },
      {
        "path": "tools/ac_harness/reference_lap.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/realtime_observer.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/coaching_runtime.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/coaching_oracle.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/driver_profile.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/lap_dynamics.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/track_map.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/ai_sidecar/server.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/session_review/report.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_reference_lap.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_driver_progression.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_track_map.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_coaching_v2.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_coaching_oracle.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_session_review.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tests/test_server_observer_wiring.py",
        "status": "exists-main",
        "scope": "remaining-source",
        "purpose": "Shared provenance/eligibility at existing consumer constructors; preserve TT and measured gates"
      },
      {
        "path": "tools/rig_launcher/app.py",
        "status": "exists-main",
        "scope": "later-part-source",
        "purpose": "Parts C/D canonical selection and silent replay; sequence after core qualification"
      },
      {
        "path": "tools/rig_launcher/supervisor.py",
        "status": "exists-main",
        "scope": "later-part-source",
        "purpose": "Parts C/D canonical selection and silent replay; sequence after core qualification"
      },
      {
        "path": "tools/rig_launcher/view.py",
        "status": "exists-main",
        "scope": "later-part-source",
        "purpose": "Parts C/D canonical selection and silent replay; sequence after core qualification"
      },
      {
        "path": "tests/test_rig_launcher.py",
        "status": "exists-main",
        "scope": "later-part-source",
        "purpose": "Parts C/D canonical selection and silent replay; sequence after core qualification"
      },
      {
        "path": "tests/test_voice_scheduler.py",
        "status": "exists-main",
        "scope": "later-part-source",
        "purpose": "Parts C/D canonical selection and silent replay; sequence after core qualification"
      },
      {
        "path": "src/ac_copilot_trainer/modules/lap_archive.lua",
        "status": "exists-main",
        "scope": "native-first-provenance-design",
        "purpose": "Inspect native authority/archival contract and cover assisted native records; preserve historical bytes. Exact implementation change follows Part B design."
      },
      {
        "path": "tests/test_lap_archive_export.py",
        "status": "exists-main",
        "scope": "native-first-provenance-design",
        "purpose": "Inspect native authority/archival contract and cover assisted native records; preserve historical bytes. Exact implementation change follows Part B design."
      },
      {
        "path": "tests/test_lap_archive_source_structure.py",
        "status": "exists-main",
        "scope": "native-first-provenance-design",
        "purpose": "Inspect native authority/archival contract and cover assisted native records; preserve historical bytes. Exact implementation change follows Part B design."
      }
    ],
    "group_with": [],
    "block_id": "815-moza-qualification-import",
    "do_not_merge": false,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-10-13T17:50:28.445833+00:00",
    "run_id": "e01865"
  }
}
```
