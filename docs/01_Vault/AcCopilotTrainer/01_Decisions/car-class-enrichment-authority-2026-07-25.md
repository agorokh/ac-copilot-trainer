---
type: decision
status: active
created: 2026-07-25
updated: 2026-07-25
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/534
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-534-car-enrichment-simhub-audio-2026-07-25.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/00_System/Architecture Invariants.md
---

# Car-class enrichment authority

## Context

Assetto Corsa, the sidecar, the tablet dashboard, and SimHub expose different
per-car controls. Allowing each consumer to classify cars independently would
create conflicting taxonomies and stale profile state. AC metadata also lacks a
reliable engine-placement field, so metadata-only inference cannot distinguish
front-, mid-, and rear-engine GT cars.

## Decision

The Python sidecar is the sole car-class authority:

1. Resolve exact curated overrides before normalized `ui_car.json` metadata.
2. Publish class, car ID, provenance, registry version, and raw UI class on the
   existing replayable `session` snapshot.
3. Label unmatched, missing, or malformed metadata as a conservative `default`;
   never claim metadata provenance for a fallback.
4. Keep the registry versioned, deterministic, stdlib-only, and safe against
   car IDs escaping Assetto Corsa's `content/cars` root.

Direct clients consume the enriched `session` frame. The SimHub plugin is a
read-only adapter over that same stream: network work stays off `DataUpdate`,
trainer freshness is monotonic and fail-closed, and stale identity becomes
`unknown`. Game Point may pass the endpoint to a newly launched SimHub. An
already-running SimHub may read only non-secret bind/port settings from the
configured Game Point root; authentication tokens remain environment-only.

The repository does not install or enable the DLL, mutate SimHub profiles, or
actuate hardware. Those remain operator-owned boundaries.

## Consequences

- Tablet and SimHub consumers cannot drift into separate class taxonomies.
- Engine-layout exceptions are explicit and auditable instead of guessed.
- A disconnected trainer cannot leave a plausible stale class live in SimHub.
- Wind and pedal outputs can consume the class later, but only after their
  hardware and operator gates are separately satisfied.
- Rollback is additive: disable the SimHub DLL without changing direct sidecar
  consumers or restoring a profile.
