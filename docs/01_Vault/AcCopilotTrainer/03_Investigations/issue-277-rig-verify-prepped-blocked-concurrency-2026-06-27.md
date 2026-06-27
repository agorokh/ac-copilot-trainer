---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-27
updated: 2026-06-27
issue: https://github.com/agorokh/ac-copilot-trainer/issues/277
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/stanley-steering-live-verified-2026-06-19.md
---

# #277 live brain-debrief rig-verify — PREPPED, paused on rig contention (2026-06-27 eve)

`/autonomous-deliver 277` on **AG_PC**. The #277 *code* shipped in **PR #321** (merged `8d9eb97`);
the only remaining acceptance is the **rig-verify** (drive a lap → confirm the live
`debriefSource==brain` `coaching_response` with `cornerAnalysis`). PR #321 deliberately left #277
**open** until that observed run exists.

## Post-merge #321 classification (clean)
Diff: `ac_copilot_trainer.lua` (+107, deferred `brainOnly` lap_complete + hoisted `lapPayload`),
`ws_bridge.lua` (+103, `debriefSource==brain` cornerAnalysis tile render), tests (+183), a protocol
doc, and two minor governance hooks. **No migration / env / deps / workflow flags.** (CodeRabbit had
already caught + fixed the block-scoped `lapPayload` bug that dropped `event=="lap_complete"` from the
deferred frame — so my live test specifically exercises that fix.)

## Verification harness — fully prepped (one-step resume)
- **Custom-AI surfaces** reconstructed at `.scratch/part-g/surfaces_customai.ini` (stock magione
  `surfaces.ini` + `[SURFACE_0] WAV_PITCH=extended-0` + `[_EXTRA_PERMISSIONS]
  ALLOW_CUSTOM_AI_MANIPULATION=1`, CRLF-correct). `new_behaviour.ini [CUSTOM_AI] ENABLED=1` added
  (backup at `.scratch/new_behaviour.ini.bak-issue277`).
- **Drive script** `.scratch/issue277_drive_laps.py` — vetted against tracked source; uses the PR #248
  `RacingDriver.from_human_profile` Stanley path, mirrors `RacingDriver.run` exactly (step/write_controls
  arg order, position-return lap counting, teleport-to-pits cleanup, never writes clutch). Byte-compiles.
- **Capture harness** `.scratch/issue277_live_verify.py` — wired: `DRIVE_SCRIPT` → `issue277_drive_laps.py`,
  Ollama disabled (it's down; brain path is deterministic), leaves AC up for the HUD screenshot. Its
  `_analyze` asserts exactly #277: a `lua_to_sidecar` `lap_complete brainOnly=true` AND a
  `sidecar_to_lua` `coaching_response debriefSource==brain` with non-empty `cornerAnalysis`. Launch
  uses direct AC shared-memory `read_status_oracle` (daemon-free).

## Why paused (not done): single-rig contention
AG_PC has **one** AC instance. A concurrent autonomous session — **"Autonomous delivery testing in
Assetto Corsa"** (worktree `flamboyant-poincare-b469d9`) — was **actively** driving the rig
(its own `tools.ai_sidecar` on :8765, `acs.exe`, and `ws_dump.py` imola/mugello lap captures across
Audi R8 / Corvette). Two autonomous drivers cannot share one sim. Per fleet discipline I **yielded**:
killed **no** peer process, and **restored magione `surfaces.ini` to stock**. Serializing the two
rig sessions is an operator decision.

Note: my harness's CM/acs launch-retries (13:16–13:19) almost certainly caused the **transient
`ConnectionResetError`/`ConnectionClosedError`** seen in the peer's `sidecar.log` (Lua peer dropped,
sidecar recovered) — another reason to yield. The peer's `setup experiment record failed … missing
setup.snapshot` is a separate concern (#114 setup-experiment recording), **not** the brain path
(`build_brain_followup` reads the trace, not `setup.snapshot`).

## Resume recipe (when the rig is EXCLUSIVELY free)
1. Confirm no peer `acs.exe` / `ws_dump.py` / extra `tools.ai_sidecar` on :8765.
2. Re-run `/autonomous-deliver 277`, or directly from repo root:
   `python .scratch/issue277_live_verify.py` (re-applies custom surfaces, launches AC 911 GT3 R @
   magione via the CM preset, drives 2 laps, captures, restores surfaces, leaves AC up).
3. Success = newest `.scratch/issue277-live-*/summary.json` `analysis.ok==true` AND
   `proxy_frames.jsonl` shows `debriefSource==brain` + non-empty `cornerAnalysis`. Screenshot the AC
   HUD brain tiles. Then post evidence + `gh issue close 277`.
4. Watch in the clean run: does the brain follow-up actually **fire + succeed** (the peer's run never
   showed a brain success in its log — but its `ws_dump` only taps broadcast topics, so absence there
   is not evidence of failure). Restore `new_behaviour.ini` from the backup when fully done.

## Concurrency learning (fleet)
Before any rig run on AG_PC, check for a peer session holding AC: `acs.exe`, a non-self
`tools.ai_sidecar` on :8765, or `ws_dump.py`/drive scripts under another worktree's `.scratch/`.
Autonomous sessions must **serialize** AC access; the all-in-one harness's CM/acs kills will disrupt a
peer mid-drive.
