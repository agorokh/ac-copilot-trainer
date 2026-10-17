# Local coaching inference

AC Copilot keeps immediate rules, ranking and CPU attribution independent of model
narration. The application does not start a model server and does not claim that a
CUDA mask on its HTTP client isolates GPUs.

**Default is model-disabled (rules-only).** The RTX3050 inference rig was removed on
2026-10-16 (issue #854). Source defaults name no backend, so Game Point and
`start_sidecar.bat` default `AC_COPILOT_INFERENCE_ENABLE=0`: coaching runs on the
deterministic CPU brain and makes no model HTTP call. The launcher no longer seeds the
retired `localhost:11435`/3050 endpoint, so default-off performs no localhost retry and
inference can never silently fall back onto the main RTX3060.

Re-enabling model coaching is an explicit operator decision (`AC_COPILOT_INFERENCE_ENABLE=1`
or the legacy `AC_COPILOT_OLLAMA_ENABLE=1` alias) that must also supply a separately
approved backend contract — provider, loopback base/health URL, model identity, and GPU
attestation. The supervised Windows admission service (workstation-ops#4004) that owned
CUDA placement is retired with the card; the operator-approved replacement is the remote
backend described below, enabled through operator configuration.
The reference rig profile is `llama3.2:3b`, 4096 context, seed 42, temperature 0, two
backend CPU threads, at most 64 narration tokens or 20 corner tokens. Only a host
service may select Ollama or a qualified LM Studio runtime, and the same model artifact
and effective profile must pass placement, latency, correctness and real game acceptance
first.

| Environment | Default | On operator re-enable |
|---|---|---|
| `AC_COPILOT_INFERENCE_ENABLE` | `0` (rules-only); legacy `AC_COPILOT_OLLAMA_ENABLE` alias honoured | set `1` to opt in |
| `AC_COPILOT_INFERENCE_PROVIDER` | unset → generic helper default (`ollama`) | `openai` for the common chat-completions wire protocol |
| `AC_COPILOT_INFERENCE_BASE_URL` | unset (retired `11435` endpoint no longer seeded) | operator-supplied loopback URL of an approved backend |
| `AC_COPILOT_INFERENCE_MODEL` | unset → generic `llama3.2` fallback | approved model identity, e.g. `llama3.2:3b` |
| `AC_COPILOT_INFERENCE_HEALTH_URL` | unset | operator-supplied loopback health endpoint |
| `AC_COPILOT_INFERENCE_GPU_UUID` | unset (no GPU placement claim) | the approved backend GPU's UUID (loopback services only) |
| `AC_COPILOT_INFERENCE_REMOTE_ORIGINS` | unset (loopback only) | exact approved HTTPS origin(s), e.g. `https://<host>:<port>` |
| `AC_COPILOT_INFERENCE_REASONING_EFFORT` | unset | `none` for a thinking model (OpenAI protocol `reasoning_effort`) |
| `AC_COPILOT_INFERENCE_API_KEY` | unset | optional bearer token, sent only to an approved URL |

## Approved remote backend (#854)

The client accepts a non-loopback service only when its base URL is HTTPS, carries
no credentials, query or fragment, and its exact origin (scheme, host, port) is listed
in `AC_COPILOT_INFERENCE_REMOTE_ORIGINS`. Anything else is rejected before any network
I/O. Remote services make no GPU placement claim; do not set the GPU UUID for them.
Hosts come from operator configuration, never from source.

On the OpenAI protocol the served `model` must equal the configured model id, or the
reply is discarded as `model_mismatch`. A thinking model that spends its whole token cap
on reasoning returns empty content, which is rejected as `invalid_response`; set
`AC_COPILOT_INFERENCE_REASONING_EFFORT=none` to switch reasoning off. A reply cut by
the token cap is trimmed back to its last complete sentence (decimals do not end one).
Deadlines, the single active generation, deterministic acceptance of corner and
between-lap text, and rules fallback are unchanged. App `/health` reports
`inference.remote`.

The operator-approved backend (2026-10-17) is the fleet LM Studio on the canonical Mac
Studio, reached over its existing Tailscale HTTPS face, serving `qwen/qwen3.5-4b`. That
model is shared with the Home Assistant voice plane. Measured from the rig with the AC
prompts and `reasoning_effort=none`: 30/30 corner replies correct and inside the
approved phrase set at 0.29–1.25 s, lap narration 1.30–1.43 s. Without the reasoning
switch every reply was empty. Concrete host values and acceptance evidence live in the
vault node `03_Investigations/issue-854-remote-inference-2026-10-17.md`.

When the operator configures a GPU UUID, the service health must attest `ready:true`, the exact model and GPU UUID, and a
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

**The model is for post-lap narration and between-lap focus (#854).** In-race corner hints
come from the trainer's rules engine; model corner hints are opt-in with
`AC_COPILOT_INFERENCE_CORNER_HINTS=1` (and still require the feature enabled). An agent-observed
rig drive showed why: an accepted model hint can only restate the command the rules engine
already chose for the speed delta (82 of 84 were "ACCELERATE, BUILD SPEED"), 41% of calls missed
the 2 s deadline under live load, and the corner stream starved narration (1 of 3 laps). When
off, a `corner_query` gets no reply and never touches the generation queue.

The model paths share one active blocking job and one pending latest request, ordered
narration (3) > between-lap focus (2) > opt-in corner hint (1): a pending higher priority
survives a lower submit, and between-lap focus falls back to its deterministic phrase at once.
Model narration must be grounded in its own facts: a diagnosis term (e.g. understeer,
oversteer, traction, setup, tyres), a positional claim ("the first three corners"), corner or
number that the facts do not contain rejects it (`fallback_reason` `ungrounded:…`) and the rules
debrief stays; numbers may be rounded. Narration is HUD-sized (at most two short sentences);
a reply cut by the token cap without one complete sentence is dropped (`truncated`). The
immediate lap `coaching_response` carries no placeholder hint: a non-empty `hints` list replaces
the trainer's own rules-engine lines, so the old "Sidecar v1: ack lap N" stub was what drivers saw
after each lap. Deadlines begin at WS
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

Between-lap `corner_advice` uses `slot:"between_lap"`; it never enters the immediate
corner command cache. Its `adviceSource:"model"` is set only for text accepted against
the selected deterministic command. Lua merges that focus with CPU brain hints,
keeps the completed-lap identity, and expires it after twelve seconds. Only focus
text still in applied coaching state appears in the existing `coaching.snapshot`
as `post_lap_focus` (`source`, `text`, `corner`, `lap`, `focus_id`, `remaining_ms`) with
`completed_lap`. This is the observation point for live panel acceptance. The P7
COACH fallback renders that exact text until expiry; repeating a snapshot cannot
renew the same focus. An existing full `session.review` retains screen authority.

Coach v2's speed-minimum regions do not establish turn names. Named voice/cue and
between-lap advice share a geometry binding to the authenticated active Lua corner
catalogue, using MAP's existing combo/range validation. A measured window must
overlap exactly one canonical region containing its apex; split/multiple measured
regions sharing one turn and merged regions stay unnamed. Eligible regions are
filtered before focus selection, preserving the internal diagnostic ledger and
allowing another uniquely mapped focus to win. Binding changes discard in-flight
post-lap output. Public voice health reports `coach_corner_identity` readiness,
reason and counts without personal geometry/targets. Same-combo files or matching
corner counts alone do not qualify ordinal labels.

The restored102183ms Magione trace has five dynamic regions, whereas Lua's active
reference has nine canonical turns. This difference is material: only the first
two regions uniquely map; later merged regions cannot emit named coaching. The
previous T5 screenshot proved text transport, not correct physical-turn semantics.

This path needs an existing reference with usable corners and Coach v2 enabled.
Game Point's normal `reference_archive` setting passes `AC_COPILOT_REFERENCE_ARCHIVE`
to the sidecar and selects Coach v2 unless explicitly parked with
`AC_COPILOT_COACH_V2=0`. The sidecar still qualifies the archive before activation.
An alien line also selects v2. Empty voice bank and TTS off support silent observation.
Legacy-unmanaged references remain `legacy_unknown`, never certified human laps.
For autonomous acceptance, disable archives with the existing authenticated
`config.set` for `lapArchiveEnabled:false`, then assert `config.get` returns a
`config.value` with boolean `false` **each new game before the first lap**. Preserve
and compare the personal journal and combo snapshot; do not rely on persistence
across game restarts or allow quota rotation to touch personal history.

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

New captures additionally record `os.preciseClock()` intervals between callbacks
for consecutive unique render-frame IDs. The installed SDK describes this as
high-precision seconds since script start; it does not specify OS wall-versus-CPU
clock implementation. UI delta stays a separate diagnostic; its apparent ceiling
must not hide longer callback gaps. These script-clock callback intervals include
scheduling/update gaps and are not OS displayed/presentation timings.
Producer capture elapsed time and client acknowledgement/arrival time are separate
observations; network/relay delay is not silently attributed to GPU rendering.
Older captures retain UI-only provenance and cannot prove script-clock callback tails.

Neither a passing HTTP call nor these software readings establish physical PSU,
noise, RGB persistence or resolution of the previously observed NVIDIA 0x133 crash.
