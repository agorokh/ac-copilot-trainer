---
type: decision
status: active
created: 2026-10-16
updated: 2026-10-16
relates_to:
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-16-200530Z-issue86-software-checkpoint-5d2b8a.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# Setup Exchange uses the trainer's native CSP session

Owner [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86), implementation
[PR #862](https://github.com/agorokh/ac-copilot-trainer/pull/862). The operator clarified
that the working in-game Setup Exchange experience must extend to the rig screen:
community setups, their authors, download/install and application to the current car.
The earlier proxy configuration question is superseded; a separate proxy is not an
operator prerequisite for the normal path.

The trainer's `setup_exchange.lua` uses the official app's fixed community endpoint
over HTTPS and supported CSP machine-key signing/session APIs. It does not patch or require the
installed third-party app. This follows the original per-app isolation decision.
Signing material and service session IDs stay within CSP. The module only returns
whitelisted public setup metadata and bounded INI data.

The screen's public `se.search`/`se.download` frames remain unchanged. The sidecar
selects exactly one authenticated trainer Lua connection and correlates private
`se.csp.request`/`se.csp.result` frames to the originating connection and operation.
Bounded background tasks keep the serial reader and heartbeats responsive while
HTTP/signing callbacks complete. Timeouts, disconnects, stale car/session context
and ambiguous trainer connections fail closed. Public result/ack frames supplied
by clients are rejected instead of being broadcast into the screen's auto-load path.

The existing Python installer remains the only writer: approved setup root, bounded
data, exclusive creation and no overwrite. Application still uses `setup_library`
and its pits/reset permission. A nondefault `AC_COPILOT_SE_ENDPOINT` preserves the
existing custom proxy/test path; the default uses native CSP.

Checkpoint: the permanent production-UI simulator passes61 assertions and13
captures, including author, failed service, installed acknowledgment and exact-path
Pocket Technician load with permission gating. The affected PNGs were inspected.
The new broker/provider/protocol integration batch passes72 tests, including a
real WebSocket→production Lua dispatch/provider→safe installer round trip with
explicit CSP signing/HTTP adapters. Broader CI and real CSP/service verification
are still pending at this checkpoint; no live success is inferred from adapters.

Author vendor OpenAI, Codex desktop; exact model ID unexposed. Two bounded in-run
helpers (`csp_setup_exchange_lua`, `csp_setup_exchange_sidecar`) returned their
assignment-only results, created nothing and touched no rig. No independent issue
or task created. Draft861 was replaced by862 because repo policy rejects the
desktop-default codex/ branch prefix; the delivery now uses feat/.

No firmware was flashed. The simulator/pre-upload prerequisite remains mandatory
before every future firmware write. Issue86 remains open for its retained real
device smoke and on-glass photo acceptance. Real service/runtime proof precedes
any further request for operator touch or camera help.

Council run0d2a67379c4a49398c66241e8e3efa11 reached3/3 quorum (Gemini,
Mistral, Kimi; three other providers unavailable). Adopted the concrete transport
finding: the new client uses HTTPS. A certificate-verified HTTPS request reached
Cloudflare and returned403/1010, as did anonymous HTTP; this is transport proof,
not signed-service proof. Live CSP remains required. The overall Lua20-second
deadline spans auth and retry; the sidecar independently expires and cleans the
request after45seconds even if frames stall. Timeout/late-result, disconnected
requester, identity-spoof and duplicate-install tests pass. Existing collision
suffixing preserves originals. The synthesis rejected speculative HMAC, hardware
attestation and host-throttling redesigns; they are not new acceptance obligations.

First full local run failed because the scratch C compiler was absent from PATH,
blank host inference-disable environment values leaked into tests, and source
changed to HTTPS after pytest collected the old expectations. These are not passes.
The final run adds the existing scratch native compiler, removes host AC_COPILOT
configuration only within the test process and holds source stable. CI retains
its normal Linux toolchain and environment. No host settings were changed.
