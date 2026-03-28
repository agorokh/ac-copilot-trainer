---
name: pr-resolution-follow-up
description: |
  After a PR is open, loop until CI is green and review threads (human + bots) are resolved.
  Triggers on "resolve PR", "fix review comments", "get PR green".
model: inherit
color: green
memory: project
---

# PR Resolution Follow-Up

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing.

**This agent owns** the only detailed procedure for **`sleep 600`**, **GraphQL `reviewThreads`**, and **check polling**. Other agents must **link here**, not copy those steps.

## Session lifecycle

- **LOAD:** Before entering the CI/review loop, complete vault LOAD per `docs/00_Core/SESSION_LIFECYCLE.md` (at minimum `Next Session Handoff.md`, `Current Focus.md`, and any `relates_to` subgraph needed for this PR).
- **SAVE:** After exiting this loop — success, green-with-follow-ups, or abandoned PR — run SAVE: update `Next Session Handoff.md` and record any new learnings as small linked vault nodes (or hand off explicitly in the handoff if the session ends abruptly).

## When to involve other agents

- If the PR diff is **only** dependencies, GitHub Actions, `.mcp.json`, or `security.yml` CVE tooling, run **`dependency-review`** first (Task `subagent_type=dependency-review` or read `.claude/agents/dependency-review.md`) for **risk summary + merge order**, then return here for the CI/bot loop.
- For **ambiguous repo policy** (branch naming, where files go), skim **`project-conventions`** or read **`AGENTS.md`** / **`10_Agent_Protocol.md`** before wide search.

## Context discipline

- Use **`gh pr view`** + **GraphQL** as the default control plane; avoid exploratory full-repo grep for “how we check PRs.”
- CI failures on **third-party** or **action** behavior: use **Context7** or workflow logs, not assumptions.

## Mandatory wait after each push (non-optional)

**After every `git push` that targets an open PR, wait ~10 minutes before the next poll.** Async bots (CodeRabbit, Cursor Bugbot, Copilot, etc.) routinely take several minutes; polling immediately causes false “done” reports and skipped work.

```bash
sleep 600   # 10 minutes — do not shorten for “speed”; this is the cooldown between bot runs
```

Only skip `sleep 600` if **every** third-party check on the PR is already `SUCCESS`/`COMPLETED` with **no** new inline threads expected (e.g. docs-only PR and bots already finished on the current SHA).

## Loop

1. `gh pr view <N> --repo <owner/repo> --json number,url,state,statusCheckRollup,reviewDecision`
2. If CI failed — pull logs, fix, commit, push, then **`sleep 600`** before returning to step 1.
3. **Review threads (use GraphQL for resolution state).** REST `GET /repos/{owner}/{repo}/pulls/{N}/comments` does **not** expose whether a conversation is resolved. Query **`reviewThreads`** on the pull request and treat **`isResolved: false`** (and not outdated, when relevant) as blocking work. Example: use **`-F`** for the PR number so `gh` sends a JSON **integer** for `Int!` (plain `-f p=3` is a string and will fail).

```bash
# Minimal thread state (valid GraphQL; expand fields if you need comment bodies)
gh api graphql \
  -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){reviewThreads(first:50){nodes{isResolved isOutdated path line}}}}}' \
  -f o=OWNER -f n=REPO -F p=3
```

Replace `OWNER`, `REPO`, and the integer `3` with the real owner, repository, and PR number. For **pagination** (`reviewThreads` has more than 50 threads), repeat with `after: $cursor` per GitHub GraphQL `PageInfo`.

If you need **full comment text**, add a nested `comments { nodes { author { login } body } }` selection — keep braces balanced (or paste the query into [GitHub’s GraphQL Explorer](https://docs.github.com/en/graphql/overview/explorer) to validate).

Use REST comments or `gh pr view --comments` only as **supplemental** context (e.g. quick scan); **do not** declare “all threads resolved” from REST alone.

4. Address each **unresolved** thread (code/doc fix + push, or a factual reply). After **any** push: **`sleep 600`**, then re-check checks **and** GraphQL threads from step 3.
5. Re-request human review when required (`gh pr edit --add-reviewer` or UI).
6. Repeat until all **required** checks pass and **no blocking unresolved review threads** remain (per GraphQL). Do **not** tell the user the PR is “fully resolved” until you have completed at least one post-push **`sleep 600`** when bots were pending on the latest SHA.

## Exit criteria (machine-checkable)

- Required checks **green** on latest SHA.
- GraphQL **`reviewThreads`**: no blocking **`isResolved: false`** (outdated-only threads may be non-blocking per team policy).
- If bots were still pending after the last push, at least **one** full **`sleep 600`** cycle completed since that push.

## Escalate to a human when

- Same root-cause CI failure after several fix attempts; **or** security/CVE policy tradeoff needs a product decision; **or** force-push / branch-protection exception required; **or** checks flaky or queued beyond reasonable wall-clock. Post a short PR comment: summary, links, options.

## Bots

Treat CodeRabbit, Bugbot, Copilot, and similar bots like human reviewers unless the finding is clearly invalid.

## Guardrails

- No force-push to shared branches unless team policy allows.
- No secrets in fixes.
- Keep changes scoped to the PR's intent; spin off follow-up Issues for scope creep.

## Exit

Stop when checks are green and **GraphQL `reviewThreads` shows no unresolved blocking threads** (or each is explicitly handled with a reply in the UI).
