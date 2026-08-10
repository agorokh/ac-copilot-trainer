---
type: investigation
status: active
memory_tier: canonical
created: 2026-08-09
updated: 2026-08-09
issue: https://github.com/agorokh/ac-copilot-trainer/issues/738
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-g1-cold-p4-scientist-2026-08-08.md
  - AcCopilotTrainer/03_Investigations/issue-737-setup-race-retry-2026-08-09.md
  - AcCopilotTrainer/03_Investigations/issue-537-cm-cached-track-relaunch-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #738 — CM "Custom Shaders Patch data" dialog: in-launcher auto-skip (PR #743)

## Mechanism (CM Main Log forensics, all 20 logs of 2026-08-08 + today's)

`PatchBaseDataUpdater.TriggerAutoLoadAsync()` walks **multiple online categories sequentially**
("tracks configs list", "vertex AO patches for tracks list", …, each `enabled: True`); on a
failing boot each fetch hangs ~60 s (`ApiCacheThing` → TaskCanceledException → `Cannot get
data`). Several sequential hangs ≫ the 75 s `attempt_timeout` → the harness relaunch-loops while
CM re-opens the same dialog (~2× launch cycles/drive; #529 night: 15 launches / ~5 drives).

## Fix shipped (PR #743, branch `fix/issue-738-cm-dialog-skip`)

`tools/ac_harness/cm_dialog_watcher.py` — **stdlib-only raw-ctypes UI Automation** watcher
thread: EnumWindows → visible top-level windows of `Content Manager.exe` → UIA FindAll
(ControlType==Button) → Python-side case-insensitive name match `"Skip"` → InvokePattern.
Policy: 2-consecutive-poll confirmation before first click (healthy fast fetch left alone),
5 s per-window cooldown re-click (the failing fetch chains categories through ONE dialog).
Wired: `auto_drive.rig_launch` (spans all attempts; `--no-cm-dialog-skip` opt-out; evidence in
launch message + now `report.notes`) and `resilient_launch` retry loop (supervisor/Game Point
path; `csp_dialog_skips` in `report.launch`). 15 CI-safe policy tests (fake backend).

## Durable findings

1. **The real dialog's window title is `Waiting…`** — "Loading data for Custom Shaders Patch"
   is dialog *content*. Title-gated watchers would miss; button-based discovery caught it.
2. **Second click can hit `0x80040200` (UIA_E_ELEMENTNOTENABLED)** — CM disables Skip while it
   cancels the fetch. Benign; contained by the exception-bounded tick.
3. **CM `Values.data` is enciphered (v2)** — issue option 2 (externally pre-disabling the
   auto-load categories) is NOT safely feasible; only CM's own Settings UI can flip them.
   Documented in the PR; option 1 (auto-skip) makes it unnecessary for autonomous launches.
4. Successful `rig_launch` detail strings were **dropped on success** — only failures kept
   them. Now `launch: <detail>` lands in `report.notes` (overnight ladders read the bundle).

## Live proofs (operator-grade, 2026-08-09 on AG_PC)

- **Synthetic WPF dialog** (PowerShell, "Skip" button): watcher found + Invoked; the window's
  own Click handler closed it (`skips=1, clicks_failed=0`). Validates the raw COM vtables.
- **Real reproduction on the unmodified path**: `auto_drive --car bmw_m3_gt2 --track magione
  --driver ggv --wait-lap` at 17:07 local — today's CM log carries the same failing-fetch
  signature; the real dialog appeared and was **skipped at +8 s**; `PASS (stage=done)`,
  **attempts=1**, 1 timed lap 106.224 s, 210.8 km/h, HUD RENDERING (screenshot inspected).
  Evidence: `.scratch/harness-evidence/pr743-dialog-skip-launch-proof/` (worktree
  `autonomous-deliver-703-e75b7b`). All three #738 acceptance criteria observed live.

## Review round 1 (SHA `976640c`) — 5 Codex P2 + 2 daemon MEDIUM, all addressed

Codex was slow (~9 min, past the first two cooldowns) but landed. Fixes on branch:
1. **Pass configured CM image** — watcher now built with `process_image=actuator.cm_exe.name`
   in rig_launch AND resilient_launch (a renamed `--cm-exe` was previously missed).
2. **Restrict clicks to the CSP-data dialog** — content/title **signature gate**
   (`DEFAULT_DIALOG_SIGNATURES`): a Skip-bearing CM window is a target only if its title OR a
   descendant Text control names the patch-data dialog. WPF exposes TextBlocks as UIA Text, so
   this is robust; the live title is the generic "Waiting…" so **content**, not title, is the
   durable identity. Skip-bearing windows failing the signature are left alone.
3. **Arm in the shared path** — `EntryLauncher.run()` now arms the watcher for CM actuators
   (covers the daemon `/session/start` + entry_launcher CLI), try/finally teardown.
4. **Opt-out through Game Point** — `AC_COPILOT_CM_DIALOG_SKIP` env kill-switch honored by all
   three paths (the frozen launcher can't pass new CLI args to its resilient child).
5. **Abort in-flight tick on stop** — `_tick` re-checks `_stop_event` after the (blocking) scan
   and before invoke; `stop()` keeps the live thread ref when the join times out (no orphan +
   coexisting second watcher).
- **Daemon (advisory, cursor-lens quota-skipped this round):** grok — `stop_csp_watcher()` before
  `os._exit(1)` on `_Car0ProbeCleanupError`; antigravity — `try/finally` for teardown instead of
  duplicated except blocks. Both done (finally + explicit pre-`os._exit` stop, since `os._exit`
  bypasses finally). 12 new tests; `make ci-fast` green.

## Pending re-verification

The signature gate (#2) must be confirmed against the REAL dialog's UIA text (title is
"Waiting…"; content must contain a signature). Added `--dump-tree` diagnostic for this; will
re-run a launch and, if the failing fetch reproduces, dump the dialog's text to confirm a
signature hit before final merge. If it does not reproduce this session, the WPF-exposure
reasoning + synthetic proof stand and the miss-logging makes any gap self-diagnosing.
