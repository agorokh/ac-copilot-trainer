---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T18:14:58Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-174325Z-post-merge-pr809-dc1d25.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
---

# Operator-driven telemetry and USB video verified; AC intentionally exited

The user supplied rigcheck.zip with four photos, correctly observing that the
earlier session only idled. They then confirmed they could drive and manually
drove Porsche 911 GT3 R 2016 at Magione. C1 autonomous driving remains paused.
No autonomous controller or scientist run was started.

## Physical photos

IMG_8757 through IMG_8760 show the cockpit/tablet idling in N at 900 RPM.
The small ESP32 screen is physically rendering T1, speed 0, CLEAR and roughly
98 m to braking, consistent with the earlier live coaching payload. This
closes the earlier lack of any on-glass evidence, but is a static observation.
Current firmware deliberately shows CLEAR when speed is below the target;
see screen_ac_copilot.cpp command_for_snapshot. It does not mirror the
tablet's primary APPROACHING text as its large command label.

## Driven verification

- AC PID 7636 was responsive, started 2026-10-12T18:06:16Z; live build remains
  6d2e1ee / 2026-10-12T17:15:20Z. Screen and browser peers stayed registered.
- Initial 20 s: 229 telemetry ticks, 163 coaching snapshots; packets 4953 -> 7331.
  Throttle 0..100%, brake 0..38%, speed roughly 1..30 km/h; T2 -> T3.
- Longer observer capture: 1,154 ticks and 962 snapshots, graphics 9183 -> 22858.
  Speed reached 184.175 km/h; RPM reached 8,813.48; gears 1 through 5;
  throttle 0..100%, brake 0..90.29%. T4 through T8 and approaching,
  in_corner and cruising states all appeared. No protocol error frames.
- Commands changed among APPROACHING, CARRY MORE SPEED, EASE OFF, ON PACE
  and SHIFT UP. Tyre temperatures/pressures changed on the actual tablet.
  Fuel stayed at 30 L in this session; do not claim fuel-consumption proof.
- Actual Android H.264 screenrecord saved locally: 1024x600, 148.06 s,
  5,905,271 bytes. This is device video, not a synthetic render.
- Video at 85 s: lap clock 2:00.47, 37 km/h, gear 2, 2,316 RPM, brake 65%.
  Nearest observed tick at 120474 ms: 37.020 km/h, gear 2, 2315.569 RPM,
  brake 0.652493, throttle 0. The displayed rounded values match.
- Video at 99.75 s: 183 km/h, gear 5, 6,809 RPM, full throttle, NEXT T6,
  ON PACE. This demonstrates changing dashboard readings during driving.
- Completed laps remained zero: this proves a driven segment, not a completed lap.
- Dashboard subsequently showed STALE with live fields cleared. The user
  explicitly confirmed they exited AC; do not attribute this exit to a crash.
  AC is now stopped intentionally. Sidecar, USB tunnel and physical peers remain.

## Remaining and resume

An async question asks whether the small screen's speed/corner/braking distance
changed during driving; that dynamic physical readback is still unconfirmed.
Keep #804 open until its remaining physical clause is resolved. Static rendering
and actual USB dynamic readings are now evidenced; do not reduce this to peer count.

Stable AC automatic Drive remains unresolved as recorded in the preceding handoff.
This drive used the operator's manual session. Preserve the C1 pause and external
racing-control plan, SimHub endpoint ownership and manual settings changes.
No firmware, GPIO mapping or audio setting was changed by the agent.

Ignored evidence under .scratch/rig-restore: user-rigcheck-20261012/IMG_8757.jpeg
through IMG_8760.jpeg, tablet-user-driven-20261012.mp4, dynamic-first-20s.json,
dynamic-telemetry.json, dynamic-verification-summary.json, live-readback-user-driving-1.txt,
live-readback-user-driving-full.txt, tablet-dynamic-map.png, tablet-dynamic-race-1.png,
tablet-dynamic-race-2.png (STALE), tablet-video-85s.png and tablet-video-100s.png.
The original ZIP remains in Downloads; the device recording is retained in Android
Download. Raw personal captures were not committed or attached to GitHub.
Canonical task-specific Tier-3 prefetch succeeded. Post-merge #810 classification
has no flags; primary retained deployment identity from the preceding SAVE.
