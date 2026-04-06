---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
source: process-miner
rule_fingerprint: 17e05ca30ccf0f0f
mined_from: 3 review comments across 2 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: reliability
preventability: guideline
---

# Code Server Send (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

While `urllib.request.urlopen` is used here with a timeout, it is a synchronous blocking call. In the context of a WebSocket ser...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `_sanitize_debrief` function collapses multiple spaces into one but does not handle potential markdown-like characters or ot...
- Follow-up from PR resolution pass (commits \ccd0cb1\, \0cb02a\):

- **\	ools.ai_sidecar\**: \rom .server import main\ so \__all__\ matches exports.
- **\ws_bridge\**: first connect without 5s delay;...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
