---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-29
updated: 2026-06-29
relates_to:
  - AcCopilotTrainer/03_Investigations/pr-359-tt-ingest-mtt0-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/353
---

# M-TT1 services crack — RESOLVED (2026-06-29): accessToken, not SigV4

`/autonomous-deliver 353` (ultracode). M-TT1 shipped in **PR #370**. The earlier
SigV4 / Identity-Pool hypothesis (this node's prior revision) was **WRONG** and is
corrected here. Cracked + verified live via CDP capture of the running TT renderer.

## CORRECTED auth model (verified live, from our own mint path)
- services `/api/v2/*`, `/dynamic-reference-laps/*`, `/advice/*` authenticate with the
  **raw Cognito ACCESS token** in `Authorization` (NO `Bearer`) — the SAME token vulcan
  uses (`tt_auth.mint_tokens` already returns it). **No SigV4 / Identity-Pool flow needed.**
- Proof: `services last-session [accessToken] → 200`, `[idToken] → 403`; vulcan
  `[accessToken] → 200`. uid `ed469389…` from the minted token matches the captured request.
- Why the prior 403s: the research probed **old cached paths** (`data-analysis/{uid}%23{sk}`)
  with the **idToken**. The live API is RESTful `/api/v2/…` and takes the access token.
- The Cognito Identity-Pool `GetCredentialsForIdentity` calls the app also makes are for
  analytics (Pinpoint), NOT these data routes.

## Method (reusable)
Relaunch `TrackTitanDesktopApplication.exe --remote-debugging-port=9222`; attach CDP
(`websockets`), `Network.enable`, drive the renderer (`Page.navigate` to /dashboard →
click "Get Insights"), capture `Network.requestWillBeSent` + `getResponseBody`. 68+ real
bodies captured to gitignored `.scratch/tt_capture/`. Scratch tooling: `.scratch/tt_cdp_*`,
`tt_crack.py`, `tt_verify.py` (no secrets; redacted prints).

## Live paths (envelope = `{success,status,data,message}`; dynamic-reference-laps is BARE)
- `GET /api/v2/users/{uid}/sessions?page&hideLimited&limit`
- `GET /api/v2/sessions/{uid}/last-session`  → session + referenceLap + **telemetry trace**
- `GET /api/v2/sessions/{uid}/{sk}/laps/{lap}/reference`  (dynamicComparisonLap)
- `GET /dynamic-reference-laps/sessions/{uid}/{sk}/laps/{lap}?segmentCount=N`
- `GET /api/v2/sessions/{uid}/{sk}/reference/{refUid}/{refSk}/laps/{refLap}`
- `GET /advice/sessions/{uid}/{sk}/laps/{lap}/reference/{refUid}/{refSk}/laps/theoreticalBestRef/segments/{n}`
- `GET /api/v2/users/{uid}/analysis/progress/?gameId&trackId&carId`

Two references, kept distinct: **dynamic_reference** (community/other driver, e.g. "Dennis
Bosman") vs **advice_reference** (operator's own `theoreticalBestRef`).

## M-TT2 input (telemetry trace, PINNED)
`last-session.data.telemetry.telemetry.{user,reference}` = ~265-pt lists. Point keys:
`dist`(spline 0-1), `distM`, `Kmh`(speed), `brak`, `throt`, `steer`, `ovSteer`, `unSteer`,
`gear`, `lTime`(ms), `useGrip`, `X`,`Y`(track pos). Maps to `lap_archive` TRACE_FIELDS in
`tools/ac_harness/reference_lap.py` (spline=dist, speed=Kmh, brake=brak, throttle=throt, …).

## Shipped (PR #370)
`tools/tt_ingest/tt_services.py` (client: builders+parsers pure, network no-cover) +
`coaching` CLI (retains per-lap raw evidence `last_session_lap{N}.json` + `coaching_lap{N}.json`
to the write-once lake, reindexed) + sanitized fixtures + tests. Live E2E verified
(per-corner diagnoses, e.g. Magione Porsche 911 GT3 R: c3 "You messed up your exit").

## NEXT: M-TT2 (reference telemetry → lap_archive → M0 --reference-archive), M-TT3 (per-corner → harness).
