---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-17
updated: 2026-10-17
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
- **A2 regression** — satisfied at the distributed Python consumer. 5 tests green at
  merged HEAD (`test_default_off_makes_no_model_http_call_but_keeps_rules` asserts a
  raising `urlopen` is never called; Game Point launcher env defaults off and drops the
  retired endpoint). **Coverage limit:** the live Windows-rig launcher → CSP → on-glass
  panel glance is an operator rig action (standing "merge ≠ rig deploy" invariant), not
  reachable from the macOS delivery session.
- **A3 keep-open** — honored. #854 remains OPEN; `Refs #854` (no closing keyword).
- **A4 preserve** — honored. Diff touches only defaults/docs/tests; archives, rig lock,
  GPU health logging untouched; NVIDIA 0x133 remains unproven.

## Review / merge

PR #865, author-vendor `anthropic`. Self-hosted daemon verdict **satisfied** on exact
head `190b027`: Antigravity (google) + Grok (xai) `reviewed_clean`, zero body findings;
cursor lens quota-exhausted, kimi not-reviewed; floor 1 met. Required CI green
(build/docs/conformance), 0 unresolved threads. Squash-merged `--match-head-commit` →
`8cd5c30`.

## Ownership boundaries (unchanged)

- Runtime scheduled-task disable/uninstall → workstation-ops#4004 (this source cleanup
  does not touch runtime tasks).
- Linux GPU/runtime/HA voice qualification → workstation-ops#4012.
- A later qualified server requires a separately approved deployment/access contract.
