---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-16
updated: 2026-06-16
relates_to:
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/csp-car-wheels-0-indexed-2026-06-15.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/190
---

# CSP Custom AI mmap interface — the `carcsw` driver foundation (EPIC #154 Part E)

The actuation keystone for the autonomous self-test: an external app writes shared memory to drive
any car (incl. the player's) at 333 Hz, and can teleport / restart / slow the sim. Source: official
CSP doc `cup.acstuff.club/docs/csp/other-things/custom-ai` (fetched 2026-06-16). Pairs with the
[autonomous-self-test-harness](../01_Decisions/autonomous-self-test-harness.md) decision.

> **Confidence caveat:** mmap NAMES, field NAMES, activation, signaling, and rates below are
> high-confidence (verbatim from the doc). The **byte offsets** were machine-extracted and MUST be
> re-verified against the CSP source / a live dump before trusting them in `carcsw` — mirror the
> #175 oracle's approach (a live `__main__` probe that dumps + reconciles).

## Memory-mapped files (`<N>` = car index, e.g. 0 for player)

- **WRITE (drive the car):** `AcTools.CSP.NewBehaviour.CustomAI.CarControls<N>.v0` — `cai_car_controls`.
- **READ (car state out):** `AcTools.CSP.NewBehaviour.CustomAI.Car<N>.v0` — `cai_car_data`.
- **READ (other cars, 60 Hz):** `AcTools.CSP.NewBehaviour.CustomAI.CarPublic<N>.v0`.
- **SIM control:** `AcTools.CSP.NewBehaviour.CustomAI.SimState.v0` — `pause`, `restart_session`,
  `disable_collisions`, `extra_sleep_ms` (slow the sim).
- **Debug lines:** `AcTools.CSP.NewBehaviour.CustomAI.DebugLines.v0`.

## `cai_car_controls` — what `carcsw` writes (offsets unverified)

`gas`@0, `brake`@4, `clutch`@8, `steer`@12 (−1..1), `handbrake`@16 (floats); `gear_up`@20 /
`gear_dn`@21 + many bool toggles (drs/kers/abs/tc/...); `teleport_to`@40 (byte: 1=pits, 2=custom),
`teleport_pos`@44 (float3), `teleport_dir`@56 (float3), `autoshift_active`@68. So a basic driver
needs only gas/brake/steer/handbrake + gear up/dn + teleport.

## Signaling / activation

- **Signal control:** the external app CREATES the `CarControls<N>` mmap; CSP responds by creating
  the matching `Car<N>` mmap — that confirms the car is hijacked. (So `carcsw` creates+writes the
  control mmap and waits for the data mmap to appear.)
- **Enable (operator-gated config):** `extension/config/new_behaviour.ini` → `[CUSTOM_AI] ENABLED=1`;
  and the track's `surfaces.ini` needs extended physics + `[_EXTRA_PERMISSIONS]
  ALLOW_CUSTOM_AI_MANIPULATION=1`. These are one-time config the operator applies.
- **Rate:** 333 Hz (controls in + car data out); public-car data 60 Hz.

## `carcsw` module design (next build, #190)

Mirror `tools/ac_harness/shared_memory.py` (#175 reader): pure `struct` pack/unpack (CI-testable any
OS) + a Windows `CreateFileMappingW`/`OpenFileMappingW` writer (NOT `mmap(-1, tagname=)` — must
create the named section; declare ctypes argtypes to avoid the 64-bit pointer overflow #175 hit) +
a live `__main__` probe (create CarControls, write a gentle gas/steer, confirm `Car<N>` appears,
read it back, dump offsets to VERIFY the layout above). Off-sim unit tests assert pack round-trips;
**in-sim driving is gated** (needs AC + the operator's config + extended-physics track) — draft until
observed moving car 0. The L1.5 sequence probe (#191) + `diag_wheels.py` then verify the driven lap
end-to-end with no human in the loop — the EPIC #154 throughline.
