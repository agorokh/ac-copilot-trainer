---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-01
updated: 2026-07-01
issue: https://github.com/agorokh/ac-copilot-trainer/issues/438
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
---

# PR #441: voice_signature staleness gate (#438)

## Summary

[PR #441](https://github.com/agorokh/ac-copilot-trainer/pull/441) squash-merged as `65e9d42`
(2026-07-02T03:35:12Z UTC); [#438](https://github.com/agorokh/ac-copilot-trainer/issues/438)
**CLOSED**. `Manifest.validate()` now enforces the persona/prosody/intensity portion of
`voice_signature`, closing the residual gap `vocabulary_hash` cannot see: wording-identical
persona swaps, prosody-chain edits, or intensity-chain bumps no longer accept a stale bank.

## Design decisions (load-bearing)

- **`endswith`, not equality or substring.** The suffix is the FINAL segment of every backend's
  signature (documented at `bake._signature_suffix`). Equality would reject portable banks over
  the host-varying ffmpeg major (`ffN`); substring would let `+intensity2` accept `+intensity21`.
- **`PROSODY_VERSION` moved `bake.py` → `vocabulary.py`** (codex P2 on the first push): it sat in
  `ProsodyShaper.signature` BEFORE the enforced suffix, so prosody-only edits were still
  unenforced — the exact #438 gap. The stdlib-only manifest gate cannot import the bake stack, so
  the constant lives with the other persona metadata. `EXPECTED_SIGNATURE_SUFFIX` =
  `{persona}+prosody{N}+intensity{N}`; shaper signature keeps only `ffN`.
- **`bake_bank()` fails fast** (Qodo Optional finding, fixed with deliberate deviation): raises
  `ValueError` before rendering when the backend signature lacks the suffix. Auto-append was
  rejected — stamping a provenance the backend never declared would forge what the gate verifies.
  Qodo explicitly accepted the deviation on the PR.

## Environment failures owned (Windows host `pc`)

- **governance-hub was 100 commits stale** at `~/.fleet-governance` (626266f → b08f6c9), missing
  `runtime/inference_egress` → `tests/test_process_miner/test_distill.py` failed collection.
  Local mods (install.ps1/install.sh/cursor wrappers, 87 lines) preserved on hub branch
  `wip/windows-install-mods-2026-07-01` (commit `63c530b`) — **operator: reconcile or drop**;
  upstream changed the same files.
- **`python3` missing on PATH** breaks (a) `make ci-fast` `ci-secrets` (recipe lines with trailing
  comments route through `/usr/bin/sh`), (b) the hub `prepare-commit-msg` hook
  (`#!/usr/bin/env python3`). Session fix: copied `.venv/Scripts/python.exe` → `python3.exe`
  (uv-style, gitignored) + `PYTHON=python make ci-fast`. Durable fix belongs in hub `install.ps1`.
- **MSYS path conversion mangles slash-command bot triggers**: `gh pr comment --body '/gemini
  review'` posted `C:/Program Files/Git/gemini review`. Always use `MSYS_NO_PATHCONV=1` for bodies
  starting with `/`. Same class: `gh api /repos/...` needs no leading slash; `2>/dev/null` in Bash
  commands trips the memory gate's touched-path parser.

## Post-merge state

- `post_merge_classify.py --pr 441`: no migration/env/deps/script/workflow flags.
- `post_merge_sync.sh sync 441` exited 10: its auto-stash of the primary checkout's dirty WIP
  (branch `feat/issue-402-data-platform`, tracked: delta.lua, coach_report.py, protocol.py, 3 test
  files; untracked: 4 vault investigation drafts + `docs/05_Architecture/` diagrams +
  sector-benchmark files + `.codex/config.toml`) failed to pop against new main. **All of it is
  preserved as `stash@{0}` (`post-merge-pr441-wip`)**; the failed partial application was cleared
  so `main` is clean at `65e9d42`. An older `stash@{1}` (`post-merge-pr417-detached-residue`)
  also awaits review. The pruned local branch `feat/issue-402-data-platform` had a deleted
  upstream (#402 is CLOSED, PR #415 merged) — the stashed WIP may be post-merge leftovers, but
  the vault drafts inside it look unshipped: **next session should `git stash show` / `apply` in
  a scratch worktree and promote what is real.**
