---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/577
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/issue-572-alien-pipeline-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/frontier-controller-ggv-2026-06-19.md
---

# #577 — flying-lap windows + progressive-envelope self-play (EPIC #529 P3)

**PR [#579](https://github.com/agorokh/ac-copilot-trainer/pull/579) review-converged at
`6907e42`, MERGE-PENDING (operator click)** — the session permission rail refuses an agent
merging its own PR without in-session named authorization. Everything else is done: CI green,
0 unresolved threads, resolve-gate ledger clean, self-hosted reviewer no-HIGH, cooldowns
completed, live-verified pre-merge. After merge: `/post-merge 579`.

## Shipped contract

- **Flying-lap windows** — `auto_drive --laps N` holds the `--wait-lap` tap open until N TIMED
  laps (`payload.last_lap_ms > 0`; untimed out-lap/teleport boundaries never count — including
  N=1) or the `--drive-seconds` budget. Per-lap times in the report (`lap_times_ms` +
  `laps_requested`); zero timed laps with a requested window FAILS the run; batch archive
  polling waits on a combo-matched, validity-AGNOSTIC count (`min_matching_count`) — an
  AC-invalid archive is falsification evidence, a foreign combo's archive is not.
- **Progressive-envelope self-play** — `auto_alien --iterations K --laps N`: per iteration,
  refit the friction envelope from ONLY the previous valid drive's archives
  (`selfplay_refine_result`), merge **strictly monotonically** (`merge_selfplay_model`: a
  lateral bin moves only when its measured posterior RAISES `safe_g`; brake/drive bins are
  preserved verbatim — no probes exist in a non-handshake drive; `mu_lat_g` never drops),
  persist through `save_plant_artifact` (fit provenance hash → cached alien line invalidates →
  next drive rebuilds line+QSS), step the ggv-scale ladder (default +0.05, `--max-scale` ≤ 1.2
  hard cap via the drive stage's explicit `--alien-allow-overspeed`; base `--ggv-scale` stays
  ≤ 1 — the #572 one-shot gate), drive again.
- **Keep-last-valid falsification oracle** (`evaluate_selfplay_iteration`, the #244 pattern):
  failed stage / any recovery / no timed lap / missing-or-malformed archive / AC-invalid lap →
  plant reverts to the last-valid bytes (peer-modification + fork-path guarded, OSError-safe)
  and the ladder stops with the named reason; an envelope that cannot change (scale capped AND
  no-op refit) refuses the identical retry. Base-drive evidence seeds refinement only after
  passing the SAME oracle.

## Live proof (rig, 2026-07-14, head `af90f0b` at run time)

`auto_alien --car ks_porsche_911_gt3_r_2016 --track magione --laps 3 --iterations 3` — one
unmodified command, hands-off: ladder `completed`, every stage PASS, every iteration VALID
(all counted laps AC-valid, zero recoveries). **Measured flying-lap trajectory strictly
monotonic: 107.009 → 101.642 → 96.624 → 92.567 s** (scale 0.9 → 0.95 → 1.0 → 1.05; bins:
+1 adopted at iter 2, +1 raised at iter 3). The 91.94 s *predicted* QSS floor is now beaten by
a *measured* lap. Honest gap: 92.567 vs the 82.7 s TT floor (~11.9%); ladder ended on budget
with headroom (`--max-scale 1.1`). Evidence:
`.scratch/harness-evidence/alien-577-selfplay-911-magione/` +
[#577 evidence comment](https://github.com/agorokh/ac-copilot-trainer/issues/577#issuecomment-4972586933).
The persisted plant carries the 3-entry `provenance.selfplay_merges` history (merged model
demonstrably persisted — used to refute a daemon false-positive HIGH with on-disk evidence).

## Review (6 fix rounds, ~15 findings fixed, 3 reply-invalid/WONTFIX with rationale)

Real catches worth remembering: `--laps 1` legacy-boundary contract drift (daemon HIGH);
validity-gated batch poll would stall on every falsified batch (Qodo); measured-but-lower
lateral evidence must never regress the envelope (caught by my own first test draft — the
merge is now strictly monotone); base evidence needs the oracle before seeding refits (Codex);
no-op refits must not count as envelope changes (Codex); peer-safe + fork-path-safe persist;
fail-closed on archives without a validity verdict. Gemini quota-dead all session (24 h limit);
slash-command triggers from Git-Bash get MSYS-mangled (`/gemini` → `C:/Program Files/Git/gemini`)
— send bot triggers via PowerShell.

## Durable lessons

- **Envelope evidence is a lower bound, not an estimate**: a lap driven at 0.81× the planned
  envelope "measures" less grip than even the prior's LCB grants — self-play merges must be
  monotone-on-safe_g, with falsification (not statistics) as the down-corrector.
- **The scale ladder is not optional**: at fixed scale the loop fixes immediately (evidence
  tops out below the 0.9 g observability gate); supra-LCB probing is what generates the
  evidence that raises the bins.
- **This Windows checkout drifts to CRLF** while the index stays LF — `ruff format --check`
  then wants to rewrite hundreds of files. Fix: delete + `git checkout --` the `w/crlf` files
  (`git ls-files --eol`); `git checkout-index -f` does NOT renormalize in place.

## Remaining

- **Operator: merge PR #579** (one click; everything staged), then `/post-merge 579`.
- **#577 open scope after merge**: L3 corridor-constrained per-corner refinement (issue "What"
  item 3 — trail-brake shape + curb usage inside QSS entry/exit corridors under a slip-angle
  stability margin; no AC attached). The floor attack continues cheaply: more iterations
  (`--iterations 6 --max-scale 1.15`) on the merged main.
- Rig invariant unchanged: AC app junction → primary checkout at merged main tip (#575 open).
