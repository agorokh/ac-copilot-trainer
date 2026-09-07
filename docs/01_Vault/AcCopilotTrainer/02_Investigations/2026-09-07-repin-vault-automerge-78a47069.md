---
type: investigation
status: complete
created: 2026-09-07
updated: 2026-09-07
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Re-pin vault-automerge hub action to 78a47069 (2026-09-07)

Bumped the governance-hub `vault-automerge` composite action pin from `f5d9a873` to `78a47069`, picking up gov-hub #465 (refuse merge while a bot review round is unsettled) and gov-hub #476 (recover DIRTY vault PRs; stop sharing the handoff file). Action inputs are byte-identical between the two SHAs, so this is a drop-in pin bump. 1 occurrence in `.github/workflows/vault-automerge.yml` (line 50), in the checkout-ref shape: the workflow checks out `agorokh/governance-hub` at `ref: <SHA>` and then runs the action from the local `./.governance-hub/...` path, so the `actions/checkout` `ref:` is the pin. Flagged BEHIND by governance-hub `scripts/hub_pin_drift.py`; opened by the 2026-09-07 fleet re-pin pass. Merge is a separate pass.
