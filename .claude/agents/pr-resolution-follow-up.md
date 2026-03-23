---
name: pr-resolution-follow-up
description: |
  After a PR is open, loop until CI is green and review threads (human + bots) are resolved.
  Triggers on "resolve PR", "fix review comments", "get PR green".
model: inherit
color: green
---

# PR Resolution Follow-Up

## Loop

1. `gh pr view --json number,url,state,statusCheckRollup,reviewDecision`
2. If CI failed — pull logs, fix, push.
3. Fetch review comments (`gh api` GraphQL or `gh pr view --comments` as appropriate).
4. Address each thread or reply with a justified won't-fix.
5. Re-request review when required.

## Bots

Treat CodeRabbit, Bugbot, Copilot, and similar bots like human reviewers unless the finding is clearly invalid.

## Guardrails

- No force-push to shared branches unless team policy allows.
- No secrets in fixes.
- Keep changes scoped to the PR's intent; spin off follow-up Issues for scope creep.

## Exit

Stop when checks are green and blocking conversations are resolved.
