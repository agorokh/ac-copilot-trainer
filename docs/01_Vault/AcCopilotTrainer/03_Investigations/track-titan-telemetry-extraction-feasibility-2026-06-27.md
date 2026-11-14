---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-27
updated: 2026-06-27
relates_to:
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/pr-207-motec-reference-import.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Track Titan — local data & extraction feasibility (2026-06-27)

Forensic study of **Track Titan (TT)** installed on the rig (`AG_PC`), to assess using its coaching
as an external angle for our coach + autonomous harness. Full report: `.scratch/tt-research-report.md`;
raw evidence: `.scratch/tt-forensics.md`.

## What TT is, on disk
- Electron app `track-titan-ghost-application` (v `2.1.37`, auto-updates). Capture SDK at
  `%APPDATA%\tracktitansdk\MOZA\` with native bindings (iRacing `IrSdkNodeBindings`, `nodeeasyipc`).
- **Reads the SAME AC `acpmf_physics/graphics/static` shared memory we read**, and for AC **uploads the
  native `.acreplay`** (it grabbed our Stanley 911@Magione lap from `OneDrive\Documents\Assetto Corsa\replay\temp`).
- Stores locally: plaintext Cognito JWTs (`config.json`/`cognito.json` — **security note, do not copy**),
  config, `setupsStore.json`, UI/analytics leveldb (LocalStorage + IndexedDB), logs. **No local persisted
  coaching artifact** — analysis is cloud-only.

## How analysis works
Local capture → **AWS** (Kinesis "Bifrost" stream + SNS lap topic + S3 + Cognito) → results via
`services.tracktitan.io/api/v1/...` (`/users/{id}/sessions`, `/setups?ghost-download=true`) → hosted
overlay + web app. **No public API, no export, no downloadable ghost telemetry** (web-confirmed;
only GDPR data-portability or browser automation). ToS: no anti-RE clause, but broad reuse-rights over
uploads + setup-redistribution ban; UK law.

## Key finding
For AC, **TT adds no new raw signal** — same shared memory + the `.acreplay` we own. Its only moat is
pro **ghost reference laps** + an **AI interpretation layer** (per-corner time-loss, pedal-vs-pro, tips).
So the value is *external opinion + pro lines*, not data we lack.

## Extraction surfaces (ranked)
1. **Screen-capture/OCR of the overlay** — most ToS-neutral + update-robust; we have GDI capture tooling.
2. **`ws://localhost:9121`** — TT's `LocalWebSocketServer` (plain `ws`, `/overlay`, `sec-websocket-protocol`).
   Highest payoff *if* it carries pro-ghost trace + corner delta as JSON; needs a handshake spike; fragile across updates.
3. **Ghost-line acquisition** (the line, not the file) → feeds the #207 faster-than-PB importer.
- **Avoid:** replaying the user's plaintext Cognito token against TT's cloud (most ToS/CFAA-exposed).

## ws:9121 tap — SPIKE CONFIRMED (2026-06-27, read-only)
A read-only consumer tap is **viable and validated** end-to-end (tool: `.scratch/tt_ws_tap.ps1`, native
PowerShell `ClientWebSocket`, no deps):
- Connect `ws://localhost:9121/` with header `Origin: http://localhost` → handshake **opens** (no subprotocol/auth).
- Register by sending `{"type":"overlay-initialisation"}` → server sets `isOverlay=true` (server source:
  `sendMessagesToOverlay` only fans out to `clients` where `n.isOverlay`). A purely passive connect gets nothing.
- Feed is **MessagePack** (binary; string keys readable → needs a msgpack decoder, not `JSON.parse`).
- Message types observed (idle replays last session): `overlay-cognito-keys` (**auth — MUST redact/skip**),
  `overlay-initial-data` (`gameId`, `trackId.id`, `carId.id`, `sessionKey`, `userId`, `ghostVersion`),
  `overlay-start-lap` (`fuel`, `tyreCompound`, `tyreTempP`, `airTemp`, `roadTemp`). During a live lap the
  server pushes `overlay-data {payload:{data}}` (the telemetry/coaching feed) — capture requires AC running.
- **Security caveat:** on register, the server pushes the user's Cognito keys (`overlay-cognito-keys`);
  the tap redacts them and never persists tokens.
## ws:9121 LIVE CAPTURE — fully autonomous, end-to-end (2026-06-27)
Ran the complete hands-off loop on `AG_PC`: applied Custom-AI permission to the track `surfaces.ini`
(`[_EXTRA_PERMISSIONS] ALLOW_CUSTOM_AI_MANIPULATION=1`; CSP `new_behaviour.ini [CUSTOM_AI] ENABLED=1`
already set), launched AC via `Content Manager.exe "acmanager://race/config"` (the shell is **non-elevated**
here, so no elevation-mismatch), drove car 0 via the carcsw `CustomAIController` + `LapDriver` (Monza /
Porsche Cayman GT4), while the read-only tap logged ws:9121. **Track Titan auto-recorded the session and
rendered its overlay** (live pedal/delta widgets visible on screen — screen-capturable).

**Captured 11,091 frames.** Across the whole live session the ws carried **only 4 message types**:
- `overlay-data` (per-frame live telemetry): `gameId, dist, brak, gear, Kmh, lTime, prevLapTime, steer,
  throt, X, Y, lapNumber, isInPit` (MessagePack).
- `overlay-start-lap` (`fuel, tyreCompound, tyreTemp, airTemp, roadTemp`), `overlay-initial-data`
  (`userId, sessionKey, trackId.id, carId.id, ghostVersion`), `overlay-session-start`.

**DECISIVE FINDING: no reference / delta / coaching / pro-ghost-trace message ever appeared on ws:9121**
(the only "ghost" token is the `ghostVersion` field). The on-screen overlay stayed in "REFERENCE WILL
APPEAR — drive a valid lap." So **TT's coaching/analysis is NOT delivered over the local ws** — the ws is
a live-telemetry transport feeding the cloud-rendered overlay; the reference/per-corner analysis is computed
cloud-side and composited in the hosted overlay page. **The ws tap therefore yields no new signal for AC**
(we already read the same shared memory). **To extract TT's actual coaching, screen-capture/OCR of the
overlay (or the cloud API) is required** — confirming the §"Extraction surfaces" ranking (screen-capture is
the robust path for the *coaching*; ws is telemetry-only).

**Caveat (honest):** the autonomous lane-keeper ran wide at Monza's chicanes (no *valid* lap completed), so
we cannot 100% exclude that TT begins pushing a reference trace over ws once it has a valid lap to compare
against. Confidence it never rides the ws is ~85-90% (schema has no reference fields; architecture is
cloud-analysis; overlay fetches the reference itself). A verified valid lap (magione + `RacingDriver.from_human_profile`)
would settle it. Tools: `.scratch/tt_ws_tap.ps1`, `.scratch/ac_drive.py`, `.scratch/ac_drive2.py`. Rig
restored to stock (both `surfaces.ini`); AC + tap stopped.

## Valid-lap follow-up — coaching is OVERLAY-side, confirmed (2026-06-27)
Closed the residual: drove a **valid** lap (magione, slow robust lane-keeper, Cayman GT4; CM track switched
via Win32-coordinate GUI clicks since CM controls aren't in the UI tree). On the official S/F crossing
(`Last: 3:08.354`), **Track Titan generated an AI post-lap debrief and rendered it in the overlay**:
> "Post-lap debrief (lap 1, 188.354 s). Focus areas from on-track coaching: **Full throttle only 0% of lap —
> focus on earlier power application**…"
**That debrief did NOT cross ws:9121** — grep of all captured frames finds no debrief text and no
`app-*`/`notification`/`overlay-debrief`/`overlay-coaching`/`overlay-reference` type; the server's reconnect
state-sync (`overlay-initial-data` + `overlay-start-lap`) does not include it. **Second finding:** with the
*real* TT overlay active, the ws tap got **zero** `overlay-data` during this session (reconnect storm) — i.e.
the ws tap is also an **unreliable second consumer** (the server effectively streams to the live overlay).
**Conclusion (high confidence): TT's coaching is computed cloud-side and rendered only in the overlay →
SCREEN-CAPTURE/OCR is the extraction path; the ws tap is telemetry-only AND not robust alongside the real
overlay.** This is the empirical basis for the screen-capture extractor (next).

Strategy + roadmap: [[track-titan-coaching-oracle-strategy-2026-06-27]].
