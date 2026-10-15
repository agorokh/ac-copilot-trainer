---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-15
updated: 2026-10-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-181458Z-operator-driven-rigcheck-f3b1cc.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-15-030700Z-post-merge-pr851-c3b1.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Issue 804: original physical proof reconciled with current deployment

## Authority and scope

The operator invoked autonomous-deliver 804. Live labels are bug/python, with no
paused, blocked or not-this-cycle gate. Its creation budget is zero independent
issues, chats or helper agents; only the assigned vault SAVE PR is needed.
The six original clauses remain governing. The #813 small-screen waiver does not
apply to #804. No new product implementation or firmware flash is indicated.

## Direct observations, October 15

Original phone media remains at `C:/Users/arsen/Downloads/IMG_8761.MOV`: 149.190 s,
3840x2160 HEVC, 858275869 bytes, SHA256
`f10af1d82eb1d4b92a981cdd0cd881fd65cb8e71fa500b8c9216a8c3977c2981`.
Freshly decoded frames at 104 and 108 seconds were inspected this session:

| Video time | Game speed | Physical ESP32 speed | Physical P7 speed | Game/P7 gear |
|---|---:|---:|---:|---:|
| 01:44 | 109 km/h | 107 km/h | 108 km/h | 2 |
| 01:48 | 170 km/h | 170 km/h | 169 km/h | 4 |

The changing actual small-screen digits prove consumption and rendering in the
October 12 operator-driven session. They are stronger evidence than a socket count.
Small asynchronous display differences are visible, rather than exact frame locking.
The wrap/action/electronics defects visible in that recording were explicitly
assigned to #813; this does not certify new firmware pixels or waive that history.

Current installed `/health` readback is status=ok, build_commit=1282a9d,
build_time=2026-10-15T03:02:13Z, connected_peers=2, screen_peers=1, browser_peers=1.
The Desktop shortcut targets the primary checkout's `dist/AC-Copilot-Game-Point.exe`;
its SHA256 is `63d93b628a84c3d840de7a5ef504aed249b9eb2e6e5a1ff3dd0a046004a1bf63`.
Actual 878x700 installed-window pixels show START, all eight current actions and
all eight current status rows without clipping. Seven was the original action count;
the later offline-report control also fits. No resize was performed for this capture.
The already-running launcher/sidecar and SimHub predate this session's UI inspection
and are preserved. No AC session, driver, capture daemon or support app was started.

## Retained acceptance and verdict

| Clause | Controlling requirement | Settled status and evidence |
|---|---|---|
| 804:1 | A fresh Game Point launch shows the yellow START button, all seven actions and all status rows without manual resizing; minimum-size behavior preserves visible actions. | Verified: original PR805 launch proof plus current installed pixels; both actual Tk scaling/minimum-size tests pass. |
| 804:2 | The launcher remains resizable and uses one sizing implementation for production and its visual preview. | Verified: PR805 commit 420eeb1 app.py/preview.py both call LauncherView.fit_window; current layout tests pass. |
| 804:3 | Build and install the current EXE on the rig; verify its live build identity, fresh-launch layout and normal START path. | Verified: earlier normal START proof retained; PR851/852 installed consumer evidence plus current build/hash/shortcut and running window. |
| 804:4 | Launch AC with the installed trainer, prove advancing live telemetry, and reconcile dashboard readings against that telemetry. | Verified historical real run: original 1154 ticks, 962 snapshots, packet 9183 to 22858 and device recording; subsequent #531 exact-session proof retained separately. |
| 804:5 | Verify live rig-screen consumption and actual rendering; distinguish transport proof from visual confirmation if physical pixels require the operator. | Verified historical physical video: 107 to 170 km/h on ESP32 while game/P7 change alongside it. Current peer count is transport proof only. |
| 804:6 | Local CI and review pass, and the verified deployment state is retained in a dated vault handoff. | Product CI/review and prior SAVEs retained; this reconciliation is verified through local vault CI and its own governed SAVE PR before owner closure. |

PR805 MERGED 420eeb1 and PR809 MERGED e4bb25c are confirmed by fresh tracker reads;
bestForSetups exists at e4bb25c. Do not rebuild these shipped fixes. PR851 MERGED
1282a9d and PR852 MERGED 4a7cc26 preserve current distribution and P7 evidence.
All original outcome predicates are evidenced; close #804 after this SAVE merges.
No new physical-lap run is needed solely to repeat already-retained acceptance.

## Verification and limits

Canonical ac_copilot prefetch was attempted in naive and local modes; both returned
non-2xx application responses and exhausted the degraded budget. No agentic-memory
MCP tool is exposed and no gate bypass was used. Work remained non-code, grounded
on vault/live evidence. Python pytest layout tests: 2 passed. Full make ci-vault passed: 91 passed,
3 declared skips with an isolated cache temp root outside Git. Earlier local attempts
failed shared-temp cleanup, the nested-Git assumption and a missing cache parent;
none is counted as passing and no test was removed. Raw captures, original
telemetry and fresh whitelisted health/hash readbacks remain local under
`.scratch/issue804/` and the preserved 0224 worktree's `.scratch/rig-restore/`.
No secrets or raw personal media are committed. No operational-dod state file exists.
No issue, chat or helper agent was created; no independent finding was filed.
