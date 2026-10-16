---
type: handoff
status: active
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-16-183012Z-post-merge-pr858-f2c9a1.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
---

# Issue 86: software checks and remaining runtime dependencies

Resume from [current owner evidence](https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6223694153).
Operator: continue86 using simulator, do software checks autonomously, involve
operator only for remaining physical checks. Author vendor OpenAI, Codex desktop;
underlying exact model ID unexposed. No agents spawned. Budget2 outside-assignment
creations; none used. Existing86 remains owner; no new issue. Source2189bd3, clean
before this dated SAVE. Tier3 ac_copilot query succeeded.

## Verified software

- Fresh permanent native run:40 assertions,10 PNGs inspected, actual production
  UI/fonts/config/LVGL8.3.11. Run20261016T195614Z-50bd41b1.
- Focused screen/protocol/serial/installer tests74 passed; sidecar/Lua/list/load
  tests157 passed, exit0. Lua batch emitted Windows exception diagnostics while
  tests continued; original log retained. No claim of physical serial proof.
- Separate loopback HTTP fixture through real WebSocket sidecar, real HTTP
  SetupExchangeClient and installer, actual production Lua setup_library listing,
  summary and loadByName resolver:passed. Exact installer path used; duplicate
  download created a distinct file without overwriting original. BB64/ABS2/TC3
  matched. Fixture remote service and CSP ac.loadSetup adapter are explicit limits.
- Supplemental scratch native probe reuses the production simulator source and
  production UI target, consumes that actual installed path, and checks install
  success→PT exact-path load→active name:59 assertions,12 captures inspected.
  Missing fresh reset-allowed state correctly refuses load. Long install filename
  intentionally ellipsizes; initial full-label oracle was corrected. This does
  not claim the permanent CI suite expanded beyond40 assertions.
- Compared current rendering with esp32_rig.png; fonts/layout inspected on PC.
  Real panel visibility/colour/touch and on-glass photo comparison remain separate.

## BLOCKED live verification; do not call all software complete

`gh issue view 86 --repo agorokh/ac-copilot-trainer --json state,labels` returned
OPEN; enhancement/epic/phase-5/python. Historical body label text is not live labels.
Decision1C retains four-leg on-device flow plus on-glass photo. All rows remain
in the linked owner checkpoint, including unverified live/physical rows.

Live authenticated loopback hello succeeded; se.search.result returned ok=false:
default Setup Exchange endpoint requires CSP session auth; set
AC_COPILOT_SE_ENDPOINT to an authenticated proxy/test endpoint. Documented source:
14_Game_Point_Launcher.md Setup Exchange and se_proxy.py SetupExchangeClient.
Process/User/Machine environment and launcher settings have no endpoint configured.
Installed official SetupExchange.lua confirms signed /session handshake; the
sidecar intentionally does not implement it. No authentication bypass tried.
Asked operator for an existing authenticated proxy endpoint; no answer at SAVE.
An isolated fixture pass does not discharge this production dependency.

Sidecar health:ok,build70ed2fe,screen_peers1,browser_peers1; voice observer-only.
Initial rig ownerNone; canonical GamePoint Stable AC request later refused
busy_other_session,presentmon-qualification. Fresh owner20:03:27Z:PID23960,
session_kind presentmon-launch-retry,phase normal launcher after Steam initialization.
Peer ownership preserved. No AC process started or stopped by this run; no flash.

Next: use existing authenticated endpoint if supplied; rerun actual browse/download
readback. Once rig ownership is free, agent verifies live hints and in-game
setup list/load through normal GamePoint/CSP path, preserving user setups. Only
then request physical touch/readability/photo. Earlier operator-confirmed
CONNECTED/all-three/Back navigation remains dated evidence, not a new request.

## Evidence and hygiene

All fixture writes are under .scratch/issue86/software-roundtrip-20261016T200003Z/
Documents/Assetto Corsa/setups, never the user's setups. HTTP fixture listener and
thread closed. Existing GamePoint and peer rig apps preserved; no owned rig app
to shut down. No .operational-dod.json. No source/config/credential mutation.

Local logs:continuation-tests.log,handoff-tests.log,live-se-readback.json,
continuation-health.json,continuation-rig-owner.json under .scratch/issue86/.
HTTP/Lua results:software-roundtrip-20261016T200003Z/results.json. Native probe:
native-acceptance/test.log,captures/results.json; twelve rendered captures.
No new independent finding filed or task created. SAVE is an own vault-only PR.
