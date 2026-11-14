---
type: decision
status: active
created: 2026-06-12
updated: 2026-06-12
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/154
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
  - AcCopilotTrainer/03_Investigations/pr-75-ollama-corner-coaching-protocol.md
  - AcCopilotTrainer/03_Investigations/lua-telemetry-trace-replay-testability.md
---

# Decision: autonomous self-test harness (agent test-drives the trainer, no human in the loop)

## Context
Every meaningful change to the trainer is validated by a **human driving a lap in Assetto Corsa**.
That manual loop ("agent says done → operator drives → it's broken → repeat") is the dominant cost and
the reason this repo moves slowly. Goal: let the **agent** test-drive the trainer itself, in iterations,
the way the HermesCraft (Minecraft) repo became self-testable (mineflayer bot + scenario scripts +
world-state detectors + a council-approved baseline harness). Tracked in **EPIC #154**.

## Decision
Build a **layered, agent-driven test harness** anchored on seams the repo already owns — the
in-process Lua modules (driven via `lupa`) and the `ai_sidecar` WebSocket tap — and reconciled with the
council to attack *bug density*, not *code volume*.

- **L0 — off-sim logic regression** (CI on the Mac, byte-deterministic). Lua modules under `lupa` +
  Python sidecar pure functions, driven by a **recorded-human-lap fixture corpus** (mutated variants),
  **gated by Schema Reflection**: the `ac.*` mock is generated from a *real in-game schema dump* and any
  out-of-schema access fails the test (kills the "mock fallacy / false-green"). LuaJIT-5.1↔lupa-5.5
  parity shim (`math.atan2`); assert the harness actually calls `:update`/`tick`; clean-lap ⇒ no coaching.
- **L1 — sidecar WS-tap regression** (CI on the Mac, no game). Headless `harness_client.py` drives a
  locally-run sidecar; deterministic `coaching_response`/`improvementRanking` goldens; Ollama stubbed.
- **L1.5 — minimal in-sim sequence probe** (the council's key insertion). AC runs with built-in AI
  driving car 0; `telemetry.lua` dumps WS frames to a file; assert on **message sequences** (session →
  lap boundary → corner entry/exit → coaching fired), **not pixels**. Catches CSP frame-pacing jitter,
  nil derefs, the real `ac.getCar(0)` read path — *where the operator's pain actually drops*. Needs only
  the new `carcsw` Lua action + a manual launch, not the full daemon.
- **L2 — full autonomous in-sim loop.** In-session "harness daemon" (auto-login + unlocked Session-1 GPU
  desktop) → start AC/sidecar → drive (built-in AI for lifecycle/smoke; recorded-trace-at-read-boundary
  for logic-on-real-physics) → WS tap + shared-memory oracle + **screenshot/vision HUD oracle** →
  tolerance assertions → reset-without-renderer-drop → loop. Determinism-lock preset (fixed
  weather/solo/warm/fixed-start). Measured by **false-green rate vs human reality (<5%)**, not coverage.
- **L3 — rare human smoke**, per CSP-version bump only.

## Load-bearing reality (researched + adversarially verified, 2026-06-12)
- **Trainer is input-source-agnostic** — every read is `ac.getCar(0)`/`ac.getSim()`; lap boundary on
  `car.lapCount`. Anything that laps car 0 drives the whole pipeline with no code change.
- **The `ai_sidecar` WS is already a headless tap** (dumb broadcast hub; token-auth external bind;
  `lap_complete→coaching_response`, `corner_query→corner_advice`, `state.snapshot`). Proven by
  `tests/test_ai_sidecar_external.py`.
- **CSP "Custom AI" mmap interface** (official: `cup.acstuff.club/docs/csp/other-things/custom-ai`) lets
  an external app write `cai_car_data`/`cai_wheel_data` at 333 Hz to drive **any car incl. the player's**,
  and can teleport/restart/slow the sim. This is the in-sim driver mechanism (via a new `carcsw` Lua action).
- **REFUTED / downgraded:** AC **replay** is a 66 Hz *interpolated reconstruction*, not re-simulation →
  byte-exact assertions must stay off-sim. The 5 declared `KNOWN_TOPICS` have **no producers** yet
  (false-green trap). **Tailscale SSH server is unsupported on Windows** → the control channel must be an
  in-session daemon, not SSH (confirm on-box). `ac.overrideCarState` is render-thread only (not a driver).
  ViGEm/gamepad injection is open-loop and drifts (butterfly effect) — last resort, not canonical.

## Consequences
- ~90% of the *logic* surface becomes human-free immediately (L0/L1, no AC PC), but the **operator's pain
  only drops once L1.5 lands** — so L1.5 + Schema Reflection are pulled forward, not deferred behind L2.
- New prerequisite **control-channel** work onto host `pc` (Tailscale 100.75.251.87): an in-session
  harness daemon + auto-login/unlocked desktop + Steam-stays-logged-in (DRM). Operator-gated.
- New code grouped by files-touched into EPIC #119 Parts A–G. Secrets (PC token) via Doppler, never
  committed (see `secrets-from-doppler` invariant).

## Evidence
`.scratch/ac-selftest-grounding.md`; workflow `wf_f362091b-f9f` (12 findings + 7 adversarial verdicts);
council digest (Gemini/Kimi/Perplexity) in EPIC #154. Related issues: #116 (RL reference-lap), #115/#79
(MoTeC/CSV lap import — the recorded-lap corpus feeds L0 fixtures).
