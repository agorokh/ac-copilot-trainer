---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T16:50:38Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-051844Z-game-point-deployed-ac-stalled-294d91.md
  - AcCopilotTrainer/03_Investigations/issue-627-journal-scan-stall-2026-07-30.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Post-reboot live telemetry works with archive scan isolated; repair in review

Operator authorized reboot after SAVE, then Game Point and Porsche/Magione live
verification. Boot was freshly verified at 2026-10-12T13:57:44.500Z. C1 remains paused.
PR [#809](https://github.com/agorokh/ac-copilot-trainer/pull/809) repairs the acceptance
blocker under #804. Review, final deployment and normal-state live proof are pending.

## Observations

- Current Game Point EXE starts with all controls and START works. Health confirms
  build 90323fd / 2026-10-12T04:26:09Z, P7 browser peer 1 and COM6 screen peer 1.
- STABLE AC attempts and a direct Drive launch froze after reboot. RELEASE AC
  safely stopped the owned loop. No successful stable handoff was delivered.
- Removing trainer from Lua ACTIVE was an invalid isolation: its background script
  still initialized. That setting was restored. Do not use the result causally.
- Stock AC with CSP disabled stayed responsive: graphics packet 4769 -> 9127 in
  20 s. Restored the exact original general.ini bytes and extended-physics checkbox.
- CSP restored, trainer initially lazy/uninitialized: Drive stayed responsive.
  Opening trainer Settings connected Lua, then froze after `setup.list` arrived.
  An attempted WS overlay diagnostic timed out before any config was changed.
- `setup.list` scanned the whole journal and fully decoded telemetry once per
  unique setup row. The journal has 185 files / 523,854,502 bytes.
- Temporarily preserving the archive outside the scanned laps directory allowed
  AC + trainer + both original 3D overlays to stay responsive. In 20 seconds,
  graphics packet 7417 -> 10169, 227 telemetry ticks and 200 coaching snapshots.
- Actual USB screenshot: neutral, 900 RPM, 30.0 L fuel, tyres 80 C / 21.5 PSI,
  APPROACHING / NEXT T1 / target 193 km/h. This matches actual tick/coaching payloads.
  Physical rig-screen visual readback and changing controls remain unverified.
- AC closed during checks. All original archive files were restored to laps;
  SHA256 sets matched before/after restoration. The empty diagnostic output
  directory was preserved separately; no user files were deleted or overwritten.

## Repair and verification

Metadata projection retains car/track/setup/lap JSON only. It checks root framing,
escaped strings and selected metadata. Telemetry sample values are intentionally
not decoded/validated for setup BEST. Numeric arrays use a C balanced scan only
when they contain no quotes or object delimiters; otherwise the general scanner
handles framing. A 64 KiB metadata ceiling fails closed.

Setup BEST consumes one metadata scan per list request, retaining strict setup
paths, legacy snapshot paths, layout compatibility, validity and finite positive
lap times. No cross-request cache can hide a newly archived lap.

56 focused tests pass under Lua 5.1 and LuaJIT 2.1. On all 185 real files, every
metadata value matches Python's full JSON decode. LuaJIT reads/projects the corpus
in 1.022 s; JSON decoder input totals 128,601 bytes, max 2,005 bytes per decode.
The earlier full CI run passed; final-head CI and independent review remain pending.

## Resume

Finish #809 review/CI/final enforced gate, merge, sync primary, and verify installed
Lua provenance. Then relaunch Game Point/Porsche with the full archive present,
require advancing packets/ticks, compare on-device P7 pixels, and obtain physical
ESP32 rendering confirmation. Do not count diagnostic archive isolation as final
normal-state acceptance. Keep #804 open until its retained live clauses pass.

Ignored evidence in .scratch/rig-restore: live-readback-isolated-journal.txt,
tablet-live.png, metadata-benchmark.json, journal-restored-hashes.json, diagnostic
CSP logs and prior freeze captures. Tier-3 direct tool unavailable; canonical
SessionStart task-specific prefetch succeeded. No token values were logged.
