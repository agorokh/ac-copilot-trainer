---
type: investigation
status: active
created: 2026-04-20
updated: 2026-04-20
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/02_Investigations/_index.md
---

# Post-merge determinism overhaul (April 2026)

## Context

The post-merge steward (`.claude/agents/post-merge-steward.md` + `scripts/post_merge_sync.sh`) has been deployed to 3 of ~6 fleet repos via Copier (template-repo, agent-factory, workstation-ops). Behavior varies wildly across hosts (Claude Code vs Cursor vs Codex) and across repos with different pre-commit / branch-protection setups. Real failure mode observed on `agorokh/agent-factory#52`: agent stashed WIP, committed vault docs to `main` with `SKIP=…` to bypass `no-commit-to-branch` and Hermes drift hooks, then `git push origin main` was rejected by branch protection — agent forced the human to push the docs commit manually.

## Findings

1. **Agent contract was implicitly "have main-write rights."** Steward's Phase C step 5 said _"vault SAVE on main when allowed; escalate if rejected."_ "When allowed" is undefined per repo and per host, producing non-deterministic outcomes.
2. **Pre-commit hooks are not docs-aware.** `no-commit-to-branch` and project drift hooks (e.g. Hermes drift checker) apply to all commits including pure docs SAVE commits. Agents work around this differently — `SKIP=…` env, `--no-verify`, or abandoning the commit.
3. **WIP collision was a `set -e`-style fail.** Old script exited at the top if working tree was dirty. Different agents handled this differently: stash, commit-and-revert, or leave files for human cleanup.
4. **No exit-code contract.** The script returned 0 or 1 with prose-only context, so agents had to LLM-interpret each failure — a recipe for divergence.

## Decisions (this overhaul)

- **Agent never pushes to `main`.** Vault SAVE writes to a `vault/post-merge-pr<N>` branch labeled `vault-only`; `.github/workflows/vault-automerge.yml` validates the diff is strictly under `docs/01_Vault/**` and enables GitHub auto-merge.
- **Two-phase script** — `sync` (merge / ff-pull / branch cleanup) and `vault` (scoped commit + branch + PR). WIP is auto-stashed under a named ref (`post-merge-pr<N>-wip`); recovery hint is printed on any non-zero exit.
- **Explicit exit-code contract** (0/2/10/11/12/13/20/30) consumed by the agent doc. Rule: _no improvising on non-zero._ No `SKIP=`, no extra `--no-verify`, no asking the human to push from main.
- **Scope guard** — `vault` phase refuses to commit if any non-vault tracked changes exist (exit 30). Prevents unrelated drift from sneaking into a docs PR.
- **PreToolUse vault-follow-up hook is now deterministic.** The previous `prompt`-type hook (lines 92–96 of `.claude/settings.base.json` pre-overhaul) required LLM acknowledgement to ALLOW/BLOCK; in Cursor and other hosts that cannot reply to hook prompts it auto-blocked, producing the same cross-host inconsistency we are fixing in the steward itself. Replaced with a `command`-type hook calling `scripts/check_vault_follow_up.sh`: blocks (exit 2) only when sensitive paths (`.claude/`, `docs/01_Vault/`, `scripts/`, `.github/workflows/`) are staged **without** a vault follow-up artefact (investigation, decision, handoff, SESSION_LIFECYCLE, or MAINTAINING_THE_TEMPLATE update). Identical behavior in Claude Code, Cursor, and Codex.

## Workstream B (deferred to follow-up PR)

Auto-file a `process-learning` issue in `template-repo` when a merged PR's "pain score" exceeds a threshold, computed from `gh` data only (commits-after-first-review, fix-up commits, CI red runs after first green, time-open-after-ready). Implementation lives in a `template-repo` GitHub Actions workflow triggered via `repository_dispatch` from each child's existing `post-merge-notify.yml` — keeps the central detector independent of any local agent behavior. Dedup by root-cause fingerprint (cluster of changed dirs + top review themes).

## Propagation

Children pin the template via `_src_path` in `.copier-answers.yml` and pull updates via `template-sync.yml`. After this PR merges and a new `template-YYYY.MM` tag is cut, every child running `template-sync` opens a PR adopting the new script + agent doc + workflow. **One-time per child:** `gh label create vault-only --description "post-merge handoff PR; auto-merged by bot"`. Until that label exists, vault PRs will be unlabeled and the auto-merge workflow will not act — the human merges manually as the safe fallback.

## Rollback

If the new behavior misfires in one repo: revert that child's `template-sync` PR; behavior returns to the old single-phase script. The `vault-only` label can be deleted to neuter the auto-merge workflow without code changes.
