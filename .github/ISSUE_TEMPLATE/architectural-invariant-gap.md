---
name: Architectural invariant gap
about: Report a gap between a documented invariant and actual runtime behavior (agent or human-detected)
title: "Invariant gap: <invariant-name> — <one-line symptom>"
labels: ["architecture", "invariant-gap"]
assignees: []
---

<!--
Required reading before filing this issue:
- docs/01_Vault/ProjectTemplate/00_System/invariants/_index.md (or your renamed vault key)
- AGENT_CORE_PRINCIPLES.md § "Architectural invariant gap" routing rule

When this template applies: an agent or operator detected runtime behavior that
contradicts a documented invariant (e.g. an agent writing to a deprecated
side-channel, a deploy host with a `.env` file, a Tier-3 substrate routing
calls through the wrong provider). File this issue against THIS template repo
so the structural fix lives at the hub and propagates to every child.

Tactical patches in child repos for invariant violations are FORBIDDEN
(see AGENTS.md § routing rule) — they perpetuate the failure.
-->

## Invariant

**Canonical node:** `docs/01_Vault/<ProjectKey>/00_System/invariants/<name>.md`

Quote the rule verbatim:

> ...

## Evidence of violation

What did you observe? Be concrete — commands run, files inspected, agent transcripts, container env dumps. Link to the relevant session, PR, or postmortem note in the vault.

- **When:** YYYY-MM-DD HH:MM UTC
- **Where:** repo + path (or deploy host + service)
- **How detected:** (agent self-detected mid-session / human noticed in review / monitoring alert / postmortem)
- **Artifact links:** session ID, PR URL, vault investigation node, container logs

## Root cause

Why did the gap exist? Was the invariant:

- [ ] Not documented (only oral tradition)?
- [ ] Documented but in a file no agent / human reads at the right moment?
- [ ] Documented but contradicted by a deeper default (e.g. Claude Code's built-in auto-memory instruction)?
- [ ] Enforced only at one layer (e.g. compose) but bypassable by another (e.g. an overriding `.env`)?
- [ ] Drift over time (worked at PR-merge, broke under quiet config change)?
- [ ] Tactical patch in a child repo was never promoted upstream?

## Proposed hardening

Concretely, what should change in **this template repo** so the gap cannot recur? At minimum cover:

- **Vault edit:** new invariant node, ADR, or routing-rule update.
- **Runtime enforcement:** hook, CI assertion, `make <area>-doctor` probe, or `propagation_manifest.yml` invariant.
- **Agent prompt edit:** `.claude/agents/*.md` or `.cursor/rules/*.mdc` change so future sessions catch the gap earlier.

## Propagation map

After this issue's template-repo PR merges, which child repos need a follow-up PR? Order by tier / criticality. Hermes Steward picks these up from the `propagation_manifest.yml`.

| Repo | Change |
|---|---|
| `template-repo` | (this PR) |
| `agorokh/<child>` | ... |

## Validation plan

How will you prove the gap is closed? Be specific:

- **CI test:** `tests/test_<area>.py::test_<assertion>`
- **`make` target:** `make <area>-doctor`
- **`propagation_health_check.py` invariant id:** `<id>` flips children from `tracking` → `converged`.
- **Manual recheck:** one-time operator action (deploy host inspection, container env dump).

## Acceptance criteria

This issue is complete when:

- [ ] Vault invariant node (new or updated) is on `main`.
- [ ] CI / runtime enforcement listed above is on `main`.
- [ ] `propagation_manifest.yml` carries the new invariant id (when fleet-scoped).
- [ ] Per-child tracking issues are filed (when fleet-scoped).
- [ ] Validation plan items pass.
