---
type: handoff
status: active
created: 2026-10-22
updated: 2026-10-22
issue: https://github.com/agorokh/governance-hub/issues/883
relates_to:
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
---

# Central public handoff caller preparation

Reuse the existing hosted public caller's authenticated, immutable hub checkout.
All three bound SHA occurrences advance together to the central label-verification
repair. The immediately following local action remains API-only with the repo token;
the App token is confined to fetching the private hub, credentials are not persisted,
and no PR code is executed in that privileged job. The shared action alone classifies
one-note handoffs and performs their exact-head merge, label readback and review policy.

The existing unprivileged hosted build already invokes ci-vault for vault content.
Its full vault tests, tracked-file secrets and policy checks remain intact. No CI-file
edit, self-hosted registration, branch-protection change or local merger is needed.
PR899 changed ci.yml and qodo-review.yml and merged as0fdb71e at17:16:22Z.
This source branch rebased onto that result; its caller tests pass on the new base.
Product roadmap401, hardware and gameplay acceptance remain with their existing owners.

The real MCP canary completed two consecutive ordinary scheduled receipt passes,
39818404216 and39821595379, with one unchanged authenticated receipt and matching bytes.
All11 focused transport-boundary tests passed with2 declared
variant skips. The first native command stopped before tests because this repo's policy
rejects codex/; only the local branch was renamed to the allowed ci/883-public-handoff-lane.
The next run passed5191 tests but found30 missing LuaJIT module errors. Upstream Lupa's
[setup.py](https://github.com/scoder/lupa/blob/master/setup.py) deliberately excludes LuaJIT
bundles on macOS. The existing fixture now skips precisely that missing module on Darwin,
retains native Lua5.1 coverage, and keeps missing LuaJIT an error on Linux/Windows. Both
negative platform cases pass; the fixture suite passed32/30 declared skips. Required
Linux CI must still exercise LuaJIT; no production gameplay code or runtime/dependency
policy was changed. The admitted full native retry passed5193 tests with50 declared skips,
86.23% coverage, and all format/lint/secrets/policy/CSP checks. Required Linux CI must
exercise the30 LuaJIT cases skipped only on Darwin. Exact-head independent review and
full remote checks still precede merge. A real
canonical post-merge SAVE must finish after the finite author exits with matching published
bytes and authenticated scheduled receipt; later normal passes must remain idempotent.
No synthetic notes, manual merge assistance or parallel receipt implementation count.

The original AC6 result remains inconclusive. This public class is an operational row,
outside the frozen four-spoke measurement cohort. Rollback restores this caller pin/input
through the normal reviewed path, preserving the three-SHA binding and credential boundary.
