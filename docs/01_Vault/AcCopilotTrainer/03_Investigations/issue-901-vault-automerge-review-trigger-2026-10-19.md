---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-19
updated: 2026-10-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/901
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/02_Investigations/2026-09-07-repin-vault-automerge-78a47069.md
---

# Vault auto-merge re-runs when the reviewer round settles (#901, 2026-10-19)

## Symptom

A `vault-only` PR sat open with a red `guard-and-automerge` check after a clean
self-hosted review (#886). Each push fired `.github/workflows/vault-automerge.yml` within
seconds, while `ws-ops-cursor-reviewer[bot]` held that head's review lease, and the hub
action refused `REFUSE: lease_in_flight` (gov-hub#464, correct behaviour). The caller
listened only to `pull_request` events, so nothing re-ran it once the review landed. The
hub `vault-pr-sweep` (15-min cron, 25–40 min end to end under runner queueing) or a
manual `gh run rerun --failed` was the only way out.

## Measured timing

The daemon keeps one sticky lease comment per PR (`<!-- ws-ops-reviewer-lease:v1 … -->`)
and edits it to `reviewed` 1–3 s after posting each review. Examples: #886 rounds 1/2/4/5,
20:41:45→47, 22:08:12→14, 01:32:44→47 and 03:10:02→04 UTC. A caller run reaches the
review-round snapshot about 9–10 s after its event.

## Fix

The caller also runs on `pull_request_review: types: [submitted]`. That payload carries
`pull_request`, so the job gate, concurrency group and `pr-number` are unchanged.
Canonical change: agorokh/template-repo#593 (`8c14812`; issue template-repo#592, which also
moved the template's public variant to the sweep-bound checkout shape from #889). Adopted
here in #902 (`01a5a98`). The trigger fired as designed on both PRs' own reviews (skipped,
not vault-only): template-repo run 39197376976, 3 s after the review; spoke run 39198185131.

Rejected: `issue_comment: edited` on the lease comment (no head repo in the payload for the
same-repo gate; breaks the template's single-`uses:` thin-caller contract) and a bounded
lease wait in the hub action (holds a runner up to ~14 min per push, against
`release-when-pending`).

## Residual

If the daemon ever releases its lease more than ~7 s after its review, the review-triggered
run refuses again and the hub sweep is still the backstop. Other spokes adopt the trigger via
`template-sync` once a template tag carries `8c14812`.
