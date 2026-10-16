---
type: handoff
status: active
created: 2026-10-16
updated: 2026-10-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Issue 86: physical acceptance checkpoint

**BLOCKED on physical touch/photo evidence; no delivery or closure claimed.**
Operator invoked autonomous-deliver86. Live issue is OPEN, labels enhancement,
epic, phase-5, python; stale body mentions of not-this-cycle are not live labels.
Controlling decision1C retains only the four-leg device smoke/photo gate.
PartF was split to677 and is not reopened. Current813 is CLOSED, not a residual owner.

Owner decision record:
https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6218931168

## Observed readiness

At2026-10-16T15:33–15:35Z, Windows present-device enumeration returned ESP32
COM6 and P7 as OK. `adb devices -l` returned one authorized P7,
serial1c000c75b543099221d. Camera/Image-class Windows inventory returned no device;
this does not establish absence of cameras on other devices.

Documented authenticated GET`http://127.0.0.1:8765/health`, with
X-AC-Copilot-Token sourced from user environment without outputting it, returned
status=ok,connected_peers=2,screen_peers=1,browser_peers=1,
build_commit=70ed2fe,build_time=2026-10-15T23:01:54Z.
Canonical `read_rig_session_owner(default_rig_session_lock_path())` returned None.
No AC/ContentManager/Steam/SimHub process appeared in the scoped process query.
Existing GamePoint processes3904/33628/2696 were preserved;2696 owns8765.
This run started no rig software and has no owned runtime to shut down.

Local evidence (gitignored, not a shared attachment): `.scratch/issue86/health.json`,
`readiness.json`, `rig-owner.json`, `decision-record.md`.
No `.operational-dod.json` exists in this checkout.

## Retained acceptance

| Clause / controlling requirement | Result | Exact next action |
| --- | --- | --- |
| Four-leg touch flow: Launcher → Copilot live hints → PT setup load → SE browse/download/install; installed setup appears in PT and loads | Unverified | Operator at ESP32, supported live AC session; observe touches and the installed setup's PT load acknowledgement. |
| Photograph/capture device against esp32_rig.png, Atelier tokens and glyph readability | Unverified | Obtain actual ESP32 photo/video and compare with docs/10_Development/design/racing-atelier-renders/esp32_rig.png. P7 screenshot or health is insufficient. |
| Record/attach verification artifact and observed result | Unverified | Attach actual device evidence on86; settle every clause from observed outputs before closure. |

Operator availability requested asynchronously; no answer/waiver received at checkpoint.
No physical camera/control path to the ESP32 has been established in this harness.
No flash, serial-port takeover, synthetic telemetry, setup installation, game launch,
or touch smoke was performed. Healthy serial connectivity is readiness, not UI acceptance.
Resume upon operator availability with actual touch/photo evidence; do not reimplement
already-shipped software or treat elapsed time as approval. Before any game launch,
follow current archive-preservation and rig-ownership procedures.

Tier3 descriptor briefly appeared after the initial unavailable-tool grounding;
actual task-specific query against ac_copilot failed with TypeError:
tools.mcp__agentic_memory__query_knowledge_graph is not a function.
Vault/live GitHub used, no bypass. Creation budget2; none created. No independent
finding filed. This new local SAVE is intentionally uncommitted while awaiting
the operator response, rather than claiming a completed/merged delivery.
