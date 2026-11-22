---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/353
---

# PR #359 — Track Titan ingest M-TT0 (vulcan retention), MERGED 2026-06-28

`/autonomous-deliver 353` (ultracode). Shipped milestone **M-TT0** of issue #353: the
`tools/tt_ingest/` package retains the operator's **own** Track Titan post-race sessions
immutably, keyed by car + track + setup — the foundation for the harness curriculum + voice
coaching. Merged as squash `bd69cab`.

## What shipped
- **`tt_auth`** — resolve the personal refresh token (`TT_REFRESH_TOKEN` env or the TT desktop
  app's Local Storage LevelDB) and mint short-lived Cognito tokens (`InitiateAuth`). Token
  discovery uses a **linear** JWE scan (suffix-after-key-marker), never a backtracking regex.
- **`tt_vulcan`** — paginate `/users/{uid}/sessions`; raw `Authorization` header (no `Bearer`).
- **`tt_export`** — **write-once** raw JSON under `journal/tt/{game}/{car}/{track}/{sk}/session.json`;
  `reindex_lake` rebuilds `index.json` + `sessions_index.json` from the **whole lake on disk**, so a
  partial export never shrinks the index and the index always matches the immutable raw files.
- **`tt_normalize`** — lossless conditions index. CLI `python -m tools.tt_ingest {auth-check, export}`.
- 97 tests, module coverage 96%.

## Live-verified (operator's real account)
`auth-check` minted via live Cognito; `export --dry-run` → **149 sessions** (matches the issue's
proven number); `export` wrote the immutable lake, re-run confirmed write-once + the index held at
"5 total in lake" after a partial re-export.

## Policy decision (important)
M-TT0 is token-authenticated cloud-API automation, which conflicted with the canonical
[[track-titan-coaching-oracle-strategy-2026-06-27]] guardrail ("never automate the cloud API with the
user's token"). The reconciliation gate caught it before merge; **operator decided (2026-06-28) to
proceed** and the guardrail was **scoped** to redistribution / automation-at-scale only — personal
own-account export is self data-portability and is permitted (tokens never logged/committed; `journal/tt`
gitignored, write-once). See the updated Guardrails in that Decision.

## Review
External bots were quota-limited (Gemini/Codex) / endorsing (Qodo), and the self-hosted reviewer daemon
is not installed for this repo — so a 5-lens **adversarial self-review workflow** (23 raw → 12 confirmed)
drove the hardening: ReDoS in token discovery, id-less lake-path collision, NaN-aborts-batch, raw
write-once vs `--overwrite`, full-lake reindex, nested-lake gitignore, `requests` runtime extra. All
secret-leakage candidates were **refuted** (no token leak).

## Next (issue #353 remains open)
- **M-TT1** — services SigV4 crack (`data-analysis`, `dynamic-reference-laps`, `advice`): idToken →
  `GetId` → `GetCredentialsForIdentity` → SigV4-sign `services.tracktitan.io`; pin the `data-analysis`
  path from the Electron Code Cache JS bundle (also check the alternate `X-Api-Key` path). Same personal-use
  guardrail scope applies. Pure SigV4 canonical-request helpers go in `tt_auth` (reuse `TTConfig`).
- **M-TT2** — reference-lap telemetry → `lap_archive` schema via `tools/ac_harness/reference_lap.build_archive_record`
  (`import_format="track_titan_reference_v1"`) → M0 `--voice-reference` (`server._wire_voice` →
  `build_observer_from_reference` needs spline/speed/px/pz/brake/throttle/steer/gear).
- **M-TT3** — per-corner analysis → harness `CornerReference` curriculum.
