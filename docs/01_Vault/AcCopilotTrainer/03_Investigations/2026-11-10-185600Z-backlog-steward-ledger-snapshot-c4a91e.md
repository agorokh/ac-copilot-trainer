---
type: investigation
status: active
created: 2026-11-10
updated: 2026-11-10
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-10-185600Z-backlog-steward-reconcile-c4a91e.md
  - AcCopilotTrainer/03_Investigations/2026-10-18-175107Z-backlog-steward-ledger-snapshot-bdd6d5.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/pitfalls/linkage-autoclose-against-intent.md
---

# Backlog ledger snapshot — 2026-11-10 (run `c4a91e`, settled post-disposition)

`/backlog-steward` run `c4a91e` over `agorokh/ac-copilot-trainer` at merged `main` `145c07a`
(diffed against 2026-10-18 snapshot `bdd6d5` at `8fade2c`), followed by operator-confirmed gate
dispositions (`A1`–`A5`). Initial read-only audit classified six open issues (`live` 2: `#401`,
`#117`; `partially-delivered` 4: `#815`, `#86`, `#529`, `#534`), nine closed-since-ledger issues
(`#627` plus eight 1:1 PR deliveries `#881`..`#938`), and one carried-forward closure exception
(`#813`), with `3-0` Council concurrence (`gpt` + `mistral`).

Settled post-disposition tracker state (`2026-11-10T19:55:00+00:00`, **4 open issues** remaining):
- **Closed with explicit boundary dispositions:** `#815` (`comment 6777499356`: 18/18 Part A–D
  engineering/acoustic `1deb45d`/rendered-HUD `d881fb9` PASS; `human_live_qualification` retained
  `NOT_ESTABLISHED_BY_THIS_ENGINEERING_CAPTURE`, MOZA/legacy-unknown artifacts unpromoted) and
  `#534` (`comment 6777501131`: live SimHub 9.13.2 Parts A+B `696292a`; Part C assigned to parked
  `#117`, Parts D/E dropped/deferred).
- **Dispositioned Done-ghost:** `#813` (`comment 6777498061`: kept closed, accepting `#531` /
  `PR #849` autonomous P7 evidence and waiving the separate human-driven P7 lap and menu-exit
  stale check).
- **Refreshed active open issues (`4`):** `#86` (body refreshed through `145c07a` with `#891` /
  `#904` / `#906` + `16068f3` EXE note; 5 Copilot render diffs deferred to next rig session),
  `#529` (stale Oct 13 header replaced with Oct 16/24 McLaren runs, `qualify_archive` `plant_fit`
  policy gate, and `REX-20261024-01/02/03`), `#401` (synced in lockstep with `Roadmap.md`), and
  `#117` (protected under `not-this-cycle`, decision 2C `#627` prerequisite settled).

The repository's established investigation location is `03_Investigations/`.

```json
{
  "agorokh/ac-copilot-trainer#86": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 86,
    "issue_state": "open",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [],
    "block_id": "86-operator-smoke",
    "do_not_merge": true,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-86-pit-capture-smoke-<date>.md",
        "purpose": "Evidence node for pit-session Pocket Technician + Setup Exchange screen_capture receipts and 5-diff disposition",
        "status": "new",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "firmware/screen/src/ui/screen_ac_copilot.cpp",
        "purpose": "Only if operator elects to align items 1/3/4 of the 5 observed render differences vs esp32_rig.png at the next rig session",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_screen_simulator.py",
        "purpose": "Simulator gate regression if screen_ac_copilot.cpp changes",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/rig_launcher/app.py",
        "purpose": "Rebuild packaged Game Point EXE (--build-exe) if pit-session screen_capture runs via packaged launcher instead of source sidecar (EXE at 16068f3 predates PR #904 5e88fe9)",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "evidence_snapshot": {
      "signals_count": 4,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PR #891 54801e6 / firmware/screen/include/ui/screen_pocket_technician.h:PT_SETUP_NAME_MAX, screen_pocket_technician.cpp",
          "detail": "Fixed 51-char setup-name wrapping (PT_SETUP_NAME_MAX 96) and empty-SE state; flashed to COM6 and operator-confirmed on glass + Spa 911 GT3 R SE browse->apply (comments 6255725710, 6255873976).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/891"
        },
        {
          "kind": "merged-pr",
          "anchor": "PRs #904 5e88fe9 + #906 67e5fc7 / firmware/screen/src/main.cpp:screen_capture_begin, tools/ai_sidecar/server.py:_route_screen_capture, tools/screen_capture.py:capture",
          "detail": "Shipped on-device LVGL framebuffer capture over WebSocket and captured live AC Copilot screen mid-drive at Spa vs esp32_rig.png, surfacing 5 visual differences (comment 6260669420).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/904"
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #862 076361a / tools/ai_sidecar/csp_setup_exchange.py:SetupExchangeBroker + PR #858 5d6f218 simulator gate",
          "detail": "Native CSP Setup Exchange broker and mandatory pre-flash LVGL simulator remain active on main 145c07a.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/862"
        },
        {
          "kind": "gh-state",
          "anchor": "2026-11-10 body refresh applied + operator gate A4",
          "detail": "Reconciled #86 body header to 2026-11-10 (145c07a) adding PRs #891/#904/#906, Spa SE confirmation, and packaged Game Point EXE (16068f3) rebuild note; operator deferred the 5-diff visual call to the next rig session."
        }
      ],
      "counterevidence": [
        "Three hardware acceptance checkboxes remain unchecked in #86 body.",
        "Pit-session on-device screen_capture receipts for Pocket Technician setup.load (requires ac.isCarResetAllowed() in pits) and SE download->install->PT load remain pending alongside next-rig-session visual disposition on the 5 Copilot render differences."
      ],
      "remaining_acceptance": [
        "Next-rig-session operator visual call on the 5 observed Copilot screen differences vs esp32_rig.png (accept as-shipped vs fix items 1/3/4).",
        "Pit-session on-device screen_capture for Pocket Technician setup load and SE download->install->PT load at Spa (rebuild Game Point EXE first if using packaged launcher rather than source sidecar)."
      ],
      "scope_evolution": "Setup Exchange leg: proxy -> native CSP client (PR #862), operator-ratified 2026-10-16.",
      "drift_flags": [],
      "recommended_action": "keep open (body refreshed 2026-11-10); revisit 5-diff visual call and pit-session PT/SE screen_capture at next rig session.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#529": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 529,
    "issue_state": "open",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [],
    "block_id": "529-g1-policy-and-rex",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [
      {
        "path": "tools/ac_harness/ggv_profile.py",
        "purpose": "REX-20261024-01 (G1): row-level thermal probe eligibility in ggv_from_lap_archives / merge_selfplay_model",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ac_harness/auto_alien.py",
        "purpose": "REX-20261024-01 (G1): per-corner capability stepping instead of scalar ladder",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tests/test_auto_alien.py",
        "purpose": "Regression coverage for per-corner stepping and G1 ladder",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/lap_qualification.py",
        "purpose": "Policy compatibility gate: qualify_archive currently blocks authority='ai' archives from use='plant_fit' (must stay distinct from human reference promotion)",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/coachable_frontier.py",
        "purpose": "REX-20261024-03 (G3): multi-lap drill sequencer (#938 and #815 issue gates closed; awaits qualified human AC session archives)",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/driver_progression.py",
        "purpose": "REX-20261024-03 (G3): corner mastery state",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/coaching_ledger.py",
        "purpose": "REX-20261024-03 (G3): drill outcome ledger",
        "status": "exists",
        "scope": "remaining"
      },
      {
        "path": "tools/ai_sidecar/coaching/between_lap.py",
        "purpose": "REX-20261024-03 (G3): between-lap focus emission",
        "status": "exists",
        "scope": "remaining"
      }
    ],
    "evidence_snapshot": {
      "signals_count": 4,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PR #937 00bf871 + comment 6388233038 / tools/lap_qualification.py:qualify_archive",
          "detail": "2026-10-24 retained ks_mclaren_650_gt3 @ magione diagnostic (9 AC-valid laps, best 95.226 s vs TT P10 74.784 s, +27.33%, fit f19c614); surfaced policy blocker where qualify_archive rejects native harness authority='ai' archives for use='plant_fit'.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/937"
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #939 469e2b5 + comment 6388379995 / 03_Investigations/roadmap-expansion-2026-10-24.md",
          "detail": "Defined REX-20261024-01 (G1 thermal probe row filter + per-corner stepping) and REX-20261024-03 (G3 multi-lap drill sequencer).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/939"
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #940 274e004 (closing #938 / REX-20261024-02) + #815 closed 2026-11-10 (comment 6777499356)",
          "detail": "Both named issue gates on REX-20261024-03 (#938 and #815) are now closed; MOZA/legacy-unknown exports remain unpromoted, so G3 consumes qualified human AC session archives.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/940"
        },
        {
          "kind": "gh-state",
          "anchor": "2026-11-10 body refresh applied (operator gate A5)",
          "detail": "Removed stale 2026-10-13 not-this-cycle claim and recorded Oct 16/24 McLaren runs, qualify_archive plant_fit policy blocker, and REX-20261024-01/02/03 status."
        }
      ],
      "counterevidence": [
        "G1 (<=5% off TT top-10 in <=20 cold-start laps) and G3 (human multi-session delta shrink) remain unmet."
      ],
      "remaining_acceptance": [
        "Operator policy decision on native harness authority='ai' eligibility for use='plant_fit' (strictly separated from human reference promotion).",
        "G1 cold-start generalization (REX-20261024-01) and G3 human multi-session validation on qualified human AC archives (REX-20261024-03)."
      ],
      "drift_flags": [
        "policy-compatibility: tools/lap_qualification.py:qualify_archive blocks authority='ai' on use='plant_fit', stalling self-play refits until operator rules."
      ],
      "recommended_action": "keep open (body refreshed 2026-11-10); await operator policy ruling on authority='ai' use='plant_fit' and authorization for REX-20261024-01.",
      "main_sha": "145c07a"
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
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [
      {
        "path": "docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md",
        "purpose": "Mandatory durable twin of #401 body when any vertical state changes",
        "status": "exists",
        "scope": "metadata-only"
      }
    ],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "gh-state",
          "anchor": "2026-11-10 paired #401 body + docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md refresh",
          "detail": "Synced #401 and Roadmap.md in lockstep at main 145c07a to reflect #815 CLOSED (comment 6777499356), #534 CLOSED (comment 6777501131), #813 DISPOSITIONED (comment 6777498061), refreshed #86/#529 bodies, and the 4-issue open backlog (#86, #529, #401, #117).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/401"
        },
        {
          "kind": "merged-pr",
          "anchor": "PRs #917 6014792, #941 14ebaaf, #944 d881fb9",
          "detail": "Maintains continuous state-consistency pair chain across roadmap reconciliations.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/944"
        },
        {
          "kind": "label-events",
          "anchor": "unlabeled not-this-cycle 2026-10-21",
          "detail": "Active living roadmap umbrella."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [
        "Standing programme umbrella; keep #401 body and Roadmap.md synchronized whenever an owning issue changes state."
      ],
      "drift_flags": [],
      "recommended_action": "keep open; #401 body and Roadmap.md reconciled in lockstep on 2026-11-10.",
      "main_sha": "145c07a"
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
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [
      {
        "path": "firmware/arduino_fan_oled/platformio.ini",
        "purpose": "Only on explicit operator unpark",
        "status": "new",
        "scope": "parked-conditional-source"
      },
      {
        "path": "firmware/arduino_fan_oled/src/main.cpp",
        "purpose": "Fan PWM + SSD1306 tyre display reusing SerialPeer",
        "status": "new",
        "scope": "parked-conditional-source"
      },
      {
        "path": "firmware/arduino_fan_oled/README.md",
        "purpose": "Transport contract + electrical safety notes",
        "status": "new",
        "scope": "parked-conditional-source"
      },
      {
        "path": "tests/test_arduino_fan_oled_protocol.py",
        "purpose": "Protocol unit tests",
        "status": "new",
        "scope": "parked-conditional-source"
      }
    ],
    "conditional_files_to_touch": [
      {
        "path": "tools/ai_sidecar/car_class.py",
        "purpose": "Former #534 Part C per-class wind curve mapping if unparked (#534 comment 6777501131)",
        "status": "exists",
        "scope": "parked-conditional-source"
      }
    ],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "tree",
          "anchor": "firmware/ = {keypad, screen}; firmware/arduino_fan_oled absent; tools/ai_sidecar/serial_transport.py:SerialPeer + server.py:_build_haptic_events_from_telemetry present",
          "detail": "0 of 4 acceptance criteria delivered; host serial transport ready for reuse."
        },
        {
          "kind": "gh-state",
          "anchor": "#627 CLOSED 2026-10-19T06:29:20Z (PR #905 6574b15); #534 CLOSED 2026-11-10 assigning Part C wind curve to #117 (comment 6777501131); #117 retains not-this-cycle",
          "detail": "Decision 2C's #627 deferral prerequisite is settled, while not-this-cycle remains authoritative until the operator unparks #117."
        },
        {
          "kind": "vault",
          "anchor": "00_System/Roadmap.md",
          "detail": "Preserves not-this-cycle on #117 and records ownership of former #534 Part C wind curve if unparked."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [
        "All four hardware/firmware checkboxes (plus optional per-class wind curve from #534 Part C), strictly held behind operator-owned not-this-cycle."
      ],
      "drift_flags": [],
      "recommended_action": "keep protected under not-this-cycle.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#815": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 815,
    "issue_state": "closed",
    "closed_at": "2026-11-10T19:50:00Z",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-815",
    "do_not_merge": false,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 4,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PRs #921 612328d .. #934 1deb45d / tools/ai_sidecar/voice/live_acceptance.py:anticipatory_assessment, reverb_aware_completeness; tools/ac_harness/live_voice.py:CaptureSupervisor",
          "detail": "Run 07 (ks_porsche_911_gt3_r_2016 @ spa) achieved engineering_acceptance=PASS, failed_gates=[], 12/12 phrases complete, +-25.0 ms monotonic timebase, 2/2 brake leads (4773 ms / 2000 ms), byte-exact audio.ini restore (comment 6360080008).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/934"
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #944 d881fb9 / Clause 38 rendered-application-state verification",
          "detail": "Direct inspection across all 14 periodic HUD frames + hud.png passed; all 18/18 Part A-D checkboxes checked off in #815 body (comment 6435873172).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/944"
        },
        {
          "kind": "code-search",
          "anchor": "tools/moza_ingest/normalize.py:normalize_view, tools/lap_qualification.py:qualify_archive, tools/session_review/moza.py:build_moza_session_report, tools/ai_sidecar/voice/shadow_replay.py:build_shadow_replay",
          "detail": "Parts A-D code surfaces present and covered on main 145c07a."
        },
        {
          "kind": "issue-comment",
          "anchor": "closing disposition comment 6777499356 + body refresh (2026-11-10)",
          "detail": "Operator closed #815 (gate A1) on completed 18/18 Part A-D engineering, acoustic, and rendered-HUD PASS, explicitly retaining human_live_qualification = NOT_ESTABLISHED_BY_THIS_ENGINEERING_CAPTURE (processed MOZA caches stay inspection-only; MOZA/legacy-unknown/AI-assisted records stay unpromoted).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6777499356"
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "closed with explicit engineering-only boundary disposition (comment 6777499356); open a dedicated human-driving session issue if human_live_qualification is desired later.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#534": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 534,
    "issue_state": "closed",
    "closed_at": "2026-11-10T19:51:00Z",
    "last_verdict": "partially-delivered",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-534",
    "do_not_merge": true,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 4,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PRs #914 683c193 + #916 696292a / tools/simhub_car_enrichment/AcCopilot.CarEnrichment/AcCopilotDataPlugin.cs:AcCopilotDataPlugin",
          "detail": "Live SimHub 9.13.2 build/enable on the rig verified property-picker + NCalc readback (rear-engine-gt -> 1.15 on 911 GT3 R @ Magione; unknown -> 1 idle); all 3 Parts A+B checkboxes ticked [x] (comments 6329734691, 6330968961).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/916"
        },
        {
          "kind": "merged-pr",
          "anchor": "PRs #689 + #692 + #936 c5d1948 / tools/ai_sidecar/car_class.py, car_schema.py",
          "detail": "Car-class resolver and schema enrichment shipped on main; PR #936 recorded C/D/E hardware/operator gates.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/936"
        },
        {
          "kind": "tree",
          "anchor": "firmware/ contains only keypad/ and screen/",
          "detail": "Confirms Parts A+B live in tree and Part C peripheral remains parked under #117."
        },
        {
          "kind": "issue-comment",
          "anchor": "closing disposition comment 6777501131 + body refresh (2026-11-10)",
          "detail": "Operator refreshed split-brain prose and closed #534 (gate A2) on live-verified Parts A+B, recording Part C under parked #117 (not-this-cycle) and formally dropping/deferring Parts D (pedal haptics) and E (optional ShakeIt experiment).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6777501131"
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "closed with explicit Parts C/D/E disposition (comment 6777501131); zero Done-ghosts.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#627": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 627,
    "issue_state": "closed",
    "closed_at": "2026-10-19T06:29:20Z",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-627",
    "do_not_merge": true,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "issue-comment",
          "anchor": "closing comments 6261077162 + 6261143558 (2026-10-19)",
          "detail": "Closed by owner with Council 3-0 concurrence after PRs #877 (resilient_launch.REPORT_SCHEMA v6), #879 (probe_only), #884 (CLI-only Stable AC), and #898 (frame_hitch.lua + lap-metadata-index).",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-6261077162"
        },
        {
          "kind": "merged-pr",
          "anchor": "PR #905 6574b15 / 03_Investigations/issue-627-c2-settled-2026-10-19.md",
          "detail": "Durable C2 closure receipt on main; also resolved the comment-drift flagged in bdd6d5.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/905"
        },
        {
          "kind": "gh-state",
          "anchor": "#627 CLOSED completed 2026-10-19T06:29:20Z",
          "detail": "Confirmed via gh issue view."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "clean done; no action.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#938": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 938,
    "issue_state": "closed",
    "closed_at": "2026-10-25T05:31:57Z",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-938",
    "do_not_merge": false,
    "scope-evolution-accepted": false,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 2,
      "evidence": [
        {
          "kind": "merged-pr",
          "anchor": "PR #940 274e004 / tools/ai_sidecar/coaching_runtime.py:CoachRuntime, tools/ai_sidecar/telemetry_source.py, tests/test_coaching_runtime.py",
          "detail": "Delivered REX-20261024-02 live capability-gated corner coaching and honest degraded status; 1:1 clean close alongside #881/#885/#889/#893/#895/#897/#901.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/940"
        },
        {
          "kind": "gh-state",
          "anchor": "#938 CLOSED completed 2026-10-25T05:31:57Z",
          "detail": "Confirmed via gh issue list --state closed."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "clean done; no action.",
      "main_sha": "145c07a"
    }
  },
  "agorokh/ac-copilot-trainer#813": {
    "repo": "agorokh/ac-copilot-trainer",
    "number": 813,
    "issue_state": "closed",
    "closed_at": "2026-10-15T01:43:36Z",
    "last_verdict": "live",
    "confidence": "high",
    "group_with": [],
    "block_id": "closed-813",
    "do_not_merge": true,
    "scope-evolution-accepted": true,
    "board_move": null,
    "run_ts": "2026-11-10T19:55:00+00:00",
    "run_id": "c4a91e",
    "files_to_touch": [],
    "conditional_files_to_touch": [],
    "evidence_snapshot": {
      "signals_count": 3,
      "evidence": [
        {
          "kind": "timeline",
          "anchor": "closed 2026-10-15T01:43:36Z via PR #848 closingIssuesReferences=[813]; PR #849 autonomous P7 evidence on #531",
          "detail": "Previously carried-forward linkage auto-close exception from bdd6d5.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/pull/849"
        },
        {
          "kind": "issue-comment",
          "anchor": "closing disposition comment 6777498061 (2026-11-10)",
          "detail": "Owner dispositioned #813 (gate A3): accepted #531 / PR #849 autonomous P7 evidence alongside PR #814 (b513d05) and #819, formally waiving the separate human-driven P7 valid-lap and automatic menu-exit stale-transition checks.",
          "url": "https://github.com/agorokh/ac-copilot-trainer/issues/813#issuecomment-6777498061"
        },
        {
          "kind": "vault",
          "anchor": "00_System/Roadmap.md + #401 body (updated 2026-11-10)",
          "detail": "Records #813 as CLOSED and DISPOSITIONED, clearing the carried-forward Done-ghost."
        }
      ],
      "counterevidence": [],
      "remaining_acceptance": [],
      "drift_flags": [],
      "recommended_action": "clean dispositioned close (comment 6777498061); Done-ghost resolved.",
      "main_sha": "145c07a"
    }
  }
}
```
