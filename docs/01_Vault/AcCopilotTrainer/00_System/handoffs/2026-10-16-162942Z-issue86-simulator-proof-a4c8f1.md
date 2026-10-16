---
type: handoff
status: active
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-16-153556Z-issue86-physical-acceptance-be60a7.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
---

# Issue86: operator navigation pass and native simulator proof

Operator returned to the rig and confirmed: "All three work; CONNECTED" in response
to checking Launcher→each of Copilot/PT/SE→Back on the actual small ESP32.
That is an operator-observed navigation/connection PASS, not setup/live/photo proof.
At16:22:57Z fresh health remained ok,screen_peers1,browser_peers1,build70ed2fe;
canonical rig owner None. GamePoint was inspected using the computer-use skill.
No game was started and no firmware flashed. Existing GamePoint preserved.

Operator then redirected work: reduce manual testing burden, find an emulator
for this exact screen and test before flashing. Manual walkthrough stopped.
This is a preflash verification request, not a waiver of retained86 physical acceptance.

## Actual prototype outcome

Built an isolated native/headless LVGL8.3.11 prototype at
`.scratch/issue86/simulator/`, using unchanged production UI cpp/generated fonts
and the actual firmware lv_conf.h,320x480 portrait,RGB565 swap settings and64KiB
LVGL pool. Existing VS Build Tools2022 was discovered via vswhere; no installation.
Cached LVGL8.3.11 source is read from primary checkout's PlatformIO libdeps.
Native HAL stubs cover Arduino time/Serial/ESP heap and in-memory Preferences;
MSVC-only C font linkage and strncasecmp adapters do not change firmware source.

`issue86-ui-probe.exe` exited0 with24 assertions (including label preconditions):
pointer hit testing opens all3 tiles and Back; real renderer BRAKE/UPSHIFT/stale;
1250m label; PT emits exact setup.load name/path; SE emits actual download queue
request; download failure label appears; launcher reports connected/disconnected.
Fixtures are synthetic UI data. No sidecar/serial/AC or actual HTTP/install performed.
Corrected initial fixture lower-case action and stale delay to actual protocol/timeout;
those were harness mistakes, not firmware defects. Final screenshots were inspected.

Evidence: local `.scratch/issue86/simulator/{README.md,probe-results.txt,build.log,
simulator-proof.png}` and8 individual framebuffer captures. Scratch-only prototype
is runnable but not a committed/published/CI-integrated simulator feature.
No source diff. No new issues, PRs or agents. Both handoffs remain uncommitted.

Canonical Tier3 prefetch was subsequently recovered using the existing
`scripts/hook_session_start_memory_prefetch.py` with task-specific CLAUDE_LOAD_PROMPT.
It successfully queriedac_copilot and returned prior Phase2 LVGL/Canvas/navigation
decisions. No gate bypass or hand-written stamp. This supersedes earlier tool absence
as the current memory-access state; initial direct tool TypeError remains historical.

## Research and coverage boundary

LVGL officially supports real UI PC simulation for8.3:
https://lvgl.io/docs/open/8.3/get-started/platforms/pc-simulator
Wokwi's current supported hardware lists ESP32-S3 but not AXS15231B displays:
https://docs.wokwi.com/getting-started/supported-hardware
Board-named browser candidate https://59jag59.github.io/Simulateur-arduino_gfx/
documents Arduino drawing-code transpilation to JS; our full LVGL firmware support
was not established. No exact MCU+QSPI+touch-controller emulator is claimed verified.

86 remains OPEN: physical live hints, real PT load, SE install→PT load and device
photo/glyph evidence remain unverified. Prototype cannot discharge those rows.
Next implementation can promote the source-reusing simulator into a repeatable
preflash/CI check under86, then reserve operator work for residual hardware proof.
