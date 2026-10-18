---
type: investigation
status: active
created: 2026-10-18
updated: 2026-10-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/889
relates_to:
  - AcCopilotTrainer/02_Investigations/_index.md
  - AcCopilotTrainer/02_Investigations/2026-10-05-repin-vault-automerge-db8b63c6.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-18-213700Z-post-merge-pr890-6f1a8c.md
---

# Vault-only PRs stalled on a manual label toggle: sweep-unreadable caller (#889, PR #890)

## Symptom

Every vault-only handoff PR here merged only after someone toggled the `vault-only` label off
and on (#880 at 20:36Z, #883 at 20:44Z, 2026-10-18). The spoke guard's first run refuses
`lease_in_flight` while the self-hosted reviewer daemon still holds the head. The hub
`vault-pr-sweep` (governance-hub, cron :09/:24/:39/:54) is the retry, and its discover step
skipped this repo every cycle:

```
skip     agorokh/ac-copilot-trainer#880: caller-unreadable (vault-automerge.yml: local hub action lacks a bound canonical checkout)
```

## Mechanism

`vault_sweep_discover.py::_bound_local_action` (hub) admits a LOCAL hub action only when the
immediately preceding `actions/checkout` pins `agorokh/governance-hub` at `ref: <sha>` into
`path: .scratch/governance-hub-<sha>`, with `persist-credentials: false`, a `token:` or
`ssh-key:`, the same `if:`, and the action step `uses:` that same `.scratch/governance-hub-<sha>`
path. Our caller (pin `5e00dad1`) checked out into `.governance-hub` without
`persist-credentials`, so the sweep failed closed. This repo is public, so the direct
private-action `uses:` shape (#329) is not available; the bound local checkout is the only shape
both GitHub and the sweep accept (`workstation-ops` already uses it).

## Fix (PR #890, squash-merged as `6f1a8c1` at 21:32Z)

- `.github/workflows/vault-automerge.yml`: checkout `path: .scratch/governance-hub-a8f5877…`,
  `persist-credentials: false`, `uses: ./.scratch/governance-hub-a8f5877…/.github/actions/vault-automerge`.
  Pin rolled `5e00dad1` -> `a8f5877` (hub `main`, 2026-10-18). The action directory and its
  runtime script closure (`vault_automerge_*.py`, `vault_sweep_stalled.py`, `ci_resolve_gate`,
  `reviewer_lens_state`, `patch_id_equivalent_heads`) are byte-identical between the two, so
  the roll is drop-in. `release-when-pending: "true"` kept; still no `require-check`.
- `tests/test_vault_automerge_workflow.py`: `HUB_ACTION_REF` rolled, and the public-variant test
  now asserts the bound shape (mirrors the hub parser), so the next drift is caught by
  `make ci-fast` instead of by a stalled vault PR. Mutation-checked: main's caller fails it.
- Verified before merge: hub `spoke_caller_info` -> `('ok', '', ['guard-and-automerge'])` (was
  `error`), `hub_pin_drift` still reads the pin as `checkout-ref`, actionlint clean, CI `build`
  green on `6fbd217`, Antigravity + Grok reviewed the exact head with zero findings (cursor and
  kimi lenses absent, quota), quorum floor 1 satisfied, zero review threads.

## Live verification

The first vault-only PR against the migrated caller is this handoff's own PR
(`vault/post-merge-pr890`). Expected: the spoke guard runs green (or refuses `lease_in_flight`
once), and the next hub sweep cycle lists `agorokh/ac-copilot-trainer#<N>` as `eligible` or
merges it, with no `caller-unreadable` skip. The observed discover log is posted as a comment
on #889; carry the result into the next handoff.

## Rule worth carrying

When rolling the hub pin in this file, change all THREE SHA occurrences together (`ref:`,
`path:`, `uses:`); `hub_pin_roll.py` does this textually, a hand roll must too. The other
local-checkout callers here (`process-miner.yml`, `steward-miner-rules.yml`) still use the
`.governance-hub` path; the vault sweep never reads them, so they were left alone.
