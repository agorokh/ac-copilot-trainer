---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T05:18:44Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-034900Z-rig-dashboard-control-d326a9.md
  - AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Game Point deployed; live AC verification blocked by game freezes

Operator authorized finishing review, deploying Game Point, and launching Porsche
911 GT3 R 2016 at Magione. Earlier C1 autonomous-driving acceptance remains paused.
Task #804 stays OPEN: live dashboard and physical rig-screen acceptance did not pass.

## Review and deployed package

- PR [#805](https://github.com/agorokh/ac-copilot-trainer/pull/805) merged as
  `420eeb17125ab129da0bafc493c425af951d8082`; audited head
  `90323fd865bfb8789f2ff761ec90e1f8bb19006d`, author vendor OpenAI.
- Eligible exact-head Antigravity and Grok reviews met the floor. Cursor quota
  absence was explicit. Adopted initial sizing findings; Antigravity's final
  missing-flush claim was refuted by the existing call at view.py:296.
- Existing trusted-MAIN dismissal-only companion PR
  [#806](https://github.com/agorokh/ac-copilot-trainer/pull/806) merged as
  `057c480bc741d664a324cdf8f5272a5c80d80368`. One exact path/title/line-272
  family row, zero line tolerance; no inline or unrelated-title dismissal.
- Complete paginated feedback, green hosted CI, independent quorum, null live
  merge queue and executed final findings enforcement preceded both merges.
  Immutable runtime pin `b256859fc74cd986e2fbbb1f10623ececc52116f`;
  mode=enforce, findings=enforce, daemon-lease=enforce, author-vendor=openai.
  Original head stayed unchanged. Its preflight failed before the companion and
  passed after trusted MAIN contained the row. No review bypass.
- Product `make ci-fast`: 4129 passed, 89 declared skips. Companion full check:
  4127 passed, 89 skips. Focused launcher checks: 151 passed. Frozen self-test passed.
- Primary main fast-forwarded to `420eeb1`. Deployed primary
  `dist/AC-Copilot-Game-Point.exe` SHA256
  `693f9bcff52e2341fcd6252d859f5fa118a3200513ff8e73ee1c1c9d9170b341`.
  Runtime health confirms `build_commit=90323fd`,
  `build_time=2026-10-12T04:26:09Z`; product source matches merged MAIN.
- Canonical installer refreshed the existing Desktop shortcut to primary dist.
  Old EXE preserved under primary `.scratch/rig-restore/` as
  `AC-Copilot-Game-Point-before-804.exe`; deployment.json retains both hashes.
- Two fresh launches showed all six rows and seven actions at 878x559 without
  manual resize. Yellow START worked; live status also fit. Real Tk tests cover
  enlarged scaling, long diagnostics, enforced minimum and manual enlargement.

## Rig and failure evidence

- GamePoint settings preserve prior preferences and select
  `ks_porsche_911_gt3_r_2016`, `magione`, blank layout and installed Content Manager.
  Porsche content preflight passed. No other rig owner existed before launch.
- Content Manager had removed `[NEW_UI] REPLACE_MAIN_MENU=0` from AC Documents
  `cfg/extension/gui.ini`. Added only that required key, preserving other settings;
  original is saved as `gui-before-live.ini`. Current readback confirms 0.
- Normal STABLE AC acquired ownership and repeatedly launched the selected combo.
  Attempts 1-9 ended FROZE; later attempts positively acknowledged session.start
  but remained at the pits menu. RELEASE AC interrupted attempt 10, made AC safe,
  and released ownership. No stable handoff was delivered.
- Direct Content Manager launch and observed Drive click entered the Magione
  cockpit. AC became unresponsive; graphics packet 3035 stayed fixed for 20 s,
  with no telemetry ticks. Focus and F1 did not restore responsiveness.
- One windowed attempt also froze, packet 5733 static. A standard-physics attempt
  froze, packet 4145 static for 20 s, with no ticks and no observer protocol errors.
  These controls do not establish a cause or a successful mitigation.
- Diagnostic FULLSCREEN=0 was restored to original FULLSCREEN=1. Original video
  bytes are preserved as `video-before-windowed.ini`. Extended physics restored
  to its prior checked state. Only individually verified, owned, unresponsive
  AC process IDs were stopped; no host reboot was performed.
- Sidecar remains running and healthy on 8765. P7 serial
  `1c000c75b543099221d` is authorized; USB reverse and scrcpy screenshots/control
  work. `browser_peers=1`, `screen_peers=1` on the reviewed package.
- Actual tablet pixels remain WAITING, with absent live speed/fuel/temperature
  channels. Setup electronics arrived (bias 68%, TC 3/12, ABS 8/12), which is
  setup-state proof, not live-telemetry proof. ESP32 COM6 transport connected;
  actual physical rendering is unverified. No framebuffer capture endpoint exists.
- Voice remains observer-only; SimHub stays running. No autonomous driver started.

## Resume and evidence

First recover a responsive AC session, then require advancing current-writer
packets and actual telemetry_tick frames; reconcile tablet pixels against them.
Get physical ESP32 readback separately. A host reboot needs explicit approval
because it interrupts Codex and other open Windows work; none is granted here.
Do not claim connection counts or frozen LIVE flags establish display success.

Ignored evidence: this chat worktree `.scratch/rig-restore/`: deployment.json,
game-point-installed-startup.png, game-point-installed-reopened.png,
game-point-current-ready.png, cm-porsche-magione.png, ac-manual-drive-stalled.png,
tablet-live.png, live-telemetry.json, windowed-stalled-telemetry.json,
live-readback*.txt, health-final.json, complete PR ledgers and final preflight logs.
Resilient logs/status/settings remain in the existing LocalAppData GamePoint root.
Tier-3 MCP was unavailable; canonical SessionStart prefetch succeeded with a
task-specific prompt. No secrets were logged or saved to repository documentation.
