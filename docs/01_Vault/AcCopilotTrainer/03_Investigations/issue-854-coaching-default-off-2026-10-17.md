---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-17
updated: 2026-10-17T05:10:00Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/854
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# #854 Part A — coaching inference defaults reconciled after RTX3050 removal (PR #865 MERGED `8cd5c30`)

## Context

The RTX3050 inference rig was removed 2026-10-16 (#854) with no qualified replacement.
Part B (lap-save) already shipped in PR #863/#864. Part A was the retained follow-up:
the normal startup consumers still baked the **abandoned** `localhost:11435`/RTX3050
service in and defaulted model coaching **on**.

Before this PR, both normal consumers seeded `AC_COPILOT_INFERENCE_ENABLE=1` plus the
retired `11435` base/health URLs and the 3050 GPU UUID:
- `tools/ai_sidecar/coaching/generation.py` → `RIG_DEFAULTS` (Game Point / rig launcher
  via `apply_rig_inference_defaults`, consumed in `supervisor.sidecar_environment()`).
- `src/ac_copilot_trainer/start_sidecar.bat` (CSP/Lua `ws_bridge.lua` auto-spawn path).

## Change (PR #865)

- Default `AC_COPILOT_INFERENCE_ENABLE=0` (rules-only / deterministic CPU brain) in both
  consumers; stopped seeding the retired `11435` base/health URLs and the 3050 GPU UUID.
- Preserved the bounded generation profile (finite caps) and explicit operator opt-in
  (incl. the legacy `AC_COPILOT_OLLAMA_ENABLE` alias). `RIG_GPU_UUID` kept only as the
  attestation fixture for tests / an operator-configured health endpoint.
- Re-enabling model coaching stays supported but now requires the operator to supply a
  separately approved backend contract (provider, loopback base/health URL, model,
  GPU attestation). The #855 admission mechanism is untouched, so the enabled-model
  acceptance goal stays open.
- Docs: `docs/10_Development/15_Local_Inference.md` records the retirement + re-enable
  contract.

## Acceptance (#854 Part A)

- **A1 defaults** — satisfied. ENABLE=0 at merged HEAD; default-off makes no model HTTP
  call (feature short-circuits → no unnecessary localhost retry); operator config + CPU
  brain preserved. Inference can never silently fall back onto the main RTX3060.
- **A2 regression** — satisfied at the distributed Python consumer (5 tests green at
  merged HEAD) **and live-verified on the rig** (operator authorized runtime + rig access
  2026-10-17): see "Live on-rig verification" below.
- **A3 keep-open** — honored. #854 remains OPEN; `Refs #854` (no closing keyword).
- **A4 preserve** — honored. Diff touches only defaults/docs/tests; archives, rig lock,
  GPU health logging untouched; NVIDIA 0x133 remains unproven.

## Review / merge

PR #865, author-vendor `anthropic`. Self-hosted daemon verdict **satisfied** on exact
head `190b027`: Antigravity (google) + Grok (xai) `reviewed_clean`, zero body findings;
cursor lens quota-exhausted, kimi not-reviewed; floor 1 met. Required CI green
(build/docs/conformance), 0 unresolved threads. Squash-merged `--match-head-commit` →
`8cd5c30`.

## Live on-rig verification (2026-10-17, operator-authorized)

The operator lifted #854's "no hardware/network/runtime" constraint and granted rig
access. Verified on **AG_PC** over SSH, driving the harness through
`tools.ac_harness.remote_launcher` (the Windows session-0 trap forbids a direct SSH drive).

- **Deploy:** pulled merged `main` into the rig's primary checkout
  `C:\Users\arsen\Projects\ac-copilot-trainer` (now `63209a6`); harness preflight reported
  `installed app provenance: match` — the CSP Lua junction serves exactly this deployed tree.
- **Inference OFF at the real consumer:** the auto-started sidecar (`build_commit 63209a6`)
  `/health` reported `inference.enabled=false`, `queue` empty, `provider=ollama`/`model=llama3.2`
  (the generic defaults — **not** the retired `openai`/`llama3.2:3b` rig profile), confirming
  the retired endpoint is no longer seeded. `netstat` showed **no connection to 11435** across
  both drives; 11435 is not even listening (RTX3050 service gone).
- **Launcher → sidecar → panel path live:** two bounded `auto_drive` runs.
  - bmw_m3_gt2@magione: AC launched+hijacked, drove 1102 m, HUD **RENDERING**, COACHING panel
    rendered live (hud.png shows the COACHING tile); the `--wait-lap` gate failed only on
    `present:lap` (no completed lap — known intermittent magione/ggv pit-start flake, coaching
    still went live). 3002 `coaching.snapshot` + 14 `coaching.cue` frames.
  - ks_porsche_911_gt3_r_2016@magione (reference-matched to the operator's loaded archive):
    **PASS** — completed **1 lap** (2728 m, 199.1 km/h, top gear 6, recoveries=0), `lap=1`,
    942 `coaching.snapshot` + 15 `coaching.cue` frames, HUD RENDERING. Inference still
    `enabled=false`, no 11435.
- **Capture limit:** the completed-lap on-glass *coaching-text* screenshot was contaminated —
  the operator's desktop (Codex app + other active sessions) was frontmost during that HUD
  capture (known "captures grab whatever is frontmost" rig-lore). The frame-count data proves
  the panel rendered coaching in-sim with inference off; a clean on-glass coaching-text shot
  during a completed lap was not captured because the desktop was in active use.
- **State restored:** closed the AC + sidecar the verification launched; `main` deploy left in
  place (that is the intended deploy); no rig config changed (operator env already had
  `INFERENCE_ENABLE=0`/`OLLAMA_ENABLE=0`).

Evidence bundles on the rig under
`.scratch/harness-evidence/verify854-drive{,2}-…/` (`report.json`, `hud.png`).

## Ownership boundaries (unchanged)

- Runtime scheduled-task disable/uninstall → workstation-ops#4004 (this source cleanup
  does not touch runtime tasks).
- Linux GPU/runtime/HA voice qualification → workstation-ops#4012.
- A later qualified server requires a separately approved deployment/access contract.
