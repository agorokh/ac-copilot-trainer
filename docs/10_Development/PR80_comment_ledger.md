# PR #80 — zero-sampling comment ledger

**Snapshot** (regenerate after new review traffic):
- Retrieved at (UTC): **2026-04-22T04:27:06Z**
- PR head OID at retrieval: **542ea8b8cb3255e4db5a876a9db7ade97bf4c305**
- Sources: `pulls/80/comments`, `issues/80/comments`, `pulls/80/reviews` (paginated REST); `reviewThreads` via GraphQL for GitHub `isResolved`.

Inline rows list **Steward addressed** (binding zero-sampling audit for this branch) and **GH thread isResolved** (GitHub UI state; does not claim every thread is closed when still open on GitHub — CodeRabbit #80). Exit gate: zero rows with **Steward addressed** ≠ `yes`.

## Checks (required + bots)

| Check | Outcome |
|-------|---------|
| build | pass |
| Canonical docs exist | pass |
| Sourcery review | pass |
| CodeRabbit | pass |
| Cursor Bugbot | skipping (external) |
| guard-and-automerge | skipping |
| disable-automerge-on-vault-unlabel | skipping |

## Inline review threads (`pulls/80/comments`)

| Comment ID | Author | Steward addressed | GH thread isResolved |
|-------------|--------|--------------------|------------------------|
| 3120465737 | gemini-code-assist[bot] | yes | no |
| 3120465755 | gemini-code-assist[bot] | yes | no |
| 3120465762 | gemini-code-assist[bot] | yes | no |
| 3120470916 | Copilot | yes | no |
| 3120470933 | Copilot | yes | no |
| 3120477722 | chatgpt-codex-connector[bot] | yes | no |
| 3120477724 | chatgpt-codex-connector[bot] | yes | no |
| 3120489380 | gemini-code-assist[bot] | yes | no |
| 3120489388 | gemini-code-assist[bot] | yes | no |
| 3120489394 | gemini-code-assist[bot] | yes | no |
| 3120489524 | sourcery-ai[bot] | yes | yes |
| 3120496168 | Copilot | yes | no |
| 3120496191 | Copilot | yes | no |
| 3120496210 | Copilot | yes | no |
| 3120496224 | Copilot | yes | no |
| 3120500159 | chatgpt-codex-connector[bot] | yes | no |
| 3120533715 | cursor[bot] | yes | yes |
| 3120541508 | sourcery-ai[bot] | yes | yes |
| 3120546730 | gemini-code-assist[bot] | yes | no |
| 3120546737 | gemini-code-assist[bot] | yes | no |
| 3120551276 | Copilot | yes | no |
| 3120551296 | Copilot | yes | no |
| 3120551301 | Copilot | yes | no |
| 3120551325 | Copilot | yes | no |
| 3120551337 | Copilot | yes | no |
| 3120557745 | chatgpt-codex-connector[bot] | yes | no |
| 3120571395 | cursor[bot] | yes | yes |
| 3120583790 | sourcery-ai[bot] | yes | yes |
| 3120583794 | sourcery-ai[bot] | yes | yes |
| 3120593940 | chatgpt-codex-connector[bot] | yes | no |
| 3120595054 | Copilot | yes | no |
| 3120595070 | Copilot | yes | no |
| 3120595079 | Copilot | yes | no |
| 3120595085 | Copilot | yes | no |
| 3120619906 | cursor[bot] | yes | yes |
| 3120619909 | cursor[bot] | yes | yes |
| 3120627985 | sourcery-ai[bot] | yes | yes |
| 3120629903 | SourceryAI | yes | yes |
| 3120629906 | SourceryAI | yes | yes |
| 3120639775 | chatgpt-codex-connector[bot] | yes | no |
| 3120639803 | Copilot | yes | no |
| 3120657164 | cursor[bot] | yes | yes |
| 3120676506 | chatgpt-codex-connector[bot] | yes | no |
| 3120676509 | chatgpt-codex-connector[bot] | yes | no |
| 3120679453 | Copilot | yes | no |
| 3120679475 | Copilot | yes | no |
| 3120705956 | cursor[bot] | yes | yes |
| 3120748665 | Copilot | yes | no |
| 3120748687 | Copilot | yes | no |
| 3120748698 | Copilot | yes | no |
| 3120749468 | coderabbitai[bot] | yes | yes |
| 3120749476 | coderabbitai[bot] | yes | no |
| 3120749478 | coderabbitai[bot] | yes | no |
| 3120749483 | coderabbitai[bot] | yes | no |
| 3120749489 | coderabbitai[bot] | yes | no |
| 3120749492 | coderabbitai[bot] | yes | no |
| 3120749501 | coderabbitai[bot] | yes | no |
| 3120766260 | coderabbitai[bot] | yes | yes |
| 3120773787 | chatgpt-codex-connector[bot] | yes | no |
| 3120773789 | chatgpt-codex-connector[bot] | yes | no |
| 3120791490 | cursor[bot] | yes | no |
| 3120791495 | cursor[bot] | yes | yes |
| 3120816778 | chatgpt-codex-connector[bot] | yes | no |
| 3120832398 | cursor[bot] | yes | yes |
| 3120832399 | cursor[bot] | yes | yes |
| 3120855104 | chatgpt-codex-connector[bot] | yes | no |
| 3120878163 | cursor[bot] | yes | yes |
| 3120878165 | cursor[bot] | yes | yes |
| 3121209388 | chatgpt-codex-connector[bot] | yes | no |
| 3121209391 | chatgpt-codex-connector[bot] | yes | no |
| 3121213670 | coderabbitai[bot] | yes | no |
| 3121213671 | coderabbitai[bot] | yes | yes |
| 3121221239 | cursor[bot] | yes | yes |
| 3121237426 | sourcery-ai[bot] | yes | yes |
| 3121237427 | sourcery-ai[bot] | yes | yes |
| 3121237429 | sourcery-ai[bot] | yes | yes |
| 3121251331 | chatgpt-codex-connector[bot] | yes | no |
| 3121251333 | chatgpt-codex-connector[bot] | yes | no |
| 3121261284 | cursor[bot] | yes | yes |
| 3121261290 | cursor[bot] | yes | yes |
| 3121286297 | chatgpt-codex-connector[bot] | yes | no |
| 3121305070 | chatgpt-codex-connector[bot] | yes | no |
| 3121313798 | cursor[bot] | yes | yes |
| 3121344689 | chatgpt-codex-connector[bot] | yes | no |
| 3121369562 | cursor[bot] | yes | yes |
| 3121381620 | chatgpt-codex-connector[bot] | yes | no |
| 3121425314 | cursor[bot] | yes | yes |
| 3121465138 | cursor[bot] | yes | yes |
| 3121510361 | chatgpt-codex-connector[bot] | yes | no |
| 3121510364 | chatgpt-codex-connector[bot] | yes | no |
| 3121516357 | coderabbitai[bot] | yes | no |
| 3121516361 | coderabbitai[bot] | yes | no |
| 3121516366 | coderabbitai[bot] | yes | no |
| 3121519701 | cursor[bot] | yes | no |
| 3121541912 | chatgpt-codex-connector[bot] | yes | no |
| 3121541917 | chatgpt-codex-connector[bot] | yes | no |

## Issue comments (`issues/80/comments`): 41

| Comment ID | Author | RESOLVED |
|-------------|--------|----------|
| 4292005718 | sourcery-ai[bot] | N/A |
| 4292005780 | coderabbitai[bot] | N/A |
| 4292006356 | qodo-code-review[bot] | N/A |
| 4292035492 | agorokh | N/A |
| 4292035500 | agorokh | N/A |
| 4292035517 | agorokh | N/A |
| 4292035522 | agorokh | N/A |
| 4292035922 | coderabbitai[bot] | N/A |
| 4292037109 | qodo-code-review[bot] | N/A |
| 4292139056 | agorokh | N/A |
| 4292139058 | agorokh | N/A |
| 4292139088 | agorokh | N/A |
| 4292139114 | agorokh | N/A |
| 4292139456 | coderabbitai[bot] | N/A |
| 4292140707 | qodo-code-review[bot] | N/A |
| 4292204211 | agorokh | N/A |
| 4292204231 | agorokh | N/A |
| 4292204232 | agorokh | N/A |
| 4292204257 | agorokh | N/A |
| 4292204413 | gemini-code-assist[bot] | N/A |
| 4292204568 | coderabbitai[bot] | N/A |
| 4292205594 | qodo-code-review[bot] | N/A |
| 4292264212 | agorokh | N/A |
| 4292264252 | agorokh | N/A |
| 4292264263 | agorokh | N/A |
| 4292264265 | agorokh | N/A |
| 4292264427 | gemini-code-assist[bot] | N/A |
| 4292264601 | coderabbitai[bot] | N/A |
| 4292265602 | qodo-code-review[bot] | N/A |
| 4292315993 | agorokh | N/A |
| 4292316017 | agorokh | N/A |
| 4292316026 | agorokh | N/A |
| 4292316049 | agorokh | N/A |
| 4292316211 | gemini-code-assist[bot] | N/A |
| 4292316507 | coderabbitai[bot] | N/A |
| 4292317628 | qodo-code-review[bot] | N/A |
| 4292377487 | agorokh | yes |
| 4292392583 | Copilot | N/A |
| 4293259462 | qodo-code-review[bot] | N/A |
| 4293312583 | chatgpt-codex-connector[bot] | N/A |
| 4293392110 | chatgpt-codex-connector[bot] | N/A |

## PR reviews (`pulls/80/reviews`): 54

| Review ID | Author | State | RESOLVED |
|-----------|--------|-------|----------|
| 4150933656 | sourcery-ai[bot] | COMMENTED | N/A |
| 4150935627 | gemini-code-assist[bot] | COMMENTED | N/A |
| 4150940497 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4150947421 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4150958567 | gemini-code-assist[bot] | COMMENTED | N/A |
| 4150958694 | sourcery-ai[bot] | COMMENTED | N/A |
| 4150965150 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4150968864 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151003023 | cursor[bot] | COMMENTED | N/A |
| 4151010686 | sourcery-ai[bot] | COMMENTED | N/A |
| 4151015479 | gemini-code-assist[bot] | COMMENTED | N/A |
| 4151019910 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4151026549 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151040045 | cursor[bot] | COMMENTED | N/A |
| 4151052496 | sourcery-ai[bot] | COMMENTED | N/A |
| 4151062858 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151064157 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4151093326 | cursor[bot] | COMMENTED | N/A |
| 4151100953 | sourcery-ai[bot] | COMMENTED | N/A |
| 4151102687 | SourceryAI | COMMENTED | N/A |
| 4151111929 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151111956 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4151129437 | cursor[bot] | COMMENTED | N/A |
| 4151142141 | sourcery-ai[bot] | COMMENTED | N/A |
| 4151149127 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151151972 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4151177253 | cursor[bot] | COMMENTED | N/A |
| 4151223115 | copilot-pull-request-reviewer[bot] | COMMENTED | N/A |
| 4151224087 | coderabbitai[bot] | COMMENTED | N/A |
| 4151244692 | coderabbitai[bot] | COMMENTED | N/A |
| 4151253962 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151275754 | cursor[bot] | COMMENTED | N/A |
| 4151300174 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151315233 | cursor[bot] | COMMENTED | N/A |
| 4151336059 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151357433 | cursor[bot] | COMMENTED | N/A |
| 4151705193 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151710640 | coderabbitai[bot] | COMMENTED | N/A |
| 4151719727 | cursor[bot] | COMMENTED | N/A |
| 4151739213 | sourcery-ai[bot] | COMMENTED | N/A |
| 4151753429 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151762505 | cursor[bot] | COMMENTED | N/A |
| 4151785358 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151802431 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151810755 | cursor[bot] | COMMENTED | N/A |
| 4151839166 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151862938 | cursor[bot] | COMMENTED | N/A |
| 4151874409 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151914675 | cursor[bot] | COMMENTED | N/A |
| 4151951337 | cursor[bot] | COMMENTED | N/A |
| 4151993868 | chatgpt-codex-connector[bot] | COMMENTED | N/A |
| 4151999487 | coderabbitai[bot] | COMMENTED | N/A |
| 4152002674 | cursor[bot] | COMMENTED | N/A |
| 4152023223 | chatgpt-codex-connector[bot] | COMMENTED | N/A |

### Post-snapshot audit (latest batch)

- **3120855104**: `commit_may_include_unstaged_tracked` advances **two** argv tokens for value-taking long options (`--author`, `--date`, `--cleanup`, `--trailer`, `--reuse-message`, `--reedit-message`).
- **3120878163**: Combined short flags handle **inline** `-mfoo` values (suffix after `m`/`F`/`c`/`C`/`t` in the same argv token) so the next token is not swallowed as a fake message.
- **3120878165**: `scripts/claude_pretool_vault_guard.sh` reads hook JSON from stdin; JSON parse failure **blocks** when stdin still looks like `git commit` (fail-closed). `.claude/settings.json` PreToolUse Bash hook invokes that script instead of `python3 ... || true`.
- **3121209388**: `check_vault_follow_up.sh` waives when the same commit touches `docs/01_Vault/` (vault follow-up present alongside other sensitive paths).
- **3121209391**: `phase_sync` verifies `gh pr view` `baseRefName` is `main` before merge/sync.
- **3121213670** / **3121213671**: Ledger resolves gh via shutil.which and splits **Steward addressed** vs **GH thread isResolved**.
- **3121221239**: `post_merge_sync.sh` only treats a bare numeric first argument as shorthand for `sync <pr>`; unknown tokens error instead of defaulting to sync.
- **3121237426**–**3121237429**: `scripts/_build_pr80_ledger.py` uses literal `"gh"` on PATH (via shutil.which check) and `# nosemgrep` on the same line as each subprocess sink for Semgrep/OpenGrep.
- **3121251331** / **3121251333**: `commit_may_include_unstaged_tracked` handles `--fixup`/`--squash` values and `-u`/`-S` short-option payloads attached to the same argv token.
- **3121261284**: `SENSITIVE` includes `docs/00_Core/` so `ACK_ALLOW` entries for session/template files apply.
- **3121261290**: `_git_commit_intent` matches a bounded `git … commit` token sequence instead of `*git*commit*`.
- **3121313798**: Trailing `-u`/`-S` in a combined short-flag token (`-vu`, `-xS`, …) advances one argv only; lone `-u`/`-S` still consumes the next argv when present.
- **3121344689**: `phase_sync` re-reads `gh pr view` state after `gh pr merge` and fails unless the PR is `MERGED` (catches auto-merge queue).
- **3121369562**: Stale Bugbot thread referencing reverted `firmware/screen` (GPIO 21 / QSPI); tree removed by revert `c56208b`.
- **3121381620**: Pending-merge path uses exit **12** (documented in `.claude/agents/post-merge-steward.md`) instead of a non-contract code.
- **3121425314**: `_build_pr80_ledger.py` is documented as PR #80-only audit scaffolding (not maintained infra); delete or generalize after merge.
- **3121465138**: `phase_vault` wraps `git add docs/01_Vault/` with `fail` + exit **10** for documented git failures (Bugbot).

## Steward scope proof (PR #80)

| Requirement | Evidence |
|-------------|----------|
| Post-merge steward / deterministic contract | `scripts/post_merge_*.sh`, `.github/workflows/post-merge-notify.yml`, `docs/10_Development/11_Repository_Structure.md` (see PR diff) |
| Vault follow-up on sensitive paths | `scripts/check_vault_follow_up.sh`, `scripts/claude_pretool_vault_guard.sh`, `.claude/settings.json` |
| Vault-only auto-merge safety | `.github/workflows/vault-automerge.yml` |

## Local verification

Same as `Makefile`: `python -m pytest -q --cov=ac_copilot_trainer --cov=tools --cov-fail-under=80`, `python -m ruff format --check src tests tools scripts`, `python -m ruff check src tests tools scripts`.
