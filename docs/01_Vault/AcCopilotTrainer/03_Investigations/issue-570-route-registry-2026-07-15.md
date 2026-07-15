---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-15
updated: 2026-07-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/570
relates_to:
  - AcCopilotTrainer/03_Investigations/tablet-dash-connection-hardening-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #570 — sidecar `/health` advertisement driven by the route registry

**Delivered.** PR [#585](https://github.com/agorokh/ac-copilot-trainer/pull/585) MERGED
`2026-07-15T02:33:20Z` as squash
[`2dbf7d8`](https://github.com/agorokh/ac-copilot-trainer/commit/2dbf7d8145dbbbb0accedcbe5a5b3c48de54a4b9);
issue #570 CLOSED. Follow-up from #568 (self-hosted reviewer, recurring MEDIUM).

## The real gap (worse than the issue body said)

The issue framed this as "nice-to-have — the drift guard already prevents the silent-omission
failure mode." That was **half true**. `test_served_endpoints_are_actually_routed` enforces
**advertised → routed** (a bogus advertisement 426s). Nothing enforced the **reverse**: a route
served but silently absent from `/health`, which is exactly what the #567/#568 stale-build
detection reads.

That gap was already real on main: **4 paths were routed but unadvertised** — `/healthz`,
`/voice/clips/`, `/voice/dispatches`, `/voice/echoes`. So the parallel structure had already
drifted, undetected, before anyone refactored anything.

## What shipped

`server._ROUTES` — a tuple of frozen `_Route(path, handler, prefix, token_gated, aliases)` —
drives **both** dispatch and advertisement:

- `SERVED_ENDPOINTS = tuple(route.path for route in _ROUTES)` is **derived**. **No
  `advertise=False` opt-out exists** — an opt-out is the hole the issue asked to close.
  Advertised set grew 6 → 9 (safe: no consumer does exact-set equality; all use `in`, and
  `supervisor.probe_tablet` deliberately probes reality with a real `GET /tablet/dash`).
- **Exact-match first, then prefixes** — a prefix can never shadow a more specific exact route.
  The old if-chain encoded that precedence by hand (`/voice/manifest.json` before
  `/voice/clips/`); it is now structural.
- `_index_routes` validates at import: duplicate paths/aliases, overlapping prefixes, and
  aliases on a prefix route all raise. Ambiguity is a startup error, not a route that silently
  never fires.
- Blanket `/voice/*` + `/dash/*` token gate → per-route `token_gated=True`.
- **Aliases** (`/healthz`) route to an advertised route's handler and are not advertised.

## The recursive bug the reviewer caught

The self-hosted reviewer (`ws-ops-cursor-reviewer`, Gemini 3.1 Pro) flagged a **MEDIUM** on
`50eb378`: prefix handlers hardcoded their own route string (`path[len("/dash/fonts/"):]`) to
slice the suffix — **duplicating registry state**. That is *the same parallel-structure drift
#570 exists to remove*, reintroduced one layer down. Fixed in `12f730b`: the router pre-strips
the matched route's path and passes `tail`; handlers never restate their path (`tail` is `""`
for exact routes). Also per that review, pure registry unit tests moved to
`tests/test_ai_sidecar_routes.py`; `/health` payload assertions stayed in the observability suite.

**Lesson:** collapsing a parallel structure at one level can silently recreate it at the next.
When a registry owns a string, nothing downstream may restate that string.

## Verification (observed, on the MERGED artifact)

Sidecar booted from `origin/main` via its own entrypoint (`python -m tools.ai_sidecar`), which
self-reported `build_commit: 2dbf7d8` — the merge commit itself:

- `/health` advertises all **9** registry routes; the live set **reconciles against the
  `_ROUTES` declarations in `origin/main` source** (`match: True`).
- Every advertised route serves (no 426). `/healthz` → 200 yet absent from `endpoints`.
- Real vendored font `/dash/fonts/Saira-Bold.ttf` → **200, 82956 bytes** (proves the
  tail-stripping fix against reality). `nope.ttf` → 404 (handler-owned, not fall-through).
- `/voice/typo`, `/unrouted` → **426** (correct WS fall-through).

**Non-vacuous guard:** `test_health_advertises_every_registered_route` was mutation-checked —
dropping one route from the derived tuple reds it (`Right contains one more item:
'/voice/echoes'`), so it genuinely catches #570's failure mode.

**Differential proof of the token-gate delta:** the one behavior change claimed "equivalent"
(unregistered paths under `/voice/`, `/dash/` now fall straight to the WS `token_check`) was
proven, not argued: `test_unregistered_path_under_gated_prefix_still_refused` passes against
**both** this branch's registry **and** `origin/main`'s pre-refactor inline chain.

`make ci-fast` OK (2912 passed, 77 skipped). Required checks green on head `12f730b`;
0 unresolved review threads; merged after a full 10-min cooldown.

## Follow-up

None filed. The reviewer's findings were fixed under the parent PR rather than deferred — they
bore on this outcome. No separable scope surfaced.
