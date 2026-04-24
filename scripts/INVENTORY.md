# Scripts inventory

Short index of `scripts/` entry points. Classification: **CI** (automation checks), **dev** (local workflows), **agent** (Claude / hook integration), **bootstrap** (new project / template).

| Script | Purpose | Class | Introduced |
|--------|---------|-------|------------|
| `bootstrap_knowledge.py` | Seed SQLite repo-knowledge DB from AGENTS.md, vault invariants, principles | dev / CI | #38 |
| `check_agent_forbidden.py` | Enforce repo layout / root file allowlist | CI | template |
| `check_bootstrap_complete.py` | Validate bootstrap / template completeness | CI | template |
| `check_vault_follow_up.sh` | PreToolUse Bash hook: block git commit if sensitive paths staged without vault follow-up (deterministic; works in Claude Code, Cursor, Codex) | agent | post-merge overhaul 2026-04 |
| `ci_policy.py` | Branch name + PR title checks (conventional commits) | CI | #42 |
| `check_policy_docs.sh` | Policy checks on canonical docs | CI | template |
| `copier_post_copy.py` | Copier task: rename vault + rewrite paths after `copier copy` | bootstrap | #27 |
| `cross_repo_aggregate.py` | CLI wrapper for cross-repo process miner aggregation | dev | template |
| `ingest_session_debriefs.py` | Merge Stop-hook JSONL into repo-knowledge SQLite (no GitHub) | dev | #46 |
| `init_knowledge_db.py` | Create empty repo-knowledge SQLite schema | dev / CI | template |
| `knowledge_session_summary.py` | SessionStart hook: print top patterns from knowledge DB | agent | #38 |
| `merge_settings.py` | Merge `.claude/settings.base.json` + `.claude/settings.local.json` → `settings.json` | dev | #40 |
| `post_merge_classify.py` | Post-merge: classify PR diff paths (migrations, env, deps, scripts, workflows) | dev / CI | #50 |
| `post_merge_sync.sh` | Post-merge two-phase steward (`sync` / `vault`): merge PR, sync main, prune; or commit vault edits to `vault/post-merge-pr<N>` branch + open `vault-only` PR. Explicit exit-code contract; never pushes to main. | agent | post-merge overhaul 2026-04 |
| `policy_tracked_files.sh` | Secret scan + tracked-file policy for CI | CI | template |
| `pre_commit_check_test_artifacts.py` | Pre-commit: block test markers / data files under `src/` (and markers in `tools/`) | dev | #43 |
| `process_miner.py` | Wrapper to run `tools.process_miner.run` | dev | template |
| `session_debrief.py` | Stop hook: append JSONL debrief record | agent | #38 |

Shell scripts are invoked from **Makefile** or GitHub Actions where noted in workflows.
