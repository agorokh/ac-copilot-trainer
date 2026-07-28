---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/703
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-pace-ladder-115-2026-07-26.md
  - AcCopilotTrainer/03_Investigations/issue-577-alien-selfplay-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #703 — the self-play ladder decoupled, and the review surface it opened (2026-07-28)

PR [#709](https://github.com/agorokh/ac-copilot-trainer/pull/709), branch
`fix/issue-703-decouple-refit-and-scale`. 16 commits, ~2100 insertions across
`auto_alien.py`, `plant_id.py` and their tests.

## The defect and the fix

`run_selfplay` bundled a **plant refit** (from the *previous* iteration's validated archives) and
an **envelope scale step** into one iteration. The oracle judged the iteration as a whole, so a
falsified *scale* rung reverted the refit too — even though the refit's evidence came from a drive
that passed and the failing drive contributed none of it. The top rung is by construction the one
most likely to falsify, so the ladder systematically destroyed its own best lever.

Iterations now **alternate**: a **plant** step refits and drives at the last *validated* scale; an
**envelope** step leaves the plant untouched and drives the next rung. Each moves exactly one knob,
so a falsification names which knob it falsified. Report gains `ladder_mode`, `step_kind`,
`falsified_component`, `refit_iterations`, `inherited_selfplay_merges`, `requires_rebase`.

## Why not "just keep the refit" (the issue's option 3)

`merge_selfplay_model` (`ggv_profile.py:708`) is **strictly monotone** — it only ever RAISES bins —
and its own contract names the keep-last-valid revert as *"the safety valve when a raised envelope
turns out wrong on track"*. Deleting the revert would leave the plant with **no downward path at
all**. That one line settles the option space: the revert must survive; what must change is what it
is attributed to.

## The finding that made it safe to ship

**The operator's proven G2 recipe was already a hand-run decoupled ladder.** #529 ladder 3 ran
`--ggv-scale 1.0 --scale-step 0.15 --max-scale 1.15 --iterations 2`; the rung caps at 1.15 on the
first step, so *both* iterations drove at 1.15 and iteration 2 was effectively refit-only. Capping
the rung so the top step can never falsify **is** how the operator kept the refit. Pinned by
`test_selfplay_reproduces_the_529_g2_recipe_unchanged`, which replays those exact flags and merge
stats and asserts an identical drive sequence.

## What the review actually cost — the durable lesson

Sixteen rounds. The decoupling itself was ~1 round of work; the other 15 were the **concurrency
surface that claiming single-knob attribution opens**. Once the report asserts "this verdict belongs
to this knob", every way a peer worktree can move the plant becomes a correctness bug. Reviewers
found, in order: the save-skip race, the `--stint` base scale, inherited-refit reporting, the
pre-drive peer window, the during-drive window, the plant-step window, the ladder-start snapshot
being unverified, the refit parse re-reading behind its own guard, and the scientist stage running
across two plants.

Three recurring shapes, all mine:

1. **Guards that only fire when both sides are present.** `current_fit is not None`,
   `driven_fit is not None`, `valid and ...` — each let a missing fact read as agreement. Fail
   closed on *missing* proof, not only on *contradicted* proof.
2. **Fixing the symptom and leaving the shape.** A second uncoordinated read that looks like a
   check; an anchor that looks like a base; a taint flag set on the pass path but not the fail path.
   Set a fact once, where it is known, so every branch inherits it.
3. **Tests that silently stop testing.** The harness emitted no `plant_provenance`, so a whole
   round's contract was verified by nothing; two peer-window tests keyed on a call *index* that a
   later read shifted. Both passed the whole time.

## Reviewer-process findings (worth keeping)

- **A fixed deadline is not proof of absence.** Codex landed 46 s and 73 s after two audit windows
  closed; I reported "no review" twice and was wrong both times. The self-hosted daemon (~500–700 s)
  landed after *every* fixed check — four reviews unread, and it had flagged the falsified-peer-race
  defect a full round before Codex did. Poll after the mandatory cooldown; never treat the boundary
  as a verdict.
- **Findings can live only in the review body.** One P1 appeared in a Codex review body and in no
  inline thread, so no `reviewThreads` query would ever have surfaced it.
- **On this Windows host** the canonical `resolve-pr` audit block cannot run verbatim: Git Bash
  rewrites `gh api "/repos/…"` into a filesystem path, and `jq` is absent. A Python equivalent with
  the same filters is in the session scratchpad.

## Owned in passing

`test_trailing_backslash_is_rejected` fed `Path("C:/repo\\")` to `validate_wrapper_path`; `Path`
normalization strips the separator on Windows, so the assertion was **vacuous on Linux CI and an
outright failure on the Windows rig**. `main` fixed it independently in #707/#708 with the same
split, the same `os.name` conditional and the same `endswith` precondition — the merge took main's
version and dropped the duplicate. Independent convergence on one root cause and one guard shape.

## Still open

- **AC 5 (live)** — a Magione ladder retaining a refit across a falsified top rung, with the next
  run's line build reporting the lower QSS floor. Rig is free; live baseline captured before the
  work started: the 911/Magione plant carries **7 self-play merges**, the last being ladder 3's
  retained `{adopted: 1, raised: 5}` (7 of 30 lateral bins measured).
- **Codex gate** — absent for 5 of the last 7 triggers (each waited 600 s plus 10–20 min of
  polling). Merge is deliberately blocked on it; CI green plus a clean advisory daemon is **not**
  the independent gate `resolve-pr` requires.
- **Watch item (n=1, not filed)** — at the 86.27 s floor a stint went 80.791 / 95.122 s, both
  `is_valid`, zero recoveries. `evaluate_selfplay_iteration` gates on validity and recoveries, not
  lap-time **variance**, so an envelope that has become unrepeatable still reads VALID. Related to
  but distinct from #703; reproduce before filing.

## Session note (memory gate)

The SessionStart Tier-3 prefetch reported the substrate unreachable and the gate soft-allowed
(`substrate_down`). The MCP bridge itself was healthy — a direct `query_knowledge_graph` against
`ac_copilot` returned grounded context — so the failure is in the prefetch's own loopback transport
on this Windows host, not the substrate. Grounding came from the real MCP query plus vault Tier-2.
