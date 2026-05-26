---
name: resolve-pr
description: Loop until a PR's CI is green and all review threads (human + bot) are resolved. Use after opening a PR or when asked to fix review comments.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# PR Resolution Follow-Up

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing.

**This agent owns** the only detailed procedure for **`sleep 600`**, **GraphQL `reviewThreads`**, and **check polling**. Other agents must **link here**, not copy those steps.

## Tier-3 Substrate Query (mandatory first step)

**Before entering the CI/review loop**, query the semantic substrate for prior bot-resolution patterns and PR history on the touched modules. The loop's value depends on having prior PR-resolution context **before** the first `gh pr view` — otherwise the agent treats each bot comment cold and re-discovers resolutions that already happened in previous PRs.

**Template** (starting point — refine after the first response):

```
mcp__agentic-memory__query_knowledge_graph(
    prompt="PR #<P> review patterns | prior bot resolutions for <module> | CI failure history | invariant violations flagged in prior PRs",
    workspace="<resolved from ops/memory_manifest.yml by repo basename>",
    limit=80,
)
```

**Refinement** (encouraged): after the first `gh pr view`, follow up with queries naming the specific bot whose threads are open (CodeRabbit, Gemini, Qodo, Sourcery, Copilot, Cursor Bugbot) — prior resolution patterns differ per reviewer.

**Workspace resolution**: read `ops/memory_manifest.yml`; match the workspace whose `name` matches this repo's basename. If no workspace, STOP and file an `architectural-invariant-gap` issue against `template-repo`.

**Surfacing**: include the substrate response under `## Pre-loaded substrate context` in your first reply, before the first `gh pr view`. This gives prior patterns to compare new bot threads against ("we already resolved this class last quarter").

## Session lifecycle

- **LOAD:** (1) Execute the Tier-3 substrate query from § **Tier-3 Substrate Query** above. (2) Complete vault LOAD per `docs/00_Core/SESSION_LIFECYCLE.md` (at minimum `Next Session Handoff.md`, `Current Focus.md`, and any `relates_to` subgraph needed for this PR). Tier-3 and vault are complementary; do not treat reading the handoff as a substitute for the substrate query.
- **SAVE:** After exiting this loop — success, green-with-follow-ups, or abandoned PR — run SAVE: update `Next Session Handoff.md` and record any new learnings as small linked vault nodes (or hand off explicitly in the handoff if the session ends abruptly).

## When to involve other agents

- If the PR diff is **only** dependencies, GitHub Actions, `.mcp.json`, or `security.yml` CVE tooling, run **`dependency-review`** first (Task `subagent_type=dependency-review` in Claude Code, or **`generalPurpose`** + `.claude/agents/dependency-review.md` in Cursor — see `.cursor/rules/cursor-task-delegation.mdc`) for **risk summary + merge order**, then return here for the CI/bot loop.
- For **ambiguous repo policy** (branch naming, where files go), skim **`project-conventions`** or read **`AGENTS.md`** / **`10_Agent_Protocol.md`** before wide search.

## Context discipline

- Use **`gh pr view`** + **GraphQL** as the default control plane; avoid exploratory full-repo grep for “how we check PRs.”
- CI failures on **third-party** or **action** behavior: use workflow logs and official docs first; use **Context7** only when installed (otherwise do not block on it), not assumptions.

## Mandatory wait after each push (non-optional)

**After every `git push` that targets an open PR, wait ~10 minutes before the next poll.** Async bots (CodeRabbit, Gemini Code Assist, Cursor Bugbot, GitHub Copilot, Qodo / PR-Agent, Sourcery) routinely take several minutes; polling immediately causes false “done” reports and skipped work.

```bash
sleep 600   # 10 minutes — do not shorten for “speed”; this is the cooldown between bot runs
```

Only skip `sleep 600` if **every** third-party check on the PR is already `SUCCESS`/`COMPLETED` with **no** new inline threads expected (e.g. docs-only PR and bots already finished on the current SHA).

## Bot triggers after each push (non-optional for PR branches)

Run these **after every `git push`** that targets the open PR (before or immediately after starting the `sleep 600` window—triggers and wait work together):

1. **CodeRabbit:** `gh pr comment <P> --repo <owner/repo> --body '@coderabbitai review'`
2. **Gemini Code Assist:** `gh pr comment <P> --repo <owner/repo> --body '/gemini review'`
3. **Copilot code review (if enabled):** On GitHub.com with `gh` **≥ 2.88**, `gh pr edit <P> --repo <owner/repo> --add-reviewer @copilot` (check `gh pr edit --help` for your version). On GitHub Enterprise Server or if CLI support is missing, use the PR **Reviewers** UI.
4. **Qodo (PR-Agent):** `gh pr comment <P> --repo <owner/repo> --body '/review'`
5. **Sourcery:** `gh pr comment <P> --repo <owner/repo> --body '@sourcery-ai review'`
6. **Cursor Bugbot:** no PR comment trigger—expect automatic runs; triage its threads like any other reviewer.
7. **`sleep 600` must run in the foreground** in the same session (not `run_in_background` / detached). Short polls after the full wait are fine; skipping the wait requires meeting the exception in § Mandatory wait above.
8. **Watermark audit:** Record the push completion time (UTC). When querying `reviewThreads` or scanning comments, treat items **created or updated after** that watermark as the primary signal set for “new bot work on this SHA,” so pre-push threads do not mask new failures.

## Loop

**`<P>`** is the **pull request** number (the **#** on the PR). It can differ from a GitHub **issue** number when you started from the issue-driven orchestrator.

1. `gh pr view <P> --repo <owner/repo> --json number,url,state,isDraft,statusCheckRollup,reviewDecision`
1a. If the PR is still **draft** (`isDraft: true`), mark it ready first: `gh pr ready <P> --repo <owner/repo>`. Draft PRs suppress CODEOWNERS-requested reviewer notifications and block merging until marked ready; status checks (CI/Actions) still run for drafts. Then **`sleep 600`** before continuing to steps 2–3 (same async-bot cooldown as after a `git push`).
2. If CI failed — pull logs, fix, commit, push, then **`sleep 600`** before returning to step 1.
3. **Review threads (use GraphQL for resolution state).** REST `GET /repos/{owner}/{repo}/pulls/{P}/comments` does **not** expose whether a conversation is resolved. Query **`reviewThreads`** on the pull request and treat **`isResolved: false`** (and not outdated, when relevant) as blocking work. Example: use **`-F`** for the PR number so `gh` sends a JSON **integer** for `Int!` (plain `-f p=3` is a string and will fail).

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

Treat CodeRabbit, Gemini Code Assist, Cursor Bugbot, GitHub Copilot, Qodo / PR-Agent, and Sourcery like human reviewers unless the finding is clearly invalid.

## Guardrails

- No force-push to shared branches unless team policy allows.
- No secrets in fixes.
- Keep changes scoped to the PR's intent; spin off follow-up Issues for scope creep.

## Exit

Stop when checks are green and **GraphQL `reviewThreads` shows no unresolved blocking threads** (or each is explicitly handled with a reply in the UI).

<!-- memory-contract:start -->
<!-- DO NOT EDIT BY HAND. Re-render with: python3 scripts/merge_memory_contract.py -->

## Memory contract (pointer)

The substantive memory rules for this skill live in the file's **`## Tier-3 Substrate Query (mandatory first step)`** section above. They are placed before the procedure on purpose, so the agent reads them in execution order.

References:

- Canonical contract: [`docs/00_Core/MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md).
- Canonical invariant: [`memory-three-tiers.md`](../../../docs/01_Vault/AgentFactory/00_System/invariants/memory-three-tiers.md).
- Runtime enforcement: `scripts/hook_memory_gate.py` (PreToolUse gate blocks code-path edits without a fresh, file-relevant Tier-3 stamp). Stop-hook drift audit removed 2026-05-20 per slim-down ADR (#205).
- Kill switch: `CLAUDE_MEMORY_GATE=0` bypasses the gate; surface why in the vault SAVE so the next session can correct.

Originating postmortem: [template-repo#115](https://github.com/agorokh/template-repo/issues/115).

<!-- memory-contract:end -->
