---
type: handoff
status: active
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-16-162942Z-issue86-simulator-proof-a4c8f1.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
---

# Issue 86: permanent native simulator and pre-upload gate

Operator explicitly requested permanent repository/CI integration, agent testing
before every flash, and operator involvement only for physical hardware checks.
Owner86; branch fix/issue-86-permanent-screen-simulator; Refs86 rather than closes.
Paginated open-PR enumeration was empty at start. Issue117 explicitly excludes
ESP32 work; no separate issue needed. Creation budget2; no new carrier/task/agent.
Canonical ac_copilot prefetch succeeded with task-specific simulator/gate context.

Implemented production-source LVGL8.3.11 CMake/CTest suite, SHA256-pinned archive,
Windows/Linux runner, fresh timestamped PNG/report/HTML evidence, source/BIN binding,
required makeci-fast integration and CI artifact retention. PlatformIO serial and
legacy WS environments inherit the pre-upload action; no skip/cached-pass switch.
AGENTS and runbooks assign UI testing and image inspection to agents, preserving
the panel/touch/MCU/serial/NVS/actual-install coverage boundary.

Actual Windows native run passed40 assertions with10 rendered captures; images
inspected. WAIT initially displayed invented0km/h with no telemetry; production
condition now requires has_data/current_speed_available and regression asserts
no false zero. Seven Python evidence/upload-action tests passed.

Actual PlatformIO-bundled SCons was exercised with a harmless fake upload alias:
missing fake BIN caused the real pre-upload callback to abort, marker absent;
present fake BIN ran40 native assertions, then fake uploader marker appeared.
No serial port, AC or real flash used. Evidence at local .scratch/issue86/
upload-gate-probe and .scratch/screen-simulator/runs/20261016T172853Z-7af0255e.
Fake-BIN SHA256 d25460bfb56c220163c91385f2b2e02ac863117fa831b652daa7b8a11bd07890.
This proves action ordering, not physical firmware installation.

Full makeci-fast is running at this checkpoint; CI/review/merge still required.
Initial Windows basetemp quoting created repo-local test temp; that owned run was
stopped and preservation-moved under .scratch; rerun uses forward-slash outside-Git
cache path. No unrelated process/state was stopped. Normal Temp ACL trouble is
avoided via explicit basetemp. Older dated notes retain their historical scope.

86 physical acceptance remains open beyond operator-confirmed navigation:
real live hints/PT load/SE install round trip and on-glass evidence. The simulator
does not waive these. Preserve existing active GamePoint; no rig app started here.
