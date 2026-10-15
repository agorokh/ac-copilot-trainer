---
type: decision
status: active
memory_tier: canonical
created: 2026-10-14
updated: 2026-10-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/531
relates_to:
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-14-232000Z-post-merge-pr846-57e89c.md
---

# Autonomous lab: agents observe and verify their own runs

## Authority and context

On 2026-10-14 PDT the operator explicitly directed: "stop asking questions like this"
about lap completion, because the agent can observe the computer, and "If it's autonomous
lab, it should be fully autonomous." This ratifies autonomous operation of the assigned
lab exercise through the existing harness and requests a durable ADR.

The established autonomous-self-test ADR already assigns routine in-sim validation to
the agent. During #531 delivery the agent instead asked the operator to report lap
completion and used a six-minute tablet recording that expired before the session ended.
The operator subsequently reported a completed lap, but the saved AC result contained
zero timed laps and no new trainer archive existed. The missing evidence cannot be
recovered by treating the operator's reply or a successful launch as a passed test.

## Decision

1. The agent owns launch, driving for commissioned autonomous tests, observation,
   diagnosis, evidence capture, teardown, and the acceptance verdict. Use the existing
   Game Point/Content Manager and `tools.ac_harness.auto_drive` paths, machine-global
   ownership lock, authenticated control protocol, and bounded recovery budget.
2. Observe the actual PC screen and P7 pixels during a run, alongside advancing
   shared-memory packets, session identity, real WS telemetry, and finalized archives.
   Do not ask the operator whether a lap finished, whether controls moved, or whether a
   visible application state changed when those facts are accessible to the agent.
3. Start capture before launch. Keep observation active through start, timed laps,
   debrief and intentional exit. Check capture health while operating. A bounded
   watchdog may stop a failed run, but a short recorder timeout must not silently
   leave an acceptance run unobserved. Preserve the gap and repeat the automated proof.
4. Settle acceptance from the same actual session and exact timed-lap identities.
   Preserve source attribution: autonomous, human, replay, and synthetic evidence stay
   distinct. A rendered outline is not proof of the numbered/colored corner catalogue;
   an active socket is not proof of fresh telemetry; software deployment is not pixel proof.
5. Use human input only for an inaccessible physical operation, a subjective physical
   perception, an explicit purchase/authorization boundary, or a specifically retained
   human-only acceptance clause. Do not turn routine lab progress into a question loop.
   Existing ownership, security, equipment limits, and unrelated scope freezes remain.

## Consequences and verification

This records operator authority and the operating procedure; it does not claim a new
production recorder was implemented. Use the existing harness and tools now. A code
change to integrate capture must follow the normal issue/review path and memory gate.
An initial naive Tier-3 prefetch exhausted its degraded budget on a non-2xx application
response. The documented `local` mode then returned usable `ac_copilot` context for the
live electronics range investigation. No memory-gate bypass was used or authorized.

For each acceptance run retain launch and capture times, exact source/build identity,
session UUID, timed-lap validity and archive hashes, actual screen observations, failures,
and cleanup results under the existing owning issue. No additional operator lap-status
confirmation is a prerequisite for the agent to inspect that evidence.
