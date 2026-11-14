---
type: handoff
status: active
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/1001
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-203607Z-post-merge-pr998-989-stage0.md
---

# PR 1002: macOS / Python 3.14 host test failures fixed; local ci-fast can go green

PR https://github.com/agorokh/ac-copilot-trainer/pull/1002 merged as
`8e583e020a136c92ff2ef3b1582cf4759e6f93ea` at 2026-11-14T21:48:58Z. Vetted head was
`88bafb4f8c077a2bb92370fb91b113fe519e3bee`. #1001 is CLOSED by the merge, as intended. This
settles the "Local test host" item left open in the first `relates_to` node.

## What shipped

Ten tests failed on untouched `main` (`65dbf654`) on the macOS development host (Python 3.14.10,
lupa 2.8), so `make ci-fast` could not pass there. All ten were reproduced before the change.

- **Real fix (7 tests).** `tools/pressure_bench_oracle.py::_code_material` handed any constant
  type it did not know to `json.dumps`. Python 3.14 folds constant slices into `co_consts`, so
  `code_sha256()` raised `TypeError`. It now serializes `slice`, `complex` and every `float`
  (as `float.hex()`, which covers `inf`/`nan`) and raises `TypeError` on any other unknown type.
- **macOS-only skip (2 tests).** The LuaJIT tests in `tests/test_traffic_eligibility.py` skip
  when `sys.platform == "darwin"` and `lupa.luajit21` is missing, with the reason string
  `tests/test_setup_library_best.py` already uses. Two tests pin that Linux and Windows never skip.
- **Platform skip (1 test).** The real process-creation-time test in
  `tests/test_pressure_bench.py` skips when `sys.platform` is neither `win32` nor `linux`.

## Evidence

- macOS, three affected files: before `10 failed, 162 passed, 1 skipped`; after
  `177 passed, 4 skipped`. Full local `make ci-fast`: OK, `6163 passed, 74 skipped`.
- GitHub `build` at the vetted head: `6388 passed, 30 skipped`; neither new skip fired on Linux.
- On merge commit `8e583e02`: `build` and `conformance` succeeded.

## Review and merge

- Author vendor: `anthropic`. Merged from the roadmap-expansion session on the operator's
  instruction, not from the delivery session.
- As reported by the merging session: the exact-head review barrier exited 0, gated by the
  Antigravity and Grok lenses; the Cursor lens was absent on error. Read back afterward: one
  self-hosted reviewer comment marked terminal on `88bafb4f`, 0 review threads.
- Post-merge classification: no flags (no migrations, env, dependency or workflow changes).

## Consequences to know

- **Oracle hashes changed.** Any edit to the oracle changes `oracle_sha256` and
  `oracle_source_sha256`, so a #956 run registration sealed before `8e583e02` no longer
  validates. The merging session reported #956 open on a cap stop with no run in flight and the
  experiment disabled. This was not checked on the rig.
- **Float encoding in the fingerprint** moved from a JSON number to `float.hex()`.
- **Not deployed.** Nothing was pushed to the rig; the rig's primary checkout still needs its
  usual pull before it runs this oracle.

## Host notes for the next local run

- Plain `make ci-fast` fails at `ci-format` on this Mac: `python3` resolves to Homebrew 3.15,
  which has no ruff. Run `make ci-fast PYTHON=<repo>/.venv/bin/python`.
- The memory gate refuses Bash heredocs. Write files with the editor tool and pass `--body-file`.

## Sync state

`sync 1002` ran from the delivery worktree `sweet-rhodes-4a01df`: the primary checkout's `main`
fast-forwarded `a3d4dda0..8e583e02`, the local branch `fix/issue-1001-macos-py314-host-tests`
was deleted, and the worktree is detached at `origin/main`. The worktree itself was not removed;
it hosts the delivery session. Nothing else remains for #1001.
