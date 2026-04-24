# Propagation strategy: template to child repos

**Status:** Active
**Created:** 2026-04-02
**Last inventory update:** 2026-04-14 (disclosures-discovery alignment note)
**Category:** Core

---

## Executive summary

There is no safe automated way to propagate template changes to the existing fleet today. Copier cannot be used because no child repo has `.copier-answers.yml`, and running `copier copy` from scratch would overwrite years of per-repo customization. The strategy is: **manual, per-repo, file-by-file migration now; Copier onboarding per-repo when convenient; automated sync only after onboarding.**

---

## 1. The `.claude/settings.json` problem (solve first)

This is the single most dangerous file. It is JSON (no merge markers), it is the most customized file across the fleet, and the template version is not even the richest -- Alpaca_trading has hooks the template lacks.

### Solution: compositional hooks via merge script

**Do not propagate `.claude/settings.json` as a monolithic file.** Instead:

1. **In the template**, create `scripts/merge_settings.py` that:
   - Reads a base `.claude/settings.base.json` (template-provided, git-tracked)
   - Reads an overlay `.claude/settings.local.json` (per-repo overrides, gitignored or tracked per repo choice)
   - Deep-merges hook arrays (base hooks + local hooks, no duplicates by hook command hash)
   - Writes the final `.claude/settings.json`
   - Runs via `make merge-settings` (or a git hook you add locally)

2. **For migration**, in each child repo:
   - Diff the child's current `settings.json` against the template's
   - Extract child-only hooks into `.claude/settings.local.json`
   - Adopt the template's `settings.base.json`
   - Run the merge script

3. **Add `.claude/settings.json` to `_skip_if_exists`** in `copier.yml` so future Copier updates never touch it. The merge script is the sync mechanism for hooks, not Copier.

**Why this works:** Each repo keeps its domain hooks. Template upgrades flow through `settings.base.json`. The merge script is idempotent. JSON never sees conflict markers.

### Interim (before the merge script exists)

Manual per-repo patching. For each child, the propagation checklist for #37/#38 changes to `settings.json` is:

| Hook change | What to do in each child |
|-------------|-------------------------|
| Stop timeout 60s -> 120s | Find the Stop hook, change `timeout` value. Safe everywhere. |
| PostToolUse vault-dirty marker | Add the new hook block to PostToolUse Edit/Write array. Safe everywhere. |
| SessionStart knowledge summary | Add only if repo has `init-knowledge` / knowledge DB. Skip for repos without it. |
| Stop debrief writer | Add only if repo has session_debrief.py. Skip otherwise. |

---

## 2. Tiered migration plan

### Tier A: closest to template (ac-copilot-trainer, dial-sandbox)

These repos have full vault structure and standard hooks. Migration path:

1. **Cherry-pick safe files** from template: `Makefile` additions (new targets), new scripts (`scripts/ci_secrets.sh`, `scripts/init_knowledge_db.py`), `.pre-commit-config.yaml` changes, `pyproject.toml` dependency additions.
2. **Manually patch** `.claude/settings.json` per the hook checklist above.
3. **Onboard to Copier** (one-time, roughly 30 min per repo):
   - Create `.copier-answers.yml` by hand with correct `project_key`, `package_name`, `project_name`, `_src_path`.
   - Run `copier update --trust --skip-answered` to verify it does not destroy anything.
   - If clean, commit. If not, abort and fix `_skip_if_exists`.
4. **After Copier onboarding**, these repos get the `template-sync.yml` workflow for future automated PRs.

**Risk:** Low. These repos are close enough that Copier diffs will be small and reviewable.

### Tier B: evolved beyond template (Alpaca_trading, case_operations)

These repos have RICHER configurations than the template. Migration is bidirectional.

**Alpaca_trading (progenitor):**
1. **Reverse flow first.** Audit Alpaca's `.claude/settings.json` for hooks the template should adopt. Open a PR on template-repo to upstream those hooks.
2. **Then forward-propagate** only the NEW items from #37/#38 that Alpaca does not already have (detect-secrets, init-knowledge, Bandit scope).
3. **Do NOT onboard to Copier.** Alpaca's structure diverged enough that Copier updates would produce large, noisy diffs. Continue with manual propagation and the merge-script pattern.
4. **case_operations** has a sibling-repo guard hook and custom hooks. Same approach: manual propagation of specific changes, no Copier onboarding until structural alignment improves.

**Risk:** Medium. These repos can regress if template overwrites their richer hooks. Manual review is mandatory.

### Tier C: partial adoption (disclosures-discovery, court-fillings-processing)

These repos have different structures and would not benefit from full template sync.

**disclosures-discovery** (inventory as of **2026-04-14**):
- **Role:** Forensic financial pipeline (SQLite corpus); not the template Python package / `AcCopilotTrainer` vault layout. **Tier C selective propagation** remains the right classification.
- **What is aligned (manual, scoped):** Compositional Claude settings — `scripts/merge_settings.py`, `.claude/settings.base.json`, `make merge-settings`, and CI check `ci-claude-settings` in `Makefile`; tracked `.cursor/rules/` and `.cursor/skills/` via `.gitignore` exceptions; vault-memory skill and memory rules; handoff still uses `docs/00_State/` with canonical notes under `docs/01_Vault/` (user taxonomy, not template graph rename).
- **What is explicitly out of scope:** `copier copy` / `copier update`, `.copier-answers.yml`, and `template-sync.yml` automation — **not planned** for this repo; continuing parity is **selective file copy** when a template change is worth porting.
- **Older checklist items superseded:** The per-repo checklist below that said “do NOT add vault-dirty / SessionStart vault handoff” assumed no vault paths. The repo now uses vault-dirty-style hooks **only** where paths match `docs/01_Vault/*` and `docs/00_State/*` (see child’s `settings.base.json`). Do not treat the old “no vault” bullets as current.
- **Proof of alignment work:** [disclosures-discovery#142](https://github.com/agorokh/disclosures-discovery/issues/142) / [PR #143](https://github.com/agorokh/disclosures-discovery/pull/143).

**court-fillings-processing:**
- Has no `.claude/` directory at all. Would BENEFIT from template hooks.
- Propagate: copy `.claude/settings.json` wholesale (no existing hooks to preserve), copy scripts, Makefile.
- This is the one repo where a fresh `copier copy` might actually work, but test in a branch first.

---

## 3. What specifically propagates from #37 and #38

### From #37 (PR #41, current branch)

| File/change | Type | Propagation method |
|-------------|------|-------------------|
| `scripts/ci_secrets.sh` | New file | Copy to all repos that have `detect-secrets` in pre-commit |
| `scripts/init_knowledge_db.py` | New file | Copy to repos that want knowledge DB |
| `Makefile` `init-knowledge` target | Addition | Append to child Makefiles (check for conflicts with existing targets) |
| `Makefile` Bandit scope `src` only | Change | Update in each repo (adjust path to repo's actual src dir) |
| `.claude/settings.json` Stop timeout | Value change | Manual edit per repo |
| `.claude/settings.json` vault-dirty marker | New hook | Manual addition per repo |
| `.pre-commit-config.yaml` detect-secrets | Addition | Add to each repo's pre-commit config |

### From #38 (not yet merged to template)

| File/change | Type | Propagation method |
|-------------|------|-------------------|
| `scripts/bootstrap_knowledge.py` | New file | Copy to repos that want knowledge bootstrap |
| `scripts/session_debrief.py` | New file | Copy to repos that want session debrief |
| `.claude/settings.json` SessionStart knowledge hook | New hook | Manual addition, only if repo has knowledge DB |
| `.claude/settings.json` Stop debrief hook | New hook | Manual addition, only if repo has debrief script |
| Orchestrator instruction (consult knowledge DB) | Doc change | Manual update to repo's orchestrator doc |
| Miner threshold changes | Config change | Copy config files if repo uses process miner |

---

## 4. Per-repo migration checklists

### ac-copilot-trainer (Tier A)

```text
[ ] Copy scripts/ci_secrets.sh
[ ] Copy scripts/init_knowledge_db.py
[ ] Add init-knowledge target to Makefile
[ ] Update Bandit scope in Makefile (src only)
[ ] Patch .claude/settings.json: Stop timeout -> 120000
[ ] Patch .claude/settings.json: add vault-dirty PostToolUse hook
[ ] Add detect-secrets to .pre-commit-config.yaml
[ ] Create .copier-answers.yml and test copier update
[ ] Enable template-sync.yml workflow (already present but inert)
```

### dial-sandbox (Tier A)

```text
[ ] Same as ac-copilot-trainer checklist
[ ] Copy template-sync.yml workflow (not present yet)
```

### Alpaca_trading (Tier B -- reverse flow first)

```text
[ ] Audit Alpaca hooks -> PR to template for universal ones
[ ] After template absorbs Alpaca innovations:
[ ]   Copy scripts/ci_secrets.sh
[ ]   Copy scripts/init_knowledge_db.py
[ ]   Add init-knowledge target to Makefile
[ ]   Patch .claude/settings.json: Stop timeout (if not already higher)
[ ]   Patch .claude/settings.json: vault-dirty hook (if not already present)
[ ]   Add detect-secrets to .pre-commit-config.yaml
[ ] Do NOT run copier copy or copier update
```

### case_operations (Tier B)

```text
[ ] Copy scripts/ci_secrets.sh
[ ] Copy scripts/init_knowledge_db.py
[ ] Add init-knowledge target to Makefile
[ ] Patch .claude/settings.json: Stop timeout -> 120000
[ ] Patch .claude/settings.json: vault-dirty hook
[ ] PRESERVE sibling-repo guard hook (do not remove)
[ ] Add detect-secrets to .pre-commit-config.yaml
[ ] Do NOT run copier copy or copier update
```

### disclosures-discovery (Tier C)

**Current baseline (2026-04):** Merge-settings pattern and cursor policy tracking are **done** in the child repo. Treat the list below as **optional forward ports** from template when there is a concrete need — not a stale backlog.

```text
[x] merge_settings.py + settings.base.json + ci-claude-settings (done in disclosures-discovery)
[ ] Copy scripts/ci_secrets.sh (optional — if adding detect-secrets to pre-commit)
[ ] Copy scripts/init_knowledge_db.py + Makefile target (optional — only if adopting knowledge DB)
[ ] Patch timeouts / hooks in settings.base.json via merge (optional — follow template hook changelog)
[ ] Add detect-secrets to .pre-commit-config.yaml (optional)
[ ] Copier / template-sync — NOT planned; selective propagation only
```

### court-fillings-processing (Tier C)

```text
[ ] Create .claude/ directory
[ ] Copy .claude/settings.json from template wholesale (no existing hooks)
[ ] Copy scripts/ci_secrets.sh
[ ] Copy Makefile (or merge targets into existing)
[ ] Add detect-secrets to .pre-commit-config.yaml
[ ] Consider full copier copy in a test branch
```

---

## 5. Reverse flow: child -> template

### Process

1. Identify universal improvement in child repo (hook, script, workflow pattern).
2. Open an Issue on template-repo with label `upstream-sync`.
3. PR the change into template-repo, stripping any domain-specific paths, secrets, or project names.
4. After merge, tag `template-YYYY.MM` if it is a governance change.
5. Forward-propagate to other children per tier checklists.

### Known backlog (Alpaca_trading -> template)

Alpaca has the most evolved hooks in the fleet. Before propagating #37/#38 to Alpaca, audit these Alpaca-specific hooks for template adoption:

- Hook innovations unique to Alpaca (audit needed)
- Any PostToolUse patterns not in template
- Any PreToolUse guards not in template

This audit should happen BEFORE forward propagation to avoid the template overwriting something better.

---

## 6. Enforcement: how to drive adoption without breaking things

**You cannot enforce it. You can only make it easy and observable.**

### What you CAN do

1. **Visibility:** Create a `template-compliance` GitHub Action (runs in template-repo) that checks each child repo for the presence of key files and settings. Produces a dashboard or matrix. Does not modify anything.

2. **Opt-in automation:** For Tier A repos that complete Copier onboarding, `template-sync.yml` creates PRs automatically. The human reviews and merges. This is the closest to enforcement that is safe.

3. **Version tracking:** Add a `template_version` field to each child's `AGENTS.md` or a `.template-version` file. Template PRs bump this. Staleness is visible.

4. **Issue creation:** After each template release, a script (or scheduled workflow) opens an Issue in each child repo with the propagation checklist for that release. The Issue tracks adoption.

### What you CANNOT safely do

- Auto-merge template sync PRs (hooks can break, domain logic can regress).
- Run `copier update` without `.copier-answers.yml` (destructive).
- Force-push template files into children (overwrites customization).
- Use a bot to patch `.claude/settings.json` across repos (JSON is fragile, hooks are domain-specific).

---

## 7. Recommended execution order

1. **Now:** Manually propagate #37 changes to ac-copilot-trainer and dial-sandbox (Tier A, lowest risk, roughly 1 hour each).
2. **This week:** Audit Alpaca_trading hooks for reverse flow. Open template PR for universal hooks found.
3. **Next:** Onboard ac-copilot-trainer to Copier (create `.copier-answers.yml`, test `copier update`). This is the proof-of-concept for automated sync.
4. **Then:** Propagate #37 to Tier B repos (Alpaca, case_operations) manually, preserving their custom hooks.
5. **Build:** `scripts/merge_settings.py` for the compositional hooks pattern. Test on template-repo first.
6. **Defer:** court-fillings-processing until there is a concrete need. **disclosures-discovery** had a **2026-04** alignment pass (merge-settings, tracked `.cursor/` policy, vault-memory); further template updates remain **selective** — see Tier C inventory. Low ROI for full Copier or vault graph rename.

---

## 8. Long-term target state

```text
template-repo (tagged releases)
    |
    |-- copier update (Tier A repos, automated PRs via template-sync.yml)
    |     |-- ac-copilot-trainer
    |     |-- dial-sandbox
    |
    |-- manual propagation + merge_settings.py (Tier B repos)
    |     |-- Alpaca_trading (also reverse-flows innovations)
    |     |-- case_operations
    |
    |-- selective file copy (Tier C repos, only when actively maintained)
          |-- disclosures-discovery
          |-- court-fillings-processing
```

The merge-script pattern for `.claude/settings.json` applies to ALL tiers. Even Copier-onboarded repos should use it because `_skip_if_exists` for settings.json means Copier will never touch hooks -- the merge script is the sync channel for that file.
