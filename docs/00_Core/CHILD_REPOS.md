# Child repositories

**Status:** Active  
**Category:** Core

Known repos spawned from (or aligned with) this template. Tiers reflect how safely **Copier** can be adopted and how propagation should run. See [PROPAGATION_STRATEGY.md](PROPAGATION_STRATEGY.md) and [MAINTAINING_THE_TEMPLATE.md](MAINTAINING_THE_TEMPLATE.md).

**Machine-readable hub view:** [Fleet inventory](../01_Vault/AcCopilotTrainer/fleet/_index.md) (`fleet_inventory.yml`) — refresh with `python3 scripts/fleet_inventory_refresh.py` and `GITHUB_TOKEN` / `GH_TOKEN`.

| Repo | Tier | Copier onboarded? | Last template-sync | CI status | Notes |
|------|------|-------------------|--------------------|-----------|-------|
| ac-copilot-trainer | A | No | manual | — | Full template v1.4 |
| dial-sandbox | A | No | manual | — | Full template v1.3 |
| Alpaca_trading | B | Never (progenitor) | manual | — | Richer hooks than template |
| case_operations | B | No | manual | — | Custom sibling-repo guard |
| disclosures-discovery | C | No | N/A | — | Flat `docs/00_State/`, no vault graph |
| court-fillings-processing | C | No | N/A | — | No `.claude/` dir |

## Quarterly review

1. Reconcile this table with org reality (new repos, archived projects, tier moves).
2. Spot-check **Tier A** for Copier onboarding candidates (`copier update` dry-run or docs-only PR).
3. Confirm **reverse flow** items from Tier B are tracked (open template PRs or Issues).

## When to invest in automation

Escalate (Issues on this template) when:

- Two or more **Tier A** repos are Copier-onboarded and need a shared sync playbook tweak.
- **template-sync** PRs repeatedly fail for the same class of conflict (then extend `_skip_if_exists` or merge tooling).
- Fleet-wide hook changes are blocked by JSON fragility — prioritize `settings.base.json` + `scripts/merge_settings.py` adoption.
