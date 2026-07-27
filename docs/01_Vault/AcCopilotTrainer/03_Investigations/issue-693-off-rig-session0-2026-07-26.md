---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-26
updated: 2026-07-26
issue: https://github.com/agorokh/ac-copilot-trainer/issues/693
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-575-stale-app-junction-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-695-qss-apex-envelope-2026-07-26.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #693 — driving the harness from off-rig: the Windows session-0 trap (PR #694)

**Merged:** squash [`49f90f1`](https://github.com/agorokh/ac-copilot-trainer/commit/49f90f1),
PR [#694](https://github.com/agorokh/ac-copilot-trainer/pull/694); **#693 CLOSED**.
Follow-up to codify it as a script: [#697](https://github.com/agorokh/ac-copilot-trainer/issues/697).

## Why this existed

EPIC #529 recorded every outstanding gate as "blocked on rig availability" since 2026-07-22. Part of
that was not availability: the rig was reachable (`tailscale ping pc` → 11 ms), but **an SSH logon
lands in Windows session 0**, and nothing in the repo said so.

Two independent reasons a session-0 command can never drive AC:

1. **Redirection-trust mitigation.** Session 0 refuses to traverse the non-admin-created
   `apps/lua/ac_copilot_trainer` junction; the #575 provenance preflight is first to touch it, so the
   run dies with `OSError: [WinError 448] … untrusted mount point` and *looks like a harness bug*.
2. **No interactive desktop.** AC renders on the console session.

The working path is a `schtasks /IT` task, which executes in the console session and needs no stored
credential. Live signal that you landed right: `auto-drive: installed app provenance: match`.

## Every defect the review rounds found in a *documentation* block

Five rounds, six real Windows defects — the strongest argument for #697:

| Defect | Symptom |
|---|---|
| `<car>`/`<track>` in the generated `.cmd` | `cmd.exe` parses `<` as stdin redirection; dies before the harness runs |
| `<`/`>` in the run id | illegal in Windows paths and task names; `New-Item` fails |
| Fixed `/st 23:59` | `/create` fails once local time passes it — i.e. overnight |
| `/st` without `/sd` | a time computed after ~23:55 rolls to `00:xx`, read as earlier *today*, same failure |
| **Space anywhere in the path** | `create=0`, `run=0`, wrapper **never executes**, `Last Result: -2147024894`, empty evidence dir |
| Buffered Python | `stdout.log` empty for minutes; the SSH tail looks hung on a healthy run |

## Measured Windows facts (do not re-derive)

- **`/sd` is locale-dependent and the culture pattern is NOT interchangeable.** `MM/dd/yyyy` → `rc=0`;
  `M/d/yyyy` (this host's `ShortDatePattern`), `dd/MM/yyyy`, `yyyy/MM/dd` → all `0x80004005`.
- **A space in the path needs the 8.3 short path.** Bare and quoted both create + run "successfully"
  and never execute; `cmd.exe /c "…"` will not even create; `ShortPath` works (`Last Result: 0`).
- **`/sc ONDEMAND`** — which would remove the date problem entirely — is rejected by `schtasks /create`.
- **A duplicate `create` without `/f` does not error — it blocks** on the interactive "replace it?"
  prompt. So `/f` must stay; collisions are prevented by a unique run id (`+ $PID + Get-Random`).
- **`$LASTEXITCODE` works fine in Windows PowerShell 5.1** (`5.1.26100.8894`, Desktop) — a reviewer
  claim that it is PS7+ only was reply-invalid'd with a measurement.

## Rig invariants confirmed this session

- The AC app junction serves the **primary checkout**, which must sit at the merged `main` tip. It was
  found on `chore/issue-677-post-merge-vault` @ `971c103` (already on main as `b80ab38`), i.e. the
  #575/#543 stale-Lua trap, and detached to `origin/main`.
- `main` may be pinned by a peer worktree — `git switch main` fails; **detach at `origin/main`** instead.
