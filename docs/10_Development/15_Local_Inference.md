# Local coaching inference

AC Copilot keeps immediate rules, ranking and CPU attribution independent of model
narration. Game Point and `start_sidecar.bat` select the supervised Windows inference
admission service managed by workstation-ops#4004. The application does not start a
model server and does not claim that a CUDA mask on its HTTP client isolates GPUs.

The rig profile is `llama3.2:3b`, 4096 context, seed 42, temperature 0, two backend CPU
threads, at most 64 narration tokens or 20 corner tokens. Only the host service may
select Ollama or a qualified LM Studio runtime. The same model artifact and effective
profile must pass placement, latency, correctness and real game acceptance first.

| Environment | Rig default |
|---|---|
| `AC_COPILOT_INFERENCE_ENABLE` | `1`; explicit legacy `AC_COPILOT_OLLAMA_ENABLE=0` also parks narration |
| `AC_COPILOT_INFERENCE_PROVIDER` | `openai` (common chat-completions wire protocol) |
| `AC_COPILOT_INFERENCE_BASE_URL` | `http://127.0.0.1:11435/v1` |
| `AC_COPILOT_INFERENCE_MODEL` | `llama3.2:3b` |
| `AC_COPILOT_INFERENCE_HEALTH_URL` | `http://127.0.0.1:11435/health` |
| `AC_COPILOT_INFERENCE_GPU_UUID` | `GPU-1b2968de-307e-8a39-093d-24ebdc1366dc` (3050) |

The service health must attest `ready:true`, the exact model and GPU UUID, and a
finite `utc_epoch` no more than five seconds old (two seconds future skew allowed).
Missing, stale or mismatching placement means rules-only. Its fresh checks before
and after upstream generation remain authoritative. The main 3060 must never be a
fallback inference target. App `/health` exposes cached last-request readiness,
provider/model, fallback reason and queue occupancy; it performs no blocking probe.

Direct Python helpers retain native Ollama compatibility when explicitly configured
with provider `ollama` and a loopback base URL such as `http://127.0.0.1:11434`.
The generic helper makes no placement claim when no GPU attestation is configured;
the Windows production launch profile always configures it. Existing Ollama model,
endpoint and generation environment names remain compatibility aliases. Numeric
settings must be finite; timeout and output are bounded. Invalid configuration or
transport/response failures preserve deterministic advice.

All three model paths share one active blocking job and one pending latest request.
Corner queries take priority over pending lap narration. Deadlines begin at WS
receipt: two seconds for corners, eight seconds for lap narration. Superseded or
expired work never sends a late model reply. Cancellation of a socket/async waiter
does not release the blocking worker; an HTTP timeout is not proof the backend has
stopped, so the host admission service also retains exclusivity. Existing lap and
corner identities remain enforced. Corner wording is restricted to approved
state-consistent phrases; between-lap text may only restate the selected corner's
deterministic action. Cached corner text is also rejected on each Lua render update if it conflicts with
the current deterministic action; a previously valid brake hint cannot survive a
change to hold/acceleration. Primary action and colour remain rules-driven. The legacy
`debriefSource:"ollama"` Lua discriminator is retained for both providers.

## Bounded render interval acceptance

The existing authenticated harness connection can subscribe to `performance.frames`
then send `{"v":1,"type":"action","name":"capturePerformance","args":{"capture_id":"rules-1","seconds":60}}`.
Use a distinct identity for the inference run. An active capture rejects a second
start. This adds no permanent setting, output file or independent rig entrypoint.

Lua samples documented `ac.getUI().dt` once for each `ac.getSim().frame`, records
pause status, and publishes at most 128 raw intervals per chunk. It stops after
1–120 seconds or 20000 samples. Capture is off by default. Preserve every chunk
in order, including the terminal chunk; lost chunks, frame gaps, resets or invalid
intervals cannot establish a complete frame-time distribution.

Pass the snapshot payloads to
`tools.ac_harness.performance_capture.summarize_capture(chunks)` for active-frame
nearest-rank p50/p95/p99, maximum, mean and >33/50 ms counts. Paused samples remain
recorded and are explicitly excluded from active-frame percentiles. Pair the capture
with session/car/track/graphics identity, actual rendered panel screenshots and GPU
telemetry. These are **CSP UI/render frame intervals**, not OS displayed/presentation
timings or ETW metrics. Do not invert CSP's rolling FPS estimate or treat simulation
`dt` as raw render timing. The installed CSP Lua SDK documents the chosen UI delta
as unaffected by pause/replay speed and both structures as updating per graphics frame.

Neither a passing HTTP call nor these software readings establish physical PSU,
noise, RGB persistence or resolution of the previously observed NVIDIA 0x133 crash.
