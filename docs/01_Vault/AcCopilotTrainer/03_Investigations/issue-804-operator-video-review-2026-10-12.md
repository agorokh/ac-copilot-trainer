---
type: investigation
status: draft
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T20:59:25Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-181458Z-operator-driven-rigcheck-f3b1cc.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Operator video: live transport works; setup and coaching semantics need repair

User requested independent analysis of IMG_8761.MOV, including problems beyond
spoken concerns. Original local Downloads file is 149.19 s, 3840x2160 HEVC/AAC,
858275869 bytes; SHA256 F10AF1D82EB1D4B92A981CDD0CD881FD65CB8E71FA500B8C9216A8C3977C2981.
Raw video, extracted frames and locally generated ASR transcript stay ignored.
Full report: .scratch/rig-restore/operator-video-review/report.md.

Physical dynamic verification is now proven: after leaving Pocket Technician,
the ESP32 speed, corner, distance, progress and delta change during driving.
At phone 01:48 game/ESP32/tablet speed is approximately 170/170/169 km/h, gear 4.
No deployment or autonomous driving occurred during analysis.

## Confirmed findings

1. Wrong firmware command mapping: screen_ac_copilot.cpp command_for_snapshot
   treats all kind=line as LIFT. realtime_coaching emits SHIFT UP, CARRY MORE SPEED
   and EASE OFF with that kind. At 01:45 the actual screen says LIFT while tablet
   says UPSHIFT. Fix action semantics, not transport.
2. Pocket Technician remains 68% at 00:40 and 01:05, while AC's adjustment overlay
   shows 63.0% at 00:50. Values are cached spinner snapshots, not continuous
   in-car bias. CSP-first/INI fallback source cannot be identified from video.
   The continuous telemetry producer lacks brake bias; tablet electronics also
   consume spinner snapshots.
3. +/- touch at 01:07-01:09 occurs stopped on track, outside pits. Lua gates all
   spinner writes on ac.isCarResetAllowed, returning must be in pits. Firmware
   displays ordinary buttons and only a transient rejection toast. No retained
   individual ack body proves the actual request rejection; avoid claiming
   transport failure or bypassing the gate.
4. Actual distance wraps: 01:48 367 becomes 36/7; 01:50 269 becomes 26/9;
   01:51 232 becomes 23/2. Firmware uses 80 px at Saira 46; source TTF 269 is
   89 px. Keep complete numbers on one line and check signed deltas.
5. Tablet min 230 is a brake-point entrySpeed, not minimum corner speed.
   In-corner label and next-brake target are also mixed: view has approachLabel,
   publisher omits it, consumers show cornerLabel + target as NEXT. Captured
   snapshots include T5 targets 89/230, T6 230/128 and T7 128/107.

## Qualifications and resume

Oil/water blanks are intentional current-producer gaps. NO REFERENCE means no
usable live delta, although AC app shows active PB 1:20.045; NO SETUP LOADED
can mean unnamed/unresolved setup. Do not infer missing reference/setup or
persistent freeze from these labels. Video ends before intentional AC exit;
small-screen stale handling, completed lap and voice were not verified.

Review grounded via successful task-specific Tier-3 prefetch, latest handoff,
start-task and vault-memory; bounded source/video review, no council invoked.
Notes are local drafts, not committed, published, independently reviewed or
merged. Keep #804 open for discovered defects and Stable AC automatic Drive.
C1 remains paused; preserve firmware, audio, SimHub and operator settings.
