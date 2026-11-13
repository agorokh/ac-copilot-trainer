---
type: entity
status: active
created: 2026-03-29
updated: 2026-04-04
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Workflow OS.md
issue: "https://github.com/agorokh/template-repo/issues/14"
---

# Epic #14 — Self-learning and template sync

Master **GitHub tracker:** https://github.com/agorokh/template-repo/issues/14

Implementation lands in child issues and their PRs; this node is the vault anchor for LOAD traversal.

Rows below use **GitHub issue state** (`CLOSED` = child delivered), not the narrative in older handoff drafts.

## Delivered (child issues closed)

| Issue | Scope | PR |
|------|--------|-----|
| [#15](https://github.com/agorokh/template-repo/issues/15) | Quick wins — agent memory, skill autonomy, self-learning hooks, rules, MCP, CI gates | [#29](https://github.com/agorokh/template-repo/pull/29) |
| [#21](https://github.com/agorokh/template-repo/issues/21) | Repo Intelligence Tier 1+2 — process miner, rule extraction, scheduling, knowledge graph | [#30](https://github.com/agorokh/template-repo/pull/30) |
| [#27](https://github.com/agorokh/template-repo/issues/27) | Template sync — Copier downstream sync + upstream failure feedback | [#32](https://github.com/agorokh/template-repo/pull/32) |
| [#37](https://github.com/agorokh/template-repo/issues/37) | Repo tooling — knowledge DB init, detect-secrets, Bandit scope, Stop hook | [#41](https://github.com/agorokh/template-repo/pull/41) |
| [#38](https://github.com/agorokh/template-repo/issues/38) | Close the learning loop — miner thresholds, consumption, session debriefs | [#45](https://github.com/agorokh/template-repo/pull/45) |
| [#39](https://github.com/agorokh/template-repo/issues/39) | pip-audit scope — mining and knowledge extras | [#47](https://github.com/agorokh/template-repo/pull/47) |
| [#40](https://github.com/agorokh/template-repo/issues/40) | Registry + propagation + merge tooling | [#48](https://github.com/agorokh/template-repo/pull/48) |
| [#42](https://github.com/agorokh/template-repo/issues/42) | CI hardening — caching, concurrency, conventional commits, CodeQL | [#49](https://github.com/agorokh/template-repo/pull/49) |
| [#43](https://github.com/agorokh/template-repo/issues/43) | Quality gates — ruff ASYNC/DTZ, pre-commit guards, test artifact check | [#51](https://github.com/agorokh/template-repo/pull/51) |
| [#44](https://github.com/agorokh/template-repo/issues/44) | Agent hooks — bot review protocol, knowledge capture, DDL guard | [#52](https://github.com/agorokh/template-repo/pull/52) |
| [#46](https://github.com/agorokh/template-repo/issues/46) | Session debrief ingest into knowledge DB | [#53](https://github.com/agorokh/template-repo/pull/53) |
| [#50](https://github.com/agorokh/template-repo/issues/50) | Post-merge steward — sync, classify, vault handoff | [#57](https://github.com/agorokh/template-repo/pull/57) |

## Active

| Issue | Scope | Notes |
|------|--------|------|
| [#26](https://github.com/agorokh/template-repo/issues/26) | Tier 3 — local fine-tuned reviewer (research) | Phase 1 merged ([#31](https://github.com/agorokh/template-repo/pull/31)); Phase 2 **scaffold** merged ([#63](https://github.com/agorokh/template-repo/pull/63)). Full training loop, Ollama export, and integration remain on **#26**. |
| [#70](https://github.com/agorokh/template-repo/issues/70) | Fleet-wide mining — noise filter, quality gates, S0/S2/S3 paths | Landed: `noise_filter.py`, scoped `learned/` dirs, `fleet.py`, `emit_cross_repo_learned`, aggregate universal = S0 keys. **Validation:** run `cross_repo_aggregate` with `GITHUB_TOKEN` + `MINING_USE_DEFAULT_FLEET=1` (optional `MINING_EMIT_LEARNED=1`) and review JSON + emitted rules. Prior flat noise rules removed from repo. |

## Dependency hint

- **#26** depends on Tier 1+2 (**#21**) for training-ready data paths (see **#26** body).
- Close GitHub **#14** when **#26** is complete, rescoped, or the epic is explicitly superseded.

## Vault hub PR

- Epic graph hub landed in **PR [#35](https://github.com/agorokh/template-repo/pull/35)** (`Refs #14`).

## Superseded (consolidated into children)

- #16–#20 → #15; #22–#25 → #21; #28 → #27.
