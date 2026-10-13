---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-13
updated: 2026-10-13
last_updated: 2026-10-13T02:47:44Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/813
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-13-021316Z-post-merge-pr814-09f346.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-034900Z-rig-dashboard-control-d326a9.md
---

# Agent-owned display recording: physical capture blocked by disconnected inputs

The operator directed the agent to record on-screen verification itself,
including Android. Capture ownership stays with this delivery. Issue 813 is
OPEN, labels bug/enhancement/python; no extra issue or independent task created.
Task-specific Tier-3 query succeeded in ac_copilot. Prior review waiver remains
specific to PR 814. PR 817 merged normally as ca04153, local main was synced.

The installed Game Point was opened with the computer-use skill. Its actual
window showed PRESS START, SIDECAR STOPPED and TABLET NO-DEVICE. Clicking its
normal START button changed it to READY TO DRIVE, SIDECAR HEALTHY and SCREEN
CONNECTED. No AC session or driving was started and no settings were changed.
Local launcher-start.mp4 is 20.0 s, 876x528, 50,246 bytes and captures the
stopped state before the click. launcher-ready.mp4 is 10.0 s, 876x528,
41,271 bytes and captures the healthy connected state. Frames at 18 s and
8 s respectively were decoded and inspected, as were before/ready screenshots.
The transition itself is bracketed by screenshots, not recorded in video.
These are launcher pixels only.

Authenticated documented user-environment /health at 02:46:38Z returned 200,
build_commit 0a2559f, screen_peers=1 and browser_peers=0. COM6 retains VID/PID
303A:1001 and serial 3C:0F:02:CF:5A:20. This establishes the real screen's
connection, not its physical pixel correctness. The sidecar remains running
through the installed launcher, ready for the tablet to reconnect.

Actual commands adb devices -l and adb mdns services both returned only
headers, with no devices or discovery endpoints. The documented USB P7 method
was attempted; capture_tablet.py refused before recording because zero
authorized devices were found. ffmpeg -list_devices true -f dshow -i dummy
reported no video devices; Windows PnP Camera/Image inventory was empty.
Remote Desktop Commander lists only an offline Mac Studio, no alternate
connected capture device. No synthetic render substitutes for physical proof.

BLOCKED: Android capture requires the P7 reconnected by USB; ESP32 on-glass
capture requires an available camera pointed at the small display. The agent
asked for those connections asynchronously and will perform the captures,
inspect frames and reconcile live values when the inputs become available.
Read-only observer plus 180-second real Android scrcpy recording is prepared
in the local capture helper; its connected-device path remains unexercised.
All local evidence, attempt logs and SHA256 manifest are under
.scratch/issue813/physical-20261013/. No media or credentials were uploaded.
Retain issue 813 C:1 on-glass proof and E:2 operator-driven valid Porsche 911
GT3 R/Magione completed lap, live electronics/action/target agreement, moving
numbered/segmented MAP, real lap comparisons, intentional AC exit and both
stale transitions. No physical clause is upgraded by launcher recording.
