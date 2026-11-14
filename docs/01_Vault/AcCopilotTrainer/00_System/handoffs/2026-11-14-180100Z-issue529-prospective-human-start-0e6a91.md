---
type: handoff
status: active
created: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-094902Z-post-merge-pr992-529-g3.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Issue 529: prospective human-session prerequisite repair

The operator requests the human-attribution and Porsche/Spa reference prerequisites
be fixed and software-verified without starting driving. Historical A/F/G remain
unconfirmed. The trial remains one session and ten total laps: two warm-up, three
baseline, three locked cued and two uncued retention. No extra seed session is added.

Implementation is isolated from the active older worktrees at origin/main 86e540a.
Open-PR file coverage found no open carriers. The current generic attribution writer
must retain its restrictive-only role; operator attestation must remain explicitly
attested and scoped to this practice session, without inventing verified human-control
evidence or promoting personal bests, progression or general references.

The repair will bind driver/assistance declarations to one fresh native session,
retain a durable consumed-session fence, and preserve native/raw and restrictive
ledger authority. Reference bootstrapping must use only the two allowed warm-up
attempts and freeze before the three baseline laps. Missing eligible evidence stops
the block rather than buying more laps. Offline fixtures are software evidence only.

No AC, driving or audio playback is authorized in this repair. All human and physical
acceptance remains unverified; #529 stays open. Tier-3 used documented ac_copilot
prefetch with limited context and a stale-endpoint hint; current source, the latest
merged handoff and the operator's explicit constraints govern the implementation.
