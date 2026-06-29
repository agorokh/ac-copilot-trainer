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

# M-TT1 services SigV4 crack — research (2026-06-29, BLOCKED on final path/key)

`/autonomous-deliver 353` (ultracode). After M-TT0 merged (PR #359), researched M-TT1 (the
services API). The issue's stated blocker — "services sits behind Cognito Identity-Pool IAM
(SigV4); idToken → 403" — is now **substantially cracked**. NOT yet end-to-end (no services 200),
so no code shipped. Live-probed against the operator's real account.

## CRACKED ✅ — the Cognito Identity-Pool → SigV4 auth flow works
- `POST cognito-identity.us-east-1.amazonaws.com` `AWSCognitoIdentityService.GetId`
  (IdentityPoolId `us-east-1:03459aca-683c-4cc1-b2af-86b86705dd67`, Logins
  `{cognito-idp.us-east-1.amazonaws.com/us-east-1_fdm9kB5Wr: idToken}`) → **200**, IdentityId.
- `GetCredentialsForIdentity` → **200**, temp creds `{AccessKeyId, SecretKey, SessionToken, Expiration}`.
- Hand-rolled **SigV4** (stdlib hmac/hashlib; service `execute-api`, region us-east-1) is **accepted**
  by API Gateway — no signature errors. Probe: `.scratch/tt_services_probe.py` (scratch, no secrets).

## PINNED ✅ — exact services path shapes (from the Electron HTTP cache, readable)
TT is an **AWS Amplify** Next.js app (`app.tracktitan.io/_next/static/chunks/*.js`, CDN-fetchable,
not bot-blocked — only the HTML route is 429). Paths grepped from `%APPDATA%/track-titan-ghost-application/{Cache,Code Cache}`:
- `dynamic-reference-laps/sessions/{uid}/{sessionKey}/laps/{lap}`
- `dynamic-reference-laps/context/{gameId}/{trackId}/{carId}`  (e.g. `.../assettoCorsa/ks_red_bull_ring/syn_mercedes_w09`)
- `advice/sessions/{uid}/{sessionKey}/laps/{lap}/reference/{referenceId}/...`
- `data-analysis/...` (fragmented to `data-analysis/20…` = sessionKey-first; full template not in the cached chunk set)

## Auth model (observed status codes, correct paths)
- **`data-analysis` ACCEPTS SigV4/IAM** → `404 {"message":"Not Found"}` (Lambda ran; wrong path/params,
  OR session lacks computed analysis). This is the operator's PRIMARY want (per-corner diagnosis) and it
  is **auth-cracked** — only the exact path remains.
- **`dynamic-reference-laps` / `advice` / `context`** → `403 {"message":"Forbidden"}` under valid SigV4
  on the correct path → the Identity-Pool IAM role likely lacks `execute-api:Invoke` on those routes (or
  they need userPool/apiKey auth). No `da2-` AppSync apiKey literal exists in asar/cache/LocalStorage, so
  it is NOT a simple embedded key; `services.tracktitan.io/{auth,api/content}` → 404 (not the issuer).

## BLOCKED — precise remaining work (next session)
1. **Pin the exact `data-analysis` path** (unblocks the primary want via the already-working SigV4):
   capture the running renderer's network (CDP — launch the TT app with `--remote-debugging-port`, read
   `Network.requestWillBeSent` for the data-analysis GET), OR fetch the session-review page chunk (not in
   the 77 cached chunk URLs) and read the fetch template. Then brute-confirm against a session known to
   have analysis (cache lists `20260628051354/laps/5`, `20260620003604/laps/4`).
2. **Resolve ref-laps/advice 403:** try the **userPool idToken** auth mode (Amplify `defaultAuthMode`
   per-endpoint) vs IAM, or inspect the Identity-Pool role policy. The reference lap (M-TT2 input) comes
   from `dynamic-reference-laps`.
3. Then build `tt_services.py` (SigV4 signer already prototyped) + fixtures, and proceed to M-TT2
   (reference → `lap_archive` → M0 `--voice-reference`) and M-TT3.

Scratch tooling (gitignored, no secrets — values redacted on print): `.scratch/tt_services_probe.py`,
`tt_chunk_scan.py`, `tt_chunk_context.py`, `tt_auth_endpoint_probe.py`. Guardrail scope (personal
own-account use) per [[track-titan-coaching-oracle-strategy-2026-06-27]] applies.
