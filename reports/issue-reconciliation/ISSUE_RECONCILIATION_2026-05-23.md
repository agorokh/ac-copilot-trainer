# Issue Reconciliation Report - 2026-05-23

Repository: `agorokh/ac-copilot-trainer`  
Default branch audited: `main` at `origin/main` (`d96cddc`, fetched before audit)  
Audit branch: `chore/issue-reconciliation-20260523`  
GitHub write mode: initially disabled for the audit; enabled by user approval after the epic-retirement addendum. GitHub actions were applied on 2026-05-23 and are listed below.

## Executive Summary

Total open issues reviewed: 5

| Classification | Count |
|---|---:|
| Verified complete | 0 |
| Complete but needs housekeeping | 0 |
| Partially implemented | 3 |
| Duplicate | 0 |
| Superseded / obsolete | 0 |
| Not implemented | 2 |
| Unverifiable | 0 |

Ordinary feature reconciliation found no fully implemented open issue. Epic retirement mode changed the governance recommendation for the broad parents: `#5` was retired as mostly completed; `#19` and `#59` were split/replaced by narrower current issues; `#86` stayed open after rewriting the body to the remaining Parts E-F/font/external-bind/device-smoke scope. Issue `#79` is explicitly not implemented: PR `#78` only made the lap archive schema forward-compatible for imported laps.

Post-action open issue set: `#79`, `#86`, and successors `#114`-`#118`. Successors `#119` and `#120` were later closed as dropped physical-only scope.

## Issue Table

| Issue | Title | Classification | Confidence | Action Taken | Evidence Summary |
|---|---|---|---|---|---|
| #5 | EPIC: AC Copilot Trainer - AI driving coach for Assetto Corsa | C ordinary; epic disposition: close mostly completed with successors | High | Closed with reconciliation comment | Issue body checks off Phases 1-3. Remaining Phase 4 work was split into `#114`, `#115`, `#116`. |
| #19 | Advanced AI: Bayesian setup optimizer, RL optimal laps, community sharing, MoTeC export | F ordinary; epic disposition: split and replace | High | Closed with reconciliation comment; created `#114`-`#116` | No `tools/ai_sidecar/setup/`, no `tools/rl_training/`, no MoTeC/CSV exporter module. Community sharing was dropped by owner decision. |
| #59 | [EPIC] Physical Rig Integration - Hardware Peripherals for Sim Cockpit | C ordinary; epic disposition: split and replace | High | Closed with reconciliation comment; created `#117`-`#120`; then closed `#119`/`#120` as dropped | ESP32/screen scope lives in `#86`; only Arduino fan/OLED and protocol boundary remain active as `#117`/`#118`. |
| #79 | feat(initiative B): MoTeC CSV reference-lap import - ingest external / pro-driver laps into bestLapTrace | F. Not implemented | High | Commented; left open | No `tools/import_motec/`, no `tests/test_import_motec.py`, no `tests/test_reference_activation.py`, no `useImportedReference` setting. PR `#78` explicitly deferred Initiative B. |
| #86 | [EPIC] Rig screen Phase-2 UI - App launcher + AC Copilot / Pocket Technician / Setup Exchange | C ordinary; epic disposition: keep open but rewrite scope | High | Body rewritten and reconciliation comment added; left open | PR `#91` merged Parts A-D; PR `#100` fixed PT chip refresh; remaining scope is Parts A4/E/F, external-bind/token, and device smoke. |

## Detailed Evidence Per Issue

### Issue #5 - EPIC: AC Copilot Trainer

Classification: C. Partially implemented  
Confidence: High

Primary goal: deliver the full AC Copilot Trainer vision across foundation, analysis, coaching, and Phase 4 advanced AI.

Requirement Matrix:

| Requirement | Status | Evidence |
|---|---|---|
| REQ-5-001 Phase 1 foundation: telemetry, brake/throttle detection, persistence, 3D markers, live delta/approach HUD | Complete | Issue body checks off `#6` and `#7`; current code includes `src/ac_copilot_trainer/modules/telemetry.lua`, `brake_detection.lua`, `throttle_detection.lua`, `track_markers.lua`, `delta.lua`. |
| REQ-5-002 Phase 2 analysis/comparison: corner analysis, consistency, AI spline/racing line/tire/setup tracking | Complete | Issue body checks off `#8`; current code includes `corner_analysis.lua`, `racing_line.lua`, `tire_monitor.lua`, `setup_reader.lua`; timeline cross-references closed `#48`. |
| REQ-5-003 Phase 3 coaching/intelligence: ML-ranked coaching, sidecar/LLM, focus practice, journal | Complete | Issue body checks off `#9` and children `#43`, `#45`, `#49`, `#46`, `#47`, `#44`; timeline cross-references closed `#9`, `#44`, `#49`, `#57`, and merged PR `#64`. |
| REQ-5-004 Phase 4: setup optimizer converges in 10-20 runs and RL reference laps available | Missing | Issue body explicitly leaves `#19` unchecked. See `#19` findings below: requested optimizer/RL/export/community modules are not present. |

GitHub / PR Evidence Checked:

- Issue body: yes.
- Issue comments: yes, 0.
- Timeline/cross-references: yes, 9 timeline rows: 7 cross-references, 1 label event, 1 commit reference.
- Related PRs inspected: `#64` as Phase 5 final HUD PR; recent PR list also inspected.
- Review comments inspected: not material for open `#5`; no direct active PR remains.
- Bot comments inspected: not material for open `#5`; no direct active PR remains.
- Comments after last commit inspected: not applicable.
- CI/checks inspected: not applicable to this umbrella issue; child PR evidence was used only as scope context.

Code Evidence Checked:

- Files: `src/ac_copilot_trainer/modules/telemetry.lua`, `brake_detection.lua`, `corner_analysis.lua`, `racing_line.lua`, `realtime_coaching.lua`, `tools/ai_sidecar/improvement_ranking.py`, `tools/session_journal.py`.
- Tests: focused command below; confirms current issue-related test surface selected for this audit, with dependency-gated skips.
- Docs/config/migrations: issue body, `docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md`.

Decision: close as mostly completed with successor issue `#19` if GitHub writes are later allowed. `#5` is no longer the right current work item because the remaining material scope is already represented by narrower open issue `#19`.

Remaining Work:

- [ ] Complete or descope Phase 4 via `#19`.
- [ ] Add a closure comment to `#5` preserving traceability to the completed phases and open successor `#19`.

Suggested GitHub comment:

```markdown
Issue Reconciliation Result: CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES

Summary:
- Phases 1-3 are represented as complete in the issue body and have corresponding code/closed child issue evidence on `main`. The only material remaining scope is Phase 4, already tracked by open successor issue #19, so keeping this broad parent open no longer improves execution.

Requirement Matrix:
| Requirement | Status | Evidence |
|---|---|---|
| REQ-5-001 Phase 1 foundation | Complete | Issue body checks #6/#7; current modules include telemetry/brake/throttle/track marker/delta code |
| REQ-5-002 Phase 2 analysis | Complete | Issue body checks #8; current modules include corner_analysis/racing_line/tire/setup tracking |
| REQ-5-003 Phase 3 coaching | Complete | Issue body checks #9 and children; timeline references closed #9/#44/#49/#57 and merged PR #64 |
| REQ-5-004 Phase 4 advanced AI | Split/replaced | #19 was closed and replaced by `#114`, `#115`, and `#116`; optimizer/RL/MoTeC work is not on main and community sharing was dropped |

Decision:
- Close as mostly completed with successor issue #19.
```

### Issue #19 - Advanced AI

Classification: F. Not implemented  
Confidence: High

Primary goal: add proactive optimization via setup experiments, Bayesian optimizer, RL reference laps, CSV/MoTeC export, and community sharing.

Requirement Matrix:

| Requirement | Status | Evidence |
|---|---|---|
| REQ-19-001 Setup experiment framework: setup params + lap telemetry + conditions, A/B testing, statistical significance, setup history dashboard | Missing | No `tools/ai_sidecar/setup/`; `rg` found only lap archive/session journal exports, not experiment tracking or significance tests. |
| REQ-19-002 Bayesian setup optimizer using scikit-optimize GP acquisition and context encoding | Missing | `rg` found no `skopt`, `scikit-optimize`, setup optimizer module, or optimizer tests. |
| REQ-19-003 RL optimal lap generation via assetto_corsa_gym/SAC and TUMFTM alternative | Missing | No `tools/rl_training/`, no `assetto_corsa_gym`, no `stable_baselines`, no RL trace import path. |
| REQ-19-004 Data export: CSV, MoTeC i2-compatible format, adaptive learning rate stats | Missing | Existing `lap_archive.lua` writes JSON archive only; no `src/ac_copilot_trainer/modules/export.lua` and no MoTeC writer. |
| REQ-19-005 Community sharing: anonymous brake maps, reference lap CSV import, progressive targets | Dropped | No community import/export module or UI exists; owner decision during reconciliation was to drop this scope rather than create a successor issue. `#79` separately tracks local MoTeC CSV reference import. |

GitHub / PR Evidence Checked:

- Issue body: yes.
- Issue comments: yes, 0.
- Timeline/cross-references: yes, 8 timeline rows: 6 cross-references, 1 label event, 1 commit reference.
- Related PRs inspected: no merged PR directly implements `#19`; PR `#78` is related only as data-foundation work and explicitly defers MoTeC importer.
- Review comments inspected: not applicable; no related implementation PR.
- Bot comments inspected: not applicable; no related implementation PR.
- Comments after last commit inspected: not applicable.
- CI/checks inspected: not applicable; no related implementation PR.

Code Evidence Checked:

- Files searched: `src/`, `tools/`, `tests/`, `docs/`, `README.md`.
- Tests: no `#19` tests found.
- Docs/config/migrations: no optimizer/RL/community/MoTeC implementation docs found beyond future references.

Decision: ordinary reconciliation says leave open because the behavior is not implemented. Epic retirement mode says split and replace this roadmap issue with narrower successor issues because the combined Phase 4 scope is not an executable work item.

Remaining Work:

- [ ] Create setup experiment tracker under the intended setup-sidecar area.
- [ ] Add Bayesian optimizer and tests.
- [ ] Add RL/TUMFTM reference-lap generation or explicitly move it to stretch/out-of-scope.
- [ ] Add CSV/MoTeC export path and tests.
- [x] Drop community sharing/import/export scope; no successor issue created.

Suggested GitHub comment:

```markdown
Issue Reconciliation Result: NOT IMPLEMENTED

Summary:
- I could not find code on `main` for the requested setup experiment framework, Bayesian optimizer, RL reference lap generation, CSV/MoTeC export, or community sharing. Existing lap archival is useful foundation work, but it is JSON archive/persistence, not the Phase 4 feature set requested here.

Decision:
- Leave open until successor issues are created, then close as split/replaced per the epic retirement section.

Remaining Work:
- [ ] Setup experiment tracker + statistical A/B tests
- [ ] Bayesian setup optimizer
- [ ] RL/TUMFTM reference lap generation/import
- [ ] CSV/MoTeC export
- [x] Community sharing/import/export dropped by owner decision
```

### Issue #59 - Physical Rig Integration

Classification: C. Partially implemented  
Confidence: High

Primary goal: integrate physical rig peripherals: Arduino UNO fan/OLED/haptics, ESP32 dashboard, bass shaker, side bolster motors, pedal haptics, and native sidecar routing.

Requirement Matrix:

| Requirement | Status | Evidence |
|---|---|---|
| REQ-59-001 ESP32 dashboard/client foundation | Partial / complete for screen foundation | `firmware/screen/platformio.ini:52-61` pins Arduino_GFX, ArduinoWebsockets, ArduinoJson, LVGL; `tools/ai_sidecar/external_protocol.py:22-45` defines external frame types; PR `#83` and PR `#91` merged screen/client work. |
| REQ-59-002 Python sidecar multi-client routing | Partial | `tools/ai_sidecar/server.py:267-325` validates external frames, requires loopback Lua peer, and broadcasts to other peers. No hardware haptic routing/events exist. |
| REQ-59-003 Lua `ws_bridge.lua` emits `telemetry_tick`, setup list/apply, haptic events | Partial | `ws_bridge.publishTopic` and `setup.list`/`setup.load` handlers exist (`ws_bridge.lua:915-947`, `ac_copilot_trainer.lua:430-520`), but `rg` found no `telemetry_tick`, `haptic_event`, `setup_select`, or `setup_applied` protocol. |
| REQ-59-004 Arduino UNO fan/OLED/vibration/pedal firmware | Missing | No Arduino UNO firmware component was found under `firmware/`; only `firmware/screen/` exists. |
| REQ-59-005 ESP32 live telemetry, tyre heatmap, setup selector, coaching summary | Partial | Pocket Technician setup selector and AC Copilot mirror exist (`screen_pocket_technician.cpp`, `screen_ac_copilot.cpp`), but live telemetry/tyre heatmap/coaching-summary dashboard from `#59` is out-of-scope in `#86` and not implemented. |
| REQ-59-006 Bass shaker/side bolster/pedal haptics native stack without SimHub dependency | Missing | No `haptic_event` code path, no Arduino haptic firmware, and no native bass-shaker output implementation found. |
| REQ-59-007 3D enclosure / FDM mount deliverables | Missing | No enclosure model or print artifact paths found. |

GitHub / PR Evidence Checked:

- Issue body: yes.
- Issue comments: yes, 0.
- Timeline/cross-references: yes, 4 timeline rows: PR `#85`, issue `#86`, and commit reference `7b95135`.
- Related PRs inspected: `#85` vault enrichment; `#91` and `#100` through related issue `#86`; PR `#83` from recent merged list as screen foundation.
- Review comments inspected: `#85` review summaries/comments; `#91` review threads; `#100` ledger comments.
- Bot comments inspected: CodeRabbit/Qodo/Copilot/Bugbot on `#85`, `#91`, `#100`.
- Comments after last commit inspected: `#100` included explicit post-watermark audit comments; `#91` review threads all resolved.
- CI/checks inspected: `#85`, `#91`, `#100` check rollups.

Code Evidence Checked:

- Files: `firmware/screen/platformio.ini`, `firmware/screen/src/main.cpp`, `tools/ai_sidecar/external_protocol.py`, `tools/ai_sidecar/server.py`, `src/ac_copilot_trainer/modules/ws_bridge.lua`, `src/ac_copilot_trainer/ac_copilot_trainer.lua`.
- Tests: `python3.11 -m pytest -q tests/test_setup_library_summary.py tests/test_ai_sidecar_external.py tests/test_ai_sidecar_protocol.py tests/test_design_conformance.py` -> 32 passed, 5 skipped (missing `lupa`, `websockets`).
- Docs/config/migrations: `docs/01_Vault/AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md` from PR `#85`; `Next Session Handoff.md`.

Decision: ordinary reconciliation says leave open because material hardware work is incomplete. Epic retirement mode says split and replace because the remaining active Arduino and protocol work can be expressed as narrower current issues and `#86` already owns the screen slice.

Remaining Work:

- [ ] Implement `telemetry_tick` and physical-peripheral event protocol if still desired.
- [ ] Add Arduino UNO firmware for fan/OLED telemetry.
- [x] Drop side bolster/pedal haptics as physical-only scope.
- [ ] Complete live telemetry/tyre dashboard and coaching-summary screen if it remains in this epic.
- [x] Drop enclosure/mount artifacts as physical-only fabrication scope.

Suggested GitHub comment:

```markdown
Issue Reconciliation Result: PARTIALLY IMPLEMENTED

Summary:
- The ESP32/sidecar screen foundation has landed through PR #83/#91 and follow-up PR #100, but the issue's Arduino UNO fan/OLED and telemetry/peripheral protocol acceptance criteria are not complete on main. Side bolster/pedal haptics and enclosure artifacts were dropped after successor issues were created.

Decision:
- Split and replace with narrow hardware/peripheral successor issues.

Remaining Work:
- [ ] Arduino UNO fan/OLED firmware
- [ ] telemetry_tick / physical-peripheral event protocol
- [ ] Live telemetry / tyre dashboard pieces not covered by #86
- [x] Side bolster/pedal haptics dropped
- [x] Enclosure/mount artifacts dropped
```

### Issue #79 - MoTeC CSV Reference-Lap Import

Classification: F. Not implemented  
Confidence: High

Primary goal: ingest MoTeC CSV reference laps into the lap archive and optionally activate them as `bestLapTrace`.

Requirement Matrix:

| Requirement | Status | Evidence |
|---|---|---|
| REQ-79-001 Python importer at `tools/import_motec/` with CLI | Missing | `rg --files` shows no `tools/import_motec/`; `rg "import_motec|motec"` found only schema comments/docs. |
| REQ-79-002 Column heuristic mapping, normalization, multi-lap CSV split, resample to 2000 samples | Missing | No importer code or tests exist. |
| REQ-79-003 Emit schema-v1 imported lap JSON with `source="imported"` / `import_format="motec_csv"` | Missing | `lap_archive.lua:1-15` reserves schema fields for future imports, but current lap writes are in-game archive writes at `ac_copilot_trainer.lua:1970-1988`; no importer emits imported records. |
| REQ-79-004 Reference-lap activation in `persistence.lua` / best trace | Missing | `rg "useImportedReference|lap_imported|source=\"imported\""` found no activation flag or loader. |
| REQ-79-005 Settings UI reference-lap section | Missing | No `Reference lap` settings UI or folder button found. |
| REQ-79-006 Tests `test_import_motec.py` and `test_reference_activation.py` | Missing | No such test files exist. |

GitHub / PR Evidence Checked:

- Issue body: yes.
- Issue comments: yes, 0.
- Timeline/cross-references: yes, 1 label event, no related PR references.
- Related PRs inspected: PR `#78` because issue body says it shipped the schema; PR `#78` body explicitly lists Initiative B MoTeC importer as out of scope/future.
- Review comments inspected: PR `#78` reviews/comments reviewed as foundation context.
- Bot comments inspected: PR `#78` CodeRabbit/Copilot/Bugbot review summaries inspected as foundation context.
- Comments after last commit inspected: PR `#78` was only foundation; no implementation PR for `#79`.
- CI/checks inspected: PR `#78` had CI/checks green for its own scope, not `#79`.

Code Evidence Checked:

- Files: `src/ac_copilot_trainer/modules/lap_archive.lua:1-15`, `src/ac_copilot_trainer/ac_copilot_trainer.lua:1970-1988`, `src/ac_copilot_trainer/modules/persistence.lua`, `src/ac_copilot_trainer/modules/hud_settings.lua`, `tools/`.
- Tests: no `#79` tests found.
- Docs/config/migrations: `docs/01_Vault/AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md` states MoTeC CSV import is future scope.

Decision: leave open. This is not implemented on `main`.

Remaining Work:

- [ ] Add `tools/import_motec/` CLI importer.
- [ ] Add column mapping/resampling/normalization/multi-lap handling.
- [ ] Emit schema-v1 imported lap JSON.
- [ ] Implement reference activation with `useImportedReference` guard.
- [ ] Add Settings UI reference-lap controls.
- [ ] Add importer and activation tests.

Suggested GitHub comment:

```markdown
Issue Reconciliation Result: NOT IMPLEMENTED

Summary:
- The schema foundation from PR #78 is present, but the actual MoTeC CSV importer, imported-reference activation, Settings UI controls, and tests requested by this issue are not present on `main`. PR #78 explicitly treated Initiative B / MoTeC import as future scope.

Decision:
- Leave open.

Remaining Work:
- [ ] `tools/import_motec/` CLI
- [ ] Column heuristic mapping + 2000-sample resampling
- [ ] Imported lap JSON emission
- [ ] `useImportedReference` activation path
- [ ] Settings UI reference-lap section
- [ ] `tests/test_import_motec.py` and `tests/test_reference_activation.py`
```

### Issue #86 - Rig Screen Phase-2 UI

Classification: C. Partially implemented  
Confidence: High

Primary goal: deliver LVGL launcher, AC Copilot mirror, Pocket Technician custom setup picker, Setup Exchange browser, and integration/polish for the JC3248W535 rig screen.

Requirement Matrix:

| Requirement | Status | Evidence |
|---|---|---|
| REQ-86-001 Part A LVGL 8.3, touch reader, canvas flush, navigator, design tokens | Partial / mostly complete | `firmware/screen/platformio.ini:52-61`, `firmware/screen/include/board/JC3248W535_Touch.h`, `firmware/screen/src/main.cpp`, and PR `#91`. Part A4 font conversion remains undone per `Next Session Handoff.md:57-61`. |
| REQ-86-002 Part B launcher screen | Complete | `firmware/screen/src/ui/screen_launcher.cpp:347-355` builds three app tiles; header/status pill at `252-303`; PR `#91` merged. |
| REQ-86-003 Part C AC Copilot mirror with `coaching.snapshot` + `corner_advice` | Complete / needs hardware smoke | `coaching_publisher.lua:1-23`, `125-141`; `ws_bridge.lua:915-947`; `screen_ac_copilot.cpp:1-30`, `85-140`. |
| REQ-86-004 Part D Pocket Technician setup picker, `setup.list`/`setup.load`, pits gate, PT sync | Complete / needs hardware smoke | `setup_library.lua:82-173`, `198-322`; `ac_copilot_trainer.lua:430-520`; `external_protocol.py:29-45`, `135-149`; PR `#100` fixed PT row BB chip refresh. |
| REQ-86-005 Part E Setup Exchange browser/proxy/cache/download/install | Missing | No `tools/ai_sidecar/se_proxy.py`; no `se.search`, `se.download`, `setup.install` protocol code found. |
| REQ-86-006 Part F integration/polish: SPIFFS persistence, offline cache, debug tap, token rotation, sustained 60 Hz device validation | Partial / missing | Some state handling exists, but `Next Session Handoff.md:57-61` lists Parts E-F and debug/polish work as remaining. No on-device final smoke artifact found. |
| REQ-86-007 Security constraints: token gitignored and external bind/token path | Partial | `firmware/screen/secrets/sidecar.h.example` exists; `Next Session Handoff.md:57-60` says `start_sidecar.bat` still needs `--external-bind 0.0.0.0` + token path. |
| REQ-86-008 Acceptance tests/checks | Partial | Focused pytest command: 32 passed, 5 skipped due missing `lupa`/`websockets`. PR `#91` CI `build` green; PR `#100` CI `build` green. Firmware compile is not wired into CI per PR `#91` body. |

GitHub / PR Evidence Checked:

- Issue body: yes.
- Issue comments: yes, 0.
- Timeline/cross-references: yes, 14 timeline rows: 6 cross-references, 4 labels, 4 commit references.
- Related PRs inspected: `#87`, `#91`, `#92`, `#94`, `#100`, `#112`; `#83` and `#78` inspected as foundation links from the issue.
- Review comments inspected: PR `#91` GraphQL review threads; PR `#100` comment ledger; PR `#85`/`#78` review summaries as foundation context.
- Bot comments inspected: CodeRabbit, Copilot, Gemini, Bugbot/Cursor, Qodo, Sourcery where present.
- Comments after last commit inspected: PR `#91` threads all resolved; PR `#100` has explicit post-watermark zero-sampling audit comments and green checks.
- CI/checks inspected: PR `#91` check rollup (`build` success, policy success, post-merge classification success; PR pain score failure noted as non-merge functional signal); PR `#100` check rollup (`build` success, policy success, Bugbot/CodeRabbit success).

Code Evidence Checked:

- Files: `firmware/screen/platformio.ini`, `firmware/screen/src/main.cpp`, `firmware/screen/src/ui/screen_launcher.cpp`, `screen_ac_copilot.cpp`, `screen_pocket_technician.cpp`, `src/ac_copilot_trainer/modules/coaching_publisher.lua`, `ws_bridge.lua`, `setup_library.lua`, `tools/ai_sidecar/external_protocol.py`, `tools/ai_sidecar/server.py`.
- Tests: `python3.11 -m pytest -q tests/test_setup_library_summary.py tests/test_ai_sidecar_external.py tests/test_ai_sidecar_protocol.py tests/test_design_conformance.py` -> 32 passed, 5 skipped (`lupa`, `websockets` missing).
- Docs/config/migrations: `docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md:45-63` records Parts A-D merged and remaining work.

Decision: leave open. Reduce scope to remaining Parts E-F plus font/external-bind/device-smoke work.

Remaining Work:

- [ ] Part E: Setup Exchange screen and sidecar proxy (`se_proxy.py`, `se.search`, `se.download`, install/load flow).
- [ ] Part F: SPIFFS persistence, SE offline cache, debug screen, telemetry backpressure proof, token rotation runbook.
- [ ] Part A4: run/commit LVGL font conversion outputs or document why generated fonts remain local-only.
- [ ] Update `start_sidecar.bat` / sidecar startup for external bind + token path.
- [ ] Perform final on-device smoke: launcher -> AC Copilot -> PT setup load; record/attach proof.

Suggested GitHub comment:

```markdown
Issue Reconciliation Result: PARTIALLY IMPLEMENTED

Summary:
- PR #91 put issue #86 Parts A-D on `main`, and PR #100 fixed a related Pocket Technician stale-chip bug. The issue should stay open because Part E (Setup Exchange), Part F polish, LVGL font conversion, external-bind/token startup, and final on-device smoke remain.

Requirement Matrix:
| Requirement | Status | Evidence |
|---|---|---|
| Part A LVGL/touch/framework | Partial | PR #91; platformio/LVGL/touch/nav/tokens present; A4 font conversion still remaining |
| Part B launcher | Complete | `firmware/screen/src/ui/screen_launcher.cpp` |
| Part C AC Copilot mirror | Complete / smoke pending | `coaching_publisher.lua`, `ws_bridge.publishTopic`, `screen_ac_copilot.cpp` |
| Part D Pocket Technician | Complete / smoke pending | `setup_library.lua`, `setup.list`/`setup.load`, pits gate; PR #100 chip refresh |
| Part E Setup Exchange | Missing | No `se_proxy.py`, `se.search`, `se.download`, or install flow |
| Part F polish/integration | Partial | `Next Session Handoff.md` lists Parts E-F/debug/polish as remaining |

Decision:
- Leave open with reduced scope to Parts E-F + font/external-bind/smoke follow-up.
```

## Drift Patterns Found

- Large issue consumed by smaller PR chain: `#86` was partially consumed by PR `#91`, then PR `#100` fixed a post-merge screen defect. The parent issue did not receive a scope-reduction comment.
- Foundation PR mistaken risk: `#78` created imported-lap-compatible schema fields, but `#79` still needs the actual importer/activation. Code presence would be weak evidence here without the CLI and tests.
- Epic overlap: `#59` and `#86` overlap on ESP32 screen work, but `#59` is broader hardware/peripheral scope. They are not duplicates.
- Vault contains clearer remaining scope than the issue: `Next Session Handoff.md` precisely lists the remaining `#86` work while GitHub issue body still shows all original unchecked acceptance items.
- Bot/review comments resolved in PRs but not issue-linked: PR `#91` has all review threads resolved and PR `#100` has a zero-sampling audit, but issue `#86` lacks a reconciliation summary.

## Recommended Cleanup

Safe immediate cleanup:

- Completed: `#5` closed as mostly completed with successors `#114`-`#116`.
- Completed: `#19` closed as split/replaced by `#114`, `#115`, and `#116`; community sharing was dropped.
- Completed: `#59` closed as split/replaced by `#117`, `#118`, `#119`, and `#120`; `#119` and `#120` were then closed as dropped physical-only scope.
- Completed: `#86` body rewritten to current Parts A4/E/F scope and commented.
- Completed: `#79` commented as not implemented and left open.

Needs user decision:

- None for this reconciliation pass. Owner decision applied: drop community sharing from `#19`; commit generated LVGL font outputs required by `#86`.

Needs implementation:

- `#114`: setup experiment tracking and Bayesian setup suggestions.
- `#115`: archived-lap CSV/MoTeC-compatible export.
- `#116`: RL/TUMFTM reference-lap decision/prototype.
- `#79`: MoTeC CSV importer, activation, UI, and tests.
- `#117`: Arduino fan/OLED peripheral.
- `#118`: telemetry and haptic event protocol.
- Dropped: `#119` side bolster and pedal haptics.
- Dropped: `#120` rig enclosure and mount artifacts.
- `#86`: Setup Exchange and Part F polish/smoke.

Needs repo-process improvement:

- Add a post-merge issue reconciliation checklist for epic PRs that intentionally implement only a subset of acceptance criteria.
- Add firmware compile or at least PlatformIO dependency check to CI once the LVGL path is stable enough for CI.

## Epic Retirement / Transformation Analysis

| Epic | Original Intent | Current Reality | Delivered % Estimate | Residual Scope | Council Consensus | Recommended Action |
|---|---|---|---:|---|---|---|
| `#5` | Full AC Copilot Trainer across telemetry, analysis, coaching, and advanced AI | Phases 1-3 are delivered through closed children and merged PRs; Phase 4 was split into `#114`-`#116` | 80-90% | Successors `#114`-`#116` | Gemini + Mistral + primary reviewer agree | Closed as mostly completed with successors |
| `#19` | Phase 4 advanced AI roadmap: experiments, Bayesian optimizer, RL, export, community sharing | No implementation exists beyond forward-compatible archive fields; issue spans unrelated domains | 0-5% | `#114`, `#115`, `#116`; community sharing dropped | Gemini + Mistral + primary reviewer agree on split/replace | Closed as split/replaced |
| `#59` | Physical rig hardware layer: Arduino, ESP32, bass shaker, haptics, enclosure, no-SimHub stack | ESP32 screen path moved into `#86`; bass shaker became SimHub/live-config docs; side bolster/pedal/enclosure scope was dropped | 25-35% | Active successors `#117` and `#118`; dropped successors `#119`/`#120` | Gemini + Mistral + primary reviewer agree | Closed as split/replaced, then dropped physical-only successors |
| `#86` | Production rig screen UI: LVGL launcher, AC Copilot, Pocket Technician, Setup Exchange, polish | Parts A-D merged in PR `#91`; PT chip fix in PR `#100`; Parts E-F/font/external-bind/device-smoke remain | 65-75% | Coherent screen remainder | Gemini + Mistral + primary reviewer agree | Kept open with rewritten scope |

### Council Availability

Actual model council was partially available. Gemini and Mistral were invoked with the evidence packet. A separate GPT-family external reviewer and repo-specific subagent were not exposed in this environment; the GPT-family review below is the primary-agent adversarial synthesis, not a separate external tool.

Council synthesis:

- Consensus: retire `#5`, split/replace `#19`, split/replace `#59`, keep/rewrite `#86`.
- Disagreements: Mistral marked `#19` confidence Medium because product relevance still needs confirmation; Gemini and primary reviewer treated the breadth itself as enough to split.
- Evidence gaps: runtime/hardware validation is unavailable from this macOS worktree; RL product priority is not encoded in code.
- Resolution: split `#19` into narrow successor issues, keep RL decision-first, and drop community sharing per owner decision.

MODEL_REVIEW:

- Model: Gemini
- Recommendation: `#5` close mostly completed with successor issues; `#19` split and replace; `#59` split and replace; `#86` keep open but rewrite scope.
- Confidence: High
- Requirements complete: `#5` Phases 1-3; `#59` initial ESP32 screen foundation and pragmatic bass-shaker path; `#86` Parts A-D.
- Requirements remain: `#19` all core Phase 4 work; `#59` Arduino fan/OLED and protocol boundary only after dropping physical-only haptics/enclosure; `#86` Parts E-F/font/external-bind/smoke.
- Requirements obsolete: pure no-SimHub bass-shaker stack in `#59` appears obsolete after Phase 1R/SimHub live config.
- Evidence relied on: closed child issues/PRs, code searches, `Next Session Handoff.md`, `Current Focus.md`, PR `#91`, PR `#100`.
- Evidence gaps: whether Arduino haptic work is abandoned or merely delayed.
- Suggested successor issues: `#19`; new Bayesian/setup, RL reference lap, MoTeC/CSV export, Arduino/haptic successors.

MODEL_REVIEW:

- Model: Mistral
- Recommendation: `#5` close mostly completed with successor issues; `#19` split and replace; `#59` split and replace; `#86` keep open but rewrite scope.
- Confidence: High for `#5`, `#59`, `#86`; Medium for `#19`.
- Requirements complete: `#5` Phases 1-3; `#59` bass shaker/Stream A; `#86` Parts A-D.
- Requirements remain: `#19` setup experiments, optimizer, RL, export; `#59` Arduino and protocol boundary only after dropping haptics/enclosure; `#86` Parts E-F.
- Requirements obsolete: some `#59` work handled by Stream A.
- Evidence relied on: issue/PR states, code contents, Current Focus and handoff docs.
- Evidence gaps: exact remaining relevance of `#19` subfeatures and `#59` Phase 3b/4.
- Suggested successor issues: split `#19` by major component; split `#59` into Arduino/haptic/protocol issues.

MODEL_REVIEW:

- Model: GPT-family primary agent reviewer
- Recommendation: `#5` close mostly completed with successor `#19`; `#19` split and replace; `#59` split and replace; `#86` keep open but rewrite scope.
- Confidence: High
- Requirements complete: code-backed Phases 1-3 for `#5`; PR-backed screen Parts A-D for `#86`; partial ESP32 foundation for `#59`.
- Requirements remain: all `#19` advanced AI implementation; `#59` native hardware/haptic stack; `#86` Setup Exchange/polish/font/external-bind/device proof.
- Requirements obsolete: `#5` as a parent coordination object; `#59` as a single all-hardware epic; native no-SimHub bass-shaker requirement unless product reaffirms it.
- Evidence relied on: GitHub timelines, closed children, PR comments/review threads, `rg` searches, line-level code evidence, focused tests.
- Evidence gaps: Windows AC/CSP and physical device runtime proof.
- Suggested successor issues: listed below.

### Epic #5 - EPIC: AC Copilot Trainer

#### Original Intent

Build the full AC Copilot Trainer product: CSP Lua app, telemetry, 3D markers, ML analysis, LLM coaching, and Phase 4 optimization/RL/export/community capabilities.

#### Requirement Structure

EPIC_GOAL_001:

- Goal: deliver the AC Copilot Trainer product vision.
- Source: issue `#5` body.
- Why it mattered originally: created the parent roadmap for the project bootstrap.
- Current relevance: historical; execution has moved to closed phase issues plus open `#19`.

CAPABILITY_5_001:

- Required behavior: Phase 1 telemetry/brake/throttle/persistence/markers/delta.
- Related child issues: `#6`, `#7`.
- Related PRs: `#10`, `#20`.
- Current implementation evidence: `src/ac_copilot_trainer/modules/telemetry.lua`, `brake_detection.lua`, `track_markers.lua`, `delta.lua`.
- Tests/docs evidence: closed child issues; issue body checked.
- Status: `DELIVERED_DIRECTLY`.
- Residual work: none.
- Recommendation: preserve as completed traceability.

CAPABILITY_5_002:

- Required behavior: Phase 2 analysis/comparison.
- Related child issues: `#8`.
- Related PRs: `#21`.
- Current implementation evidence: `corner_analysis.lua`, `racing_line.lua`, `tire_monitor.lua`, `setup_reader.lua`.
- Tests/docs evidence: closed child issue; issue body checked.
- Status: `DELIVERED_DIRECTLY`.
- Residual work: none.
- Recommendation: preserve as completed traceability.

CAPABILITY_5_003:

- Required behavior: Phase 3 coaching/intelligence.
- Related child issues: `#9`, `#43`, `#44`, `#45`, `#46`, `#47`, `#49`, `#57`.
- Related PRs: `#51`-`#56`, `#58`-`#65`.
- Current implementation evidence: `realtime_coaching.lua`, `coaching_overlay.lua`, `tools/ai_sidecar/improvement_ranking.py`, `session_journal.lua`.
- Tests/docs evidence: closed children and merged PRs.
- Status: `DELIVERED_DIRECTLY`.
- Residual work: none in this parent.
- Recommendation: preserve as completed traceability.

CAPABILITY_5_004:

- Required behavior: Phase 4 advanced AI and optimization.
- Related child issues: `#19`.
- Related PRs: none implementing it.
- Current implementation evidence: no optimizer/RL/export/community implementation found.
- Tests/docs evidence: none beyond open issue `#19`.
- Status: `STILL_REQUIRED` but duplicated into `#19`.
- Residual work: all owned by `#19` or successors.
- Recommendation: close `#5`; keep or split `#19`.

Traceability matrix:

| Epic Requirement | Original Source | Delivered By | Current Code Evidence | Test/Doc Evidence | Current Relevance | Residual Work | Recommended Action |
|---|---|---|---|---|---|---|---|
| Phase 1 foundation | `#5` body | `#6`, `#7`, PR `#10`, PR `#20` | telemetry/brake/marker/delta modules | closed children | Delivered | None | `DELIVERED_DIRECTLY` |
| Phase 2 analysis | `#5` body | `#8`, PR `#21` | corner/racing/tire/setup modules | closed child | Delivered | None | `DELIVERED_DIRECTLY` |
| Phase 3 coaching | `#5` body | `#9`, `#43`-`#49`, `#57`, PR chain through `#64` | realtime/coaching/sidecar/journal modules | closed children + merged PRs | Delivered | None | `DELIVERED_DIRECTLY` |
| Phase 4 advanced AI | `#5` body | Not delivered; represented by `#19` | no optimizer/RL/export/community code | open `#19` | Still relevant, better represented elsewhere | `#19` | `DUPLICATED_ELSEWHERE` |

Final recommendation: `CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES`.

Proposed GitHub comment:

```markdown
Epic Reconciliation Result: CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES

Summary:
This parent epic has served its roadmap purpose. Phases 1-3 are delivered through closed child issues and merged PRs on `main`; the only material remaining scope is Phase 4, already tracked by open successor issue #19.

Original Epic Intent:
- Build the full AC Copilot Trainer product from telemetry foundation through coaching intelligence.
- Track Phase 4 advanced AI / optimization once the core trainer was in place.

Traceability Matrix:
| Epic Requirement | Status | Delivered / Superseded By | Evidence |
|---|---|---|---|
| Phase 1 foundation | DELIVERED_DIRECTLY | #6, #7, PR #10, PR #20 | telemetry/brake/marker/delta modules on main |
| Phase 2 analysis | DELIVERED_DIRECTLY | #8, PR #21 | corner/racing/tire/setup modules on main |
| Phase 3 coaching | DELIVERED_DIRECTLY | #9, #43-#49, #57, PRs through #64 | sidecar, realtime coaching, journal, HUD work on main |
| Phase 4 advanced AI | DUPLICATED_ELSEWHERE | `#114`, `#115`, `#116` | #19 was closed after replacement; successors own setup/Bayesian, export, and RL/prototype scope |

Current Architecture Reality:
- Execution no longer needs this broad parent; the remaining work has a narrower current owner (#19).
- Keeping #5 open creates planning noise because every actionable item is either delivered or belongs to #19.

Council Review:
- GPT-family: CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES
- Gemini: CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES
- Mistral: CLOSE_AS_MOSTLY_COMPLETED_WITH_SUCCESSOR_ISSUES
- Other: repo-specific subagent unavailable
- Consensus: close this epic and use #19 for remaining Phase 4 work.
- Disagreements: none.
- Resolution: retire #5 with traceability.

Residual Work:
- Phase 4 only, tracked by #19.

Successor Issues:
- #114 Add setup experiment tracking and Bayesian setup suggestions
- #115 Export archived laps to CSV and MoTeC-compatible telemetry
- #116 Decide and prototype RL reference-lap generation

Decision:
This epic should be closed as mostly completed with successor issues.

Reason:
The material delivered product exists on `main`, and the only remaining area is already represented by a narrower open issue.

Confidence:
High
```

### Epic #19 - Advanced AI Roadmap

#### Original Intent

Add proactive advanced AI after Phase 3: setup experiments, Bayesian optimization, RL-generated reference laps, CSV/MoTeC export, and community sharing.

#### Architecture Evolution

The repository now has a per-lap archive and sidecar foundation, but not an advanced optimization architecture. PR `#78` explicitly made the archive schema forward-compatible with future imported laps, not a MoTeC importer/exporter or optimizer. The issue combines ML experimentation, GPU/RL research, export formats, and community data workflows into one stale roadmap artifact.

Traceability matrix:

| Epic Requirement | Original Source | Delivered By | Current Code Evidence | Test/Doc Evidence | Current Relevance | Residual Work | Recommended Action |
|---|---|---|---|---|---|---|---|
| Setup experiment framework | `#19` Part A | None | no `tools/ai_sidecar/setup/` | no tests | Still relevant if Phase 4 proceeds | tracker + stats + UI | `STILL_REQUIRED` |
| Bayesian setup optimizer | `#19` Part B | None | no `skopt` / optimizer code | no tests | Still relevant but should follow experiment tracker | optimizer + tests | `STILL_REQUIRED` |
| RL optimal laps | `#19` Part C | None | no `tools/rl_training/`, no `assetto_corsa_gym` | none | Product decision needed; stretch item | feasibility decision/prototype | `STILL_REQUIRED` / product decision |
| CSV/MoTeC export | `#19` Part D | None; PR `#78` only foundation | `lap_archive.lua:1-15` future fields only | PR `#78` docs say future scope | Still relevant as narrow issue | exporter + tests | `STILL_REQUIRED` |
| Community sharing/import | `#19` Part E | Dropped by owner decision; `#79` separately covers local MoTeC import | no community module | none | No longer active | none | `OBSOLETE` / dropped |

Final recommendation: `SPLIT_AND_REPLACE`.

Proposed successor issues:

```markdown
Title: Add setup experiment tracking and Bayesian setup suggestions

Problem:
Phase 4 setup optimization is still unimplemented. The repository has setup snapshots and lap archives, but no experiment rows, statistical A/B comparison, or Bayesian next-setup suggestion path.

Current Evidence:
- Open epic #19 Part A/B requests setup experiments and Bayesian optimization.
- `rg` found no `tools/ai_sidecar/setup/`, `skopt`, or optimizer implementation.
- `src/ac_copilot_trainer/modules/lap_archive.lua` stores setup snapshots but does not model experiments.

Scope:
- Add an experiment store for setup params, lap telemetry summary, and conditions.
- Add A/B significance calculation for old vs new setup runs.
- Add Bayesian next-suggestion logic only after experiment rows exist.
- Surface suggestions through the existing sidecar/Lua boundary.

Acceptance Criteria:
- [ ] Experiment records are written from archived laps with setup and conditions.
- [ ] A/B comparison reports measurable improvement and confidence/significance.
- [ ] Bayesian suggestion command returns the next setup candidate with rationale.
- [ ] Tests cover record creation, significance calculation, and suggestion output.
- [ ] Docs describe data location and how to reset/rebuild experiments.

Non-Goals:
- RL training.
- Community sharing.
- MoTeC import/export.
- Reworking delivered Phase 1-3 coaching.

Links:
- Retired epic #19
- Parent epic #5
- `src/ac_copilot_trainer/modules/lap_archive.lua`
- `tools/ai_sidecar/`

Closure Condition:
- A user can run enough archived setup laps to get a tested, deterministic setup suggestion.
```

```markdown
Title: Export archived laps to CSV and MoTeC-compatible telemetry

Problem:
The archive schema is forward-compatible, but there is no exporter for CSV or MoTeC/i2 analysis.

Current Evidence:
- #19 Part D requests CSV and MoTeC export.
- `lap_archive.lua` writes JSON per-lap records only.
- `docs/01_Vault/.../pr-78-sidecar-autolaunch-lap-archive.md` says MoTeC/import work is future scope.

Scope:
- Add a CLI or tool module that reads `journal/laps/lap_*.json`.
- Export CSV with speed, brake, throttle, steering, gear, spline, and position.
- Define a MoTeC-compatible channel mapping or document exact compatibility limits.
- Add tests with fixture lap archives.

Acceptance Criteria:
- [ ] CSV export produces stable columns from a fixture archive.
- [ ] MoTeC-compatible export path is implemented or explicitly documented with format limitations.
- [ ] Tests cover valid lap, invalid lap filtering, and missing-field behavior.
- [ ] Documentation names input/output paths and supported channels.

Non-Goals:
- MoTeC CSV import (#79).
- Bayesian setup optimization.
- Community upload/download.

Links:
- Retired epic #19
- `src/ac_copilot_trainer/modules/lap_archive.lua`
- `docs/01_Vault/AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md`

Closure Condition:
- A fixture archived lap can be exported and consumed by the documented downstream analysis path.
```

```markdown
Title: Decide and prototype RL reference-lap generation

Problem:
#19 includes RL reference laps as a stretch feature, but the repository has no RL runtime, GPU workflow, simulator wrapper, or acceptance boundary.

Current Evidence:
- #19 Part C references `assetto_corsa_gym`, SAC, and TUMFTM.
- `rg` found no `tools/rl_training/`, `assetto_corsa_gym`, or `stable_baselines` usage.

Scope:
- Decide whether the project should pursue RL training, TUMFTM trajectory generation, or defer this feature.
- If pursuing, add a minimal prototype with documented runtime requirements and fixture output shape.
- Define how a generated reference trace enters the existing lap/archive comparison path.

Acceptance Criteria:
- [ ] Decision doc chooses RL, TUMFTM, or deferral with evidence.
- [ ] If not deferred, prototype emits one reference trace in the expected schema.
- [ ] Runtime/dependency requirements are documented and isolated from `make ci-fast`.
- [ ] Tests validate trace schema without requiring GPU/Assetto Corsa runtime.

Non-Goals:
- Production overnight model training unless separately approved.
- Community sharing.
- Setup Bayesian optimization.

Links:
- Retired epic #19
- Parent epic #5

Closure Condition:
- The repo has an evidence-backed go/no-go and, if go, a tested schema-compatible reference trace prototype.
```

Community-sharing successor omitted: owner decision was to drop this scope.

Proposed GitHub comment:

```markdown
Epic Reconciliation Result: SPLIT_AND_REPLACE

Summary:
This Phase 4 roadmap issue is not implemented on `main`, and it is too broad to remain an executable work item. It combined setup experiments, Bayesian optimization, RL research, export formats, and community sharing. Setup/optimizer, export, and RL were replaced by narrow current issues; community sharing was dropped.

Original Epic Intent:
- Add proactive optimization after Phase 3 coaching.
- Cover setup experiments, Bayesian suggestions, RL reference laps, export, and community sharing.

Traceability Matrix:
| Epic Requirement | Status | Delivered / Superseded By | Evidence |
|---|---|---|---|
| Setup experiment framework | STILL_REQUIRED | none | no `tools/ai_sidecar/setup/` or experiment tests |
| Bayesian setup optimizer | STILL_REQUIRED | none | no `skopt` / optimizer code |
| RL reference laps | STILL_REQUIRED / product decision | none | no `tools/rl_training/`, `assetto_corsa_gym`, or `stable_baselines` |
| CSV/MoTeC export | STILL_REQUIRED | none | `lap_archive.lua` is JSON archive only |
| Community sharing/import | OBSOLETE / DROPPED | none | no sharing module; owner decision was to drop this scope; #79 separately covers local MoTeC import |

Current Architecture Reality:
- PR #78 created archive foundation only; it did not implement this roadmap.
- The issue spans several independent surfaces and is not a useful single implementation target.

Council Review:
- GPT-family: SPLIT_AND_REPLACE
- Gemini: SPLIT_AND_REPLACE
- Mistral: SPLIT_AND_REPLACE
- Other: repo-specific subagent unavailable
- Consensus: replace with narrow issues.
- Disagreements: Mistral noted medium confidence because product priority is not encoded.
- Resolution: split implementation-ready items, keep RL as decision-first, and drop community sharing per owner decision.

Residual Work:
- Setup experiment + Bayesian optimizer
- CSV/MoTeC export
- RL reference-lap decision/prototype
- Community sharing: dropped, no successor

Successor Issues:
- #114 setup experiment tracking and Bayesian setup suggestions
- #115 export archived laps to CSV/MoTeC-compatible telemetry
- #116 decide/prototype RL reference-lap generation

Decision:
This epic should be split and replaced.

Reason:
No requested capability is implemented, and the scope is too broad for one actionable issue.

Confidence:
High
```

### Epic #59 - Physical Rig Integration

#### Original Intent

Build the physical cockpit hardware layer: Arduino UNO fan/OLED/vibration/pedal haptics, ESP32 dashboard, bass shaker, side bolster motors, enclosure, and native sidecar protocol without SimHub dependency.

#### Architecture Evolution

The hardware roadmap transformed. ESP32 screen work moved into `#86`; the live focus doc says Stream A is the first slice of `#59`, and PR `#91` delivered much of that screen slice. Bass-shaker work is documented as live through a SimHub/Phase 1R path, which conflicts with the original "all peripherals without SimHub" acceptance criterion. After owner follow-up, the side-bolster/pedal-haptics and enclosure/mount successors were closed as dropped physical-only scope.

Traceability matrix:

| Epic Requirement | Original Source | Delivered By | Current Code Evidence | Test/Doc Evidence | Current Relevance | Residual Work | Recommended Action |
|---|---|---|---|---|---|---|---|
| ESP32 dashboard foundation | `#59` Phase 2 | PR `#83`, PR `#91`, PR `#100`, issue `#86` | `firmware/screen/`, sidecar external protocol, setup handlers | Current Focus lines 23-40 | Current, owned by `#86` | `#86` Parts E-F | `DUPLICATED_ELSEWHERE` |
| Arduino UNO fan/OLED | `#59` Phase 1 | None | no Arduino UNO firmware in `firmware/` | none | Still plausible | firmware + serial/WS path | `STILL_REQUIRED` |
| Native haptic protocol | `#59` software changes | None | no `telemetry_tick` / `haptic_event` | rig doc lists only planned types | Still plausible | protocol + sidecar routing | `STILL_REQUIRED` |
| Bass shaker no-SimHub | `#59` Phase 3a | Transformed to SimHub/live config docs | no native output | Current Focus says Phase 1R done via SimHub | Original no-SimHub assumption likely obsolete | product decision only | `TRANSFORMED` / `OBSOLETE` |
| Side bolster/pedal haptics | `#59` Phases 3b/4 | Dropped after successor `#119` was created | no haptic firmware/generation | rig doc lists planned pins/safeguards | No longer active | none | `OBSOLETE` / dropped |
| Enclosure/mount artifacts | `#59` acceptance | Dropped after successor `#120` was created | no model artifacts found | none | No longer active | none | `OBSOLETE` / dropped |

Final recommendation: `SPLIT_AND_REPLACE`.

Proposed successor issues:

```markdown
Title: Implement Arduino fan and OLED telemetry peripheral

Problem:
#59 Phase 1 remains unimplemented. The repo has no Arduino UNO firmware for fan PWM or SSD1306 tyre display.

Current Evidence:
- `firmware/` contains only the ESP32 screen project.
- `docs/01_Vault/AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md` lists Arduino UNO fan/OLED as Phase 1.

Scope:
- Add Arduino UNO firmware for fan speed and OLED tyre telemetry.
- Define the PC-to-Arduino transport used by the sidecar or trainer.
- Add simulator-free tests or protocol fixtures where possible.

Acceptance Criteria:
- [ ] Firmware maps speed to fan PWM with bounded output.
- [ ] OLED renders tyre temperatures/pressures/wear from a test frame.
- [ ] Transport contract is documented.
- [ ] Thermal/electrical safety notes are documented.

Non-Goals:
- ESP32 screen work (#86).
- Seat/pedal haptics.
- Bass shaker.

Links:
- Retired/split epic #59
- `docs/01_Vault/AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md`

Closure Condition:
- Bench test frame drives fan/OLED behavior through the documented transport.
```

```markdown
Title: Add telemetry and haptic event protocol for physical peripherals

Problem:
The original hardware epic requires `telemetry_tick` and `haptic_event`, but the current sidecar protocol only supports screen/external-client messages such as `setup.list`, `setup.load`, and `state.snapshot`.

Current Evidence:
- `tools/ai_sidecar/external_protocol.py` defines setup and snapshot types, not `telemetry_tick` or `haptic_event`.
- `rg` found no native haptic event generation path.

Scope:
- Define `telemetry_tick` and `haptic_event` message shapes.
- Route events from Lua/sidecar to physical peripheral clients without echoing to Lua.
- Add rate limiting and tests for validation/routing.

Acceptance Criteria:
- [ ] Protocol constants and validation exist for telemetry/haptic messages.
- [ ] Sidecar routes physical-peripheral messages to the intended client class.
- [ ] Tests cover invalid frames, no-client behavior, and rate limiting.
- [ ] Docs describe payload fields and expected frequency.

Non-Goals:
- Implementing Arduino motor firmware.
- ESP32 Setup Exchange screen.
- Community telemetry sharing.

Links:
- Retired/split epic #59
- `tools/ai_sidecar/external_protocol.py`
- `tools/ai_sidecar/server.py`

Closure Condition:
- A fixture telemetry frame produces a validated haptic event route in tests.
```

Dropped successors:

- `#119` was created for side bolster and pedal haptics, then closed as physical-only scope not expected to be wired into the active implementation path.
- `#120` was created for rig enclosure and mount artifacts, then closed as physical fabrication scope not expected to be part of the active software workflow.

Proposed GitHub comment:

```markdown
Epic Reconciliation Result: SPLIT_AND_REPLACE

Summary:
This physical-rig epic no longer works as one current execution item. The ESP32 screen slice moved into #86, bass shaker direction transformed through the SimHub/Phase 1R path, and only the Arduino fan/OLED plus protocol boundary remain active after dropping the physical-only haptics/enclosure successors.

Original Epic Intent:
- Build a complete tactile/visual physical rig hardware layer.
- Include Arduino fan/OLED/haptics, ESP32 screen, bass shaker, side motors, pedal haptics, and enclosure.

Traceability Matrix:
| Epic Requirement | Status | Delivered / Superseded By | Evidence |
|---|---|---|---|
| ESP32 dashboard | DUPLICATED_ELSEWHERE / PARTIALLY_DELIVERED | #86, PR #83, PR #91, PR #100 | `firmware/screen/`, external protocol, setup handlers |
| Arduino fan/OLED | STILL_REQUIRED | none | no Arduino UNO firmware under `firmware/` |
| Native haptic protocol | STILL_REQUIRED | none | no `telemetry_tick` or `haptic_event` implementation |
| Bass shaker no-SimHub | TRANSFORMED / OBSOLETE | Phase 1R SimHub/live config docs | Current Focus says bass shaker is done as Phase 1R |
| Side bolster/pedal haptics | OBSOLETE / DROPPED | #119 closed | physical-only scope not expected to be wired into active implementation |
| Enclosure/mounts | OBSOLETE / DROPPED | #120 closed | fabrication scope not expected to be part of active software workflow |

Current Architecture Reality:
- #86 is the active ESP32 screen coordination object.
- Remaining active physical-peripheral work is limited to Arduino fan/OLED and the protocol boundary.

Council Review:
- GPT-family: SPLIT_AND_REPLACE
- Gemini: SPLIT_AND_REPLACE
- Mistral: SPLIT_AND_REPLACE
- Other: repo-specific subagent unavailable
- Consensus: split the epic into narrow hardware successors.
- Disagreements: none material.
- Resolution: retire #59 after successor issue creation; later close #119/#120 after owner decision to drop physical-only scope.

Residual Work:
- Arduino fan/OLED peripheral
- telemetry_tick/haptic_event protocol
- side bolster + pedal haptics: dropped, `#119` closed
- enclosure/mount artifacts: dropped, `#120` closed

Successor Issues:
- #117 Implement Arduino fan and OLED telemetry peripheral
- #118 Add telemetry and haptic event protocol for physical peripherals
- #119 Implement side bolster and pedal haptics with thermal safeguards (created, then closed as dropped)
- #120 Add rig enclosure and mount artifacts (created, then closed as dropped)

Decision:
This epic should be split and replaced.

Reason:
The original epic is fragmented and partially transformed; the remaining work can be expressed as narrow, testable issues.

Confidence:
High
```

### Epic #86 - Rig Screen Phase-2 UI

#### Original Intent

Replace the debug-grade JC3248W535 screen with a production LVGL touchscreen UI: launcher, AC Copilot mirror, Pocket Technician setup picker, Setup Exchange browser, and device polish.

#### Delivery Map

| Requirement | Delivered By | Evidence |
|---|---|---|
| Part A LVGL/touch/framework | PR `#91` partially | `firmware/screen/platformio.ini:52-61`; touch/nav/UI files; font conversion remains |
| Part B launcher | PR `#91` | `firmware/screen/src/ui/screen_launcher.cpp:347-355` |
| Part C AC Copilot mirror | PR `#91` | `coaching_publisher.lua:1-23`, `125-141`; `ws_bridge.lua:915-947`; `screen_ac_copilot.cpp` |
| Part D Pocket Technician | PR `#91`, PR `#100` | `setup_library.lua`, `ac_copilot_trainer.lua:420-535`, `external_protocol.py:29-45`, PT chip fix in PR `#100` |
| Part E Setup Exchange | Not delivered | no `se_proxy.py`, no `se.search`, no `se.download`, no `setup.install` |
| Part F polish | Partially missing | handoff lines 45-63 list SPIFFS/debug/polish, external-bind/token, device smoke |

Traceability matrix:

| Epic Requirement | Original Source | Delivered By | Current Code Evidence | Test/Doc Evidence | Current Relevance | Residual Work | Recommended Action |
|---|---|---|---|---|---|---|---|
| LVGL/touch/framework | `#86` Part A | PR `#91` | PlatformIO/LVGL/touch/nav code | PR `#91`; handoff says A4 fonts remain | Current | font conversion | `PARTIALLY_DELIVERED` |
| Launcher | `#86` Part B | PR `#91` | launcher tiles | PR `#91` | Delivered | none | `DELIVERED_DIRECTLY` |
| AC Copilot mirror | `#86` Part C | PR `#91` | coaching publisher + screen parser | focused tests, PR `#91` | Current | hardware smoke | `DELIVERED_DIRECTLY` |
| Pocket Technician | `#86` Part D | PR `#91`, PR `#100` | setup library + handlers + PT UI | PR `#100` ledger; focused tests | Current | hardware smoke | `DELIVERED_DIRECTLY` |
| Setup Exchange | `#86` Part E | None | absent `se_proxy.py` / protocols | none | Current | proxy/search/download/install | `STILL_REQUIRED` |
| Integration/polish | `#86` Part F | partial | state handling exists, but gaps remain | handoff/current focus | Current | SPIFFS/debug/backpressure/token/runbook | `STILL_REQUIRED` |

Stale epic retirement gate:

- [x] The epic reflects current architecture after rewrite.
- [x] The epic has current acceptance criteria after rewrite.
- [x] The epic is not mostly delivered enough to retire because Part E and Part F are coherent and material.
- [x] The epic is not better represented by narrower issues yet; remaining work is one screen/proxy stream.
- [x] The epic has a clear closure condition after rewrite.
- [x] The epic still improves coordination.
- [x] The epic is not merely historical memory after rewrite.

Final recommendation: `KEEP_OPEN_BUT_REWRITE_SCOPE`.

Proposed replacement issue body:

```markdown
# [EPIC] Rig screen Phase-2 UI - remaining scope after reconciliation

## Reconciliation status

This issue originally covered Parts A-F of the production JC3248W535 rig screen. PR #91 merged Parts A-D on `main` as `35d770c`; PR #100 fixed the Pocket Technician row chip refresh defect from #93. This body now tracks only the remaining current scope.

## Delivered / No Longer Active In This Issue

- [x] Part A baseline LVGL/touch/framework, except font conversion outputs.
- [x] Part B launcher screen.
- [x] Part C AC Copilot mirror with `coaching.snapshot`.
- [x] Part D Pocket Technician setup list/load flow and pits gate.
- [x] PT stale brake-bias chip refresh fixed by PR #100.

Evidence:
- PR #91: Parts A-D merged.
- PR #100: PT chip refresh.
- `docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md` records the delivered and remaining scope.

## Current Scope After Reconciliation

### Part A4 - LVGL fonts

- [ ] Run `lv_font_conv` for bundled Michroma/Montserrat/Syncopate faces or document why generated fonts remain local-only.
- [ ] Verify glyph coverage required by the screen UI.

### Part E - Setup Exchange screen and proxy

- [ ] Add `tools/ai_sidecar/se_proxy.py`.
- [ ] Implement `se.search`, `se.download`, progress/result frames, and `setup.install`.
- [ ] Cache Setup Exchange results with bounded storage and offline fallback.
- [ ] Ensure installed setup appears in the Pocket Technician list and can be loaded.

### Part F - Integration and polish

- [ ] Add or verify SPIFFS persistence for last screen, SE sort, and cache.
- [ ] Prove telemetry/backpressure budget for the screen message rate.
- [ ] Add hidden/debug screen or equivalent diagnostic surface.
- [ ] Document sidecar token rotation in `firmware/screen/README.md`.
- [ ] Update sidecar startup so rig screen use has external bind + token path while loopback trainer still works.

### Final device smoke

- [ ] On-device proof: launcher -> AC Copilot live hints -> Pocket Technician setup load -> Setup Exchange browse/download/install.
- [ ] Record or attach the verification artifact.

## Closure Criteria

This issue can close when Parts A4, E, F, and final device smoke are complete on `main`, or when any remaining part is explicitly split into a narrower successor issue with a reconciliation comment here.

## Links

- PR #83 - external WS client foundation.
- PR #91 - Parts A-D merged.
- PR #100 - PT chip refresh fix.
- Issue #59 - broader physical rig hardware, being split/replaced separately.
```

Proposed GitHub comment:

```markdown
Epic Reconciliation Result: KEEP_OPEN_BUT_REWRITE_SCOPE

Summary:
This epic is still the right coordination object for the remaining rig-screen work, but the original body is stale because PR #91 delivered Parts A-D and PR #100 fixed the PT chip refresh defect. The issue should stay open only after rewriting it to Parts A4, E, F, and final device smoke.

Original Epic Intent:
- Build production JC3248W535 LVGL screen UI.
- Cover launcher, AC Copilot, Pocket Technician, Setup Exchange, and integration polish.

Traceability Matrix:
| Epic Requirement | Status | Delivered / Superseded By | Evidence |
|---|---|---|---|
| Part A LVGL/touch/framework | PARTIALLY_DELIVERED | PR #91 | `firmware/screen/platformio.ini`; font conversion remains |
| Part B launcher | DELIVERED_DIRECTLY | PR #91 | `screen_launcher.cpp` app tiles |
| Part C AC Copilot mirror | DELIVERED_DIRECTLY | PR #91 | `coaching_publisher.lua`, `ws_bridge.publishTopic`, `screen_ac_copilot.cpp` |
| Part D Pocket Technician | DELIVERED_DIRECTLY | PR #91 and PR #100 | `setup_library.lua`, setup handlers, PT chip refresh tests |
| Part E Setup Exchange | STILL_REQUIRED | none | no `se_proxy.py`, `se.search`, `se.download`, or `setup.install` |
| Part F polish/integration | STILL_REQUIRED | partial | handoff lists SPIFFS/debug/token/backpressure/device-smoke gaps |

Current Architecture Reality:
- The screen/proxy path remains coherent and active.
- The old body overstates remaining work because Parts A-D are already on `main`.

Council Review:
- GPT-family: KEEP_OPEN_BUT_REWRITE_SCOPE
- Gemini: KEEP_OPEN_BUT_REWRITE_SCOPE
- Mistral: KEEP_OPEN_BUT_REWRITE_SCOPE
- Other: repo-specific subagent unavailable
- Consensus: keep open but rewrite.
- Disagreements: none.
- Resolution: replace the body with current acceptance criteria.

Residual Work:
- Part A4 fonts
- Part E Setup Exchange
- Part F integration/polish
- external-bind/token startup
- final on-device smoke

Successor Issues:
- None required if the body is rewritten. Create successors only if Part E or Part F is intentionally split later.

Decision:
This epic should be kept open with rewritten scope.

Reason:
The remaining work is material, current, aligned with architecture, and still cohesive as one screen epic.

Confidence:
High
```

## GitHub Write Actions Performed

User approved proceeding after the initial audit. Actions performed:

- Created `#114` [Add setup experiment tracking and Bayesian setup suggestions](https://github.com/agorokh/ac-copilot-trainer/issues/114).
- Created `#115` [Export archived laps to CSV and MoTeC-compatible telemetry](https://github.com/agorokh/ac-copilot-trainer/issues/115).
- Created `#116` [Decide and prototype RL reference-lap generation](https://github.com/agorokh/ac-copilot-trainer/issues/116).
- Created `#117` [Implement Arduino fan and OLED telemetry peripheral](https://github.com/agorokh/ac-copilot-trainer/issues/117).
- Created `#118` [Add telemetry and haptic event protocol for physical peripherals](https://github.com/agorokh/ac-copilot-trainer/issues/118).
- Created `#119` [Implement side bolster and pedal haptics with thermal safeguards](https://github.com/agorokh/ac-copilot-trainer/issues/119).
- Created `#120` [Add rig enclosure and mount artifacts for physical peripherals](https://github.com/agorokh/ac-copilot-trainer/issues/120).
- Closed `#119` as dropped physical-only haptics scope after owner follow-up.
- Closed `#120` as dropped physical-only fabrication scope after owner follow-up.
- Closed `#5` with an epic-retirement traceability comment.
- Closed `#19` with a split/replace traceability comment; community sharing was dropped and no successor issue was created.
- Closed `#59` with a split/replace traceability comment.
- Rewrote `#86` body to current Parts A4/E/F scope and added reconciliation comment: https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-4526031208.
- Commented on `#79` and left it open: https://github.com/agorokh/ac-copilot-trainer/issues/79#issuecomment-4526031240.

No labels were invented; only existing labels were used on successor issues.

## Verification Commands

```bash
git fetch --prune origin
gh issue list --state open --limit 200 --json number,title,labels,assignees,milestone,createdAt,updatedAt,author,url
gh issue view <issue> --comments --json number,title,body,comments,labels,assignees,milestone,projectItems,author,createdAt,updatedAt,url,closed,closedAt
gh api --paginate -H "Accept: application/vnd.github+json" /repos/agorokh/ac-copilot-trainer/issues/<issue>/timeline
gh pr view 91 --json number,title,body,author,mergedAt,mergeCommit,commits,files,reviews,comments,labels,headRefName,baseRefName,updatedAt,url,statusCheckRollup
python3.11 -m pytest -q tests/test_setup_library_summary.py tests/test_ai_sidecar_external.py tests/test_ai_sidecar_protocol.py tests/test_design_conformance.py
```

Focused test result:

```text
32 passed, 5 skipped in 0.11s
```

Skipped tests:

- `tests/test_setup_library_summary.py`: `lupa` not installed.
- `tests/test_ai_sidecar_external.py` and `tests/test_ai_sidecar_protocol.py`: `websockets` not installed.

## Limitations

- GitHub write actions were initially disabled during audit, then explicitly approved by the user and performed. Suggested comments remaining in earlier sections are historical drafts; the actual action list is above.
- Local default `python3` is Python 3.14 without `pytest`; focused tests were run with `python3.11`.
- Runtime/on-device validation for the Windows-only Assetto Corsa/CSP app and ESP32 hardware was not possible from this macOS worktree.
- Firmware PlatformIO compile was not run; PlatformIO was not verified in the local environment during this audit.
- GitHub raw timeline output can be very large; timeline calls were paginated and then reduced into counts and reference summaries for the report.
