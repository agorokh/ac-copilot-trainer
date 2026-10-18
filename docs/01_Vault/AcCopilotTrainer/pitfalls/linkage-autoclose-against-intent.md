---
type: pitfall
status: active
created: 2026-10-18
updated: 2026-10-18
memory_tier: canonical
severity: maintainability
relates_to:
  - AcCopilotTrainer/pitfalls/_index.md
  - AcCopilotTrainer/pitfalls/cross-issue-pointer-rot.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/pitfalls/state-consistency.md
  - AcCopilotTrainer/03_Investigations/2026-10-18-175107Z-backlog-steward-ledger-snapshot-bdd6d5.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-18-201940Z-resolve-pr878-8e0ce8.md
---

# Linkage auto-close against stated intent

**Project-curated** (observed in the `/backlog-steward` sweep of 2026-10-18; canonical case #813).
Process pitfall — no `scope_paths`, so the issue-writer does not inject it.

## What happened

PR #848 ("fix(tablet): use exposed setup ranges for live electronics (#531)") carried
`closingIssuesReferences = [813]`. Its body said, in words, *"this does not close #813 or change
MAP geometry/corner numbering"*. GitHub closed #813 at `2026-10-15T01:43:36Z`, two seconds after
the merge at `01:43:34Z`. No closing comment exists on #813; its last comments (2026-10-13) are
the ESP32-only waiver and a "P7 disconnected" check. Two hours later the post-merge handoff
wrote "#813 remains a separate owner" and PR #849 wrote "#813 retains its separate scope" — the
owner believed the issue was still open. Its retained P7 acceptance (operator-driven valid lap,
moving numbered MAP, intentional-exit stale transition) was never dispositioned.

## Why it bites

- The tracker now says Done for work the owner explicitly kept open: a **Done ghost**. The next
  session either re-derives the gap from scratch or trusts the closed state and loses it.
- Prose disclaimers do not override closing keywords. `Closes/Fixes/Resolves #N` anywhere GitHub
  reads them (PR body, earlier body revision, commit message) wins at merge time.
- Backlog reconciliation that keys on *open* issues never sees it unless it also diffs the
  previous ledger's open set against current state.

## How to avoid

1. In PR bodies and commit messages, reference a parent you do not intend to close with
   `Refs #N`, never `Closes #N`. Check `gh pr view <P> --json closingIssuesReferences` before
   merge; the list must equal the set you mean to close.
2. After every merge, `gh issue view <N> --json state,closedAt` for every issue the PR
   references. A close within seconds of `mergedAt` with no closing comment is this pitfall.
3. When it has happened: record an explicit closing-disposition comment (accepting other
   evidence, or waiving the remainder) or reopen. Never leave an auto-closed issue with
   undispositioned acceptance.
4. Never *quote* a closing phrase either — "does not close #N", "will not fix #N" — in a PR body
   or commit message. GitHub's parser has no negation; the quotation re-links #N. Describe the
   intent instead ("disclaims #N as a closing target", "#N stays open").

## Steward detection rule

Phase 0 ledger diff: for each issue the previous ledger carried as open that is now closed,
require a closing comment or a merged PR whose body claims closure. Absent both, verdict
`partially-delivered` (CLOSED) and escalate — the merge is a hypothesis; the verdict owns the state.

## Seen again (2026-10-18, PR #878)

The steward SAVE that recorded this pitfall quoted #848's disclaimer verbatim and so carried
`closingIssuesReferences = [813]` itself. The hub `vault-automerge` close-intent snapshot
(gov-hub#621, pin `5e00dad1`) refused the merge on the exact head; rewording the body emptied the
list without moving the head, and the PR merged as `8dc8478`. Rule 4 above is that lesson.
Handoff: `00_System/handoffs/2026-10-18-201940Z-resolve-pr878-8e0ce8.md`.
