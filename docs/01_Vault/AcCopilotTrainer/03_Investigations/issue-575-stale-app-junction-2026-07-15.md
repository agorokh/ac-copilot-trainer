---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-15
updated: 2026-07-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/575
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Issue #575 — detect a stale AC app junction (harness preflight)

## Summary

The trainer app is installed as a junction
(`<ac_root>/apps/lua/AC_Copilot_Trainer` -> `<checkout>/src/ac_copilot_trainer`) while the harness
runs from its **own** checkout (usually a worktree). Nothing detected when the two disagreed, so the
rig silently executed app code the harness never saw. `preflight()` in
`tools/ac_harness/auto_drive.py` now compares the installed tree against the harness's own
`src/ac_copilot_trainer` and records `extras.run.app_install` in the evidence bundle.

Delivered by PR [#587](https://github.com/agorokh/ac-copilot-trainer/pull/587).

## Root cause of the original damage (EPIC #529 G1, 2026-07-14)

The junction target sat at `73ebe82` (PR #492, 2026-07-03 — ten days stale). Lap archives were
written with `car: "function_0xff"` (the callable-surface class #543 fixed), and a handshake run
produced **zero** valid lap archives, so the #543 friction fit could not promote and the #572
one-button pipeline correctly FAILed after an otherwise-clean 2-lap session. Hand-fixed that session
by detaching the primary checkout at the merged tip — but a hand-sync is not detection.

## Design: content digest, not a commit compare

Two checkouts can share a `HEAD` and still differ (dirty tree), and a junction may point at a non-git
export. So the **verdict is a content digest**; commits ride along as human-readable provenance so the
warning can name both versions.

**This choice was vindicated live** (see the true positive below): a concurrent session's worktree
sat at the *same commit* as ours while carrying an uncommitted Lua edit. The commit-compare the issue
originally proposed (`git rev-parse HEAD` on both sides) would have reported "up to date" and missed
it entirely.

`PreflightIssue` gained `severity` (default `"error"`, so every pre-#575 check stays fatal).

## Provenance is FOUR states, because strictness must split "unknown"

PR #587 review (Codex P2) caught that `--strict-app-version` promoted every `app_version` row to
fatal while the dataclass docstring claimed unknown never fails — code and docs disagreed. The
reviewer proposed gating on `drift` only; a Council pass (dissent 0.5) found a better resolution:
**"unknown" conflated two states with opposite risk profiles** ("presence vs identity").

| status | meaning | default | `--strict-app-version` |
|---|---|---|---|
| `match` | content equal | pass | pass |
| `drift` | proven different | warn | **fail** |
| `absent` | no app installed | warn | **pass** |
| `unverifiable` | app installed, version not establishable | warn | **fail** |

- **`absent`** — nothing installed can run the wrong code; a rig that doesn't run the Lua app is a
  legitimate config and must not be bricked by the flag.
- **`unverifiable`** — an app *is* installed but can't be compared (unreadable tree; harness has no
  source). Strict fails: a flag whose purpose is evidence integrity must not go green on "something
  is installed and I cannot tell what" — that is the silent false-confidence failure #575 exists to
  kill. Absence of proof is not proof of match, but absence of an *app* is not absence of proof.

Strictness gates on `AppInstallProvenance.blocks_strict` (the verdict), never on the row's presence.
`unverifiable` is narrow: a plain **copied** (non-junction, non-git) install is content-compared and
resolves to `match`/`drift` correctly.

## The two false-drift normalizations (found only by running it against the real rig)

A version check that cries wolf trains the operator to ignore the one time it is real — which is the
failure #575 exists to prevent. The first draft reported **drift on the real rig where there was
none**, twice:

1. **`__pycache__/*.pyc`** — the primary checkout carries it *inside* `src/ac_copilot_trainer`; a
   worktree does not. The AC Lua runtime never reads it. Now skipped.
2. **Line endings** — `.gitattributes` has `*.bat text eol=crlf`, and `start_sidecar.bat` differed
   between the primary checkout and a worktree **at the identical commit `8a3283f`**, purely in EOLs
   (exactly 41 bytes across 41 lines). Text is now compared EOL-insensitively; **binary is detected by
   a NUL byte** (git's own heuristic) and still hashes byte-exact, so a font/PNG differing by one byte
   is still drift.

Both are locked by regression tests, along with the inverse (a real one-character `.lua` edit is still
drift; a pure rename with identical bytes is still drift).

## Live verification (real rig, unmodified CLI path)

| scenario | result |
|---|---|
| Real rig junction -> primary checkout | `provenance: match`, `preflight ok`, exit `0` **even under `--strict-app-version`** |
| Real junction -> real checkout of `73ebe82` (the incident commit), default | `drift`, names `73ebe823d945` (installed) vs `8a3283f74c56` (harness), exit `0` |
| same + `--strict-app-version` | `PREFLIGHT FAILED [app_version]`, exit `2` |
| app absent | `absent`, `blocks_strict=False`, warning, no crash |

The drift case used a **real junction** to a **real git worktree** of the stale commit — not a mock.

## Provenance must be measured UNDER the rig lock (PR #587 review, Qodo)

The first draft computed provenance **before** `RigSessionLock.acquire()`. The installed app is
**shared rig state**, so a peer worktree can repoint the junction while we block on the lock:

- a pre-lock `match` could **bypass** `--strict-app-version` on an app that drifted since, and
- `extras.run.app_install` could record a version the rig never ran — the evidence bundle lying
  retroactively, which is worse than no bundle.

**The precedent already existed one block below the lock** and was walked past: plant/line artifact
resolution is deliberately post-lock because "a peer worktree may have re-identified this combo while
we waited on the lock, and resolving pre-lock would drive a stale in-memory plant". **Rule to
generalize: any read of shared rig state that gates a decision or lands in evidence belongs under the
rig lock.**

Fix: re-measure after `acquire()`; the post-lock verdict gates strict and lands in the bundle. The
pre-lock check stays as fast feedback (`--preflight-only` returns before the lock, unaffected). A
verdict that *changes* across the lock wait is surfaced on its own line. The decision is the pure
`app_provenance_recheck()` because `_main_impl` is `# pragma: no cover - rig-only CLI wiring` and AC3
requires rig-free unit coverage.

## The unplanned live true positive (the best evidence)

Mid-session the rig's junction was **concurrently repointed** by another session
(`autonomous-deliver-531-187940`, branch `feat/issue-531-partd-live-vitals`), whose worktree carries
an **uncommitted** edit to `src/ac_copilot_trainer/modules/telemetry_publisher.lua`. The check
reported `drift` and named that worktree unprompted.

Two lessons, both load-bearing:

1. **Both worktrees were at the same commit.** A `git rev-parse HEAD` compare would have said "up to
   date". Only the content digest caught it. This is the concrete justification for the design.
2. **The rig junction is shared, mutable, cross-session state** — see
   `issue-555-cross-worktree-rig-ownership`. A session can silently inherit another session's
   in-progress app. That is precisely #575's failure mode, and it is *live and recurring*, not
   historical.

Do **not** repoint the junction to your own worktree while another session owns the rig.

## Rig-ops note (important)

Test junctions were removed with `cmd /c rmdir` (**unlinks** the junction) and never with a recursive
delete — `Remove-Item -Recurse` / `rm -rf` on a junction can traverse into the **target**, and two of
the test junctions pointed at the **real AC install** (`content`, `extension`). The real AC install and
the rig's real app junction were both confirmed intact afterward.

## Out of scope

- Auto-syncing the checkout (state mutation of another worktree is an operator action) — and
  doubly so given the live finding above: a peer session may own the junction.

## The stale-build problem is now closed on BOTH halves

Verified live 2026-07-15 (`gh issue view 569 --repo agorokh/ac-copilot-trainer --json state` →
`CLOSED` at 02:57:49Z; `gh pr view 586` → `MERGED` `8a895ee`) — #569 landed *during* this PR's own
session, so do not carry it forward as pending:

| half | mechanism | status |
|---|---|---|
| Frozen Game Point EXE | `/health build_commit` + `--self-test` (#567/#568), `build_commit` baked into the EXE ([#569](https://github.com/agorokh/ac-copilot-trainer/issues/569), PR #586 `8a895ee`) | **CLOSED** |
| Lua app junction | preflight content-digest provenance + `--strict-app-version` ([#575](https://github.com/agorokh/ac-copilot-trainer/issues/575), PR #587 `b51e1d5`) | **CLOSED** |

Both artifacts the rig executes can now assert which build they are.
