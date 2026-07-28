---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/710
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-625-boot-scoped-redesign-2026-07-28.md
  - AcCopilotTrainer/03_Investigations/issue-630-parts-cde-2026-07-22.md
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #710 — a launch attempt now says whether it delivered an AC cycle

## The ambiguity that cost boots

`LaunchVerdict.NEVER_LIVE` covered two physically different outcomes, and
`resilient-launch-report/v1` stored only the verdict string:

| Shape | What happened | Cycle? |
|---|---|---|
| delivered | `acs.exe` appeared and exited during load, or rendered without ever reaching readiness | **yes** |
| undelivered | `_ensure_cm_running` returned false, or `actuator.launch()` raised — nothing was spawned | **no** |

The #625 freeze accumulator arms on launch **cycles**, so `init_perturber_ab.summarize_boot`
had to map a launch's ordinal position onto an accumulator position with no way to know which
attempts consumed one. PR #708 shipped the conservative answer: any boot whose onset was preceded
by *any* `never_live` was marked `onset_ambiguous` and dropped from the primary endpoint. Honest,
but each discarded boot costs a **physical reboot**.

## The load-bearing insight

Delivery is not a property of the verdict — it is a property of the **trace**: "was `acs.exe`
observed alive at least once". `_watch_live` already collects that trace, and the two undelivered
paths return *before* any process could exist. So the launcher always knows; only a caller that
returns a bare verdict does not.

That gives three states, not two: `True` / `False` / `None` (undetermined). `None` is what a bare
`LaunchVerdict` normalizes to — but **only** for `never_live`; every other verdict is reachable
only through a live `acs.exe`, so its delivery is derivable.

## What shipped (PR #717)

**Launcher — `resilient-launch-report/v1` → `/v2`**

- `AttemptOutcome(verdict, cycle_delivered)`; `watch_attempt` may return one instead of a bare verdict.
- Pure `cycle_delivered(samples) = any(sample.acs_alive)`. Never inferred from a verdict.
- `attempts_log[].cycle_delivered` + a top-level `cycles: {delivered, undelivered, undetermined}`.
  Kept **out** of `counts` on purpose — `counts` is the verdict histogram and consumers compare it
  for exact equality.
- A **delivered** `never_live` no longer advances the CM cold-restart streak. Same argument the code
  already made for `WEDGED_INIT` (CM delivered; restarting only adds kill-churn) — it only became
  expressible once delivery was recorded.
- A non-`never_live` verdict claimed as undelivered **raises** rather than publishing an internally
  inconsistent measurement artifact.

**Analysis — `init-perturber-ab-analysis/v2` → `/v3`**

- Onset is scored in **delivered cycles** (`onset_cycle`); the raw report row stays as `onset_index`.
- The censoring surrogate is `delivered_cycles + 1`, not `launches + 1` — an arm with more delivery
  failures no longer looks like it stayed clean for longer. `_onset_difference_bounds` now derives
  from `onset_value` instead of re-deriving the surrogate from the raw launch count.
- The post-onset burst window counts delivered cycles, so an undelivered attempt **extends** the
  window instead of voiding it (pre-#710 it voided the window rather than shrink the denominator).
- `onset_ambiguous` narrows to `cycle_delivered: null` — a state a rig run never emits. **That is the
  recovered statistical power.**
- `MAX_NEVER_LIVE_FRACTION` → `MAX_UNDELIVERED_FRACTION` (`undelivered_fraction_exceeded`), plus a
  new `no_delivered_cycles` reason. The exclusion is about *delivery* failures, not about the
  `never_live` verdict.
- v1 reports are rejected with an explicit reason; `_parse_report` validates presence, type,
  verdict-consistency, and the `cycles` block against the log.

`PLAN_SCHEMA` stays at `/v2`: the plan's policy text is documentation `load_plan` never reads, so a
plan generated before this change still loads and analyzes under the current rules.

## What the review caught (11 findings over two rounds, all acted on)

### The one that matters: a shared budget was silently load-bearing

Pre-#710 every boot in a plan shared the censoring surrogate `launches + 1`. That single fact was
providing **two** guarantees for free, neither of them written down anywhere:

1. **Doubly-censored blocks cancelled to zero.** Equal surrogates ⇒ difference `0` ⇒ excluded by
   `informative_blocks` and caught by the surrogate-tie guard.
2. **Singly-censored blocks had a guaranteed ordering.** A censored boot's surrogate strictly
   exceeded any onset *observable in the same plan* (observed onset ≤ `launches`), so the censored
   arm was provably the later one and the surrogate's sign was always right.

Making the surrogate **per-boot** (`delivered_cycles + 1`) deleted both — without touching a line
of the code that depended on them. Round 1 caught the first (six doubly-censored blocks split
`+1`/`-1` clear the informative-block floor and report `no_measurable_effect` with p=1 having
observed **no onset at all**). Round 2 caught the second, which is subtler: with a 24-launch
budget, `on` observed at cycle 24 against an `off` censored after 20 delivered cycles supplies
`21 - 24 = -3` while the true difference may be zero or positive — six such pairs manufacture a
significant p-value out of pure censoring artifact.

Both are now one rule: **a censoring surrogate enters the permutation statistic only when the
bounds establish its sign.** Both observed → usable; one censored → only if its one-sided bound
excludes zero; otherwise the block contributes `0.0` with its real bounds retained. The guard
that stops an all-uninformative run reading as a null result had to be rescoped too
(`surrogate_tied_blocks` → `censoring_uninformative_blocks`, keyed on the new
`onset_sign_established`) — the old "both bounds are `None`" test would have missed the
sign-ambiguous *singly*-censored case entirely.

> **Generalizable lesson.** When a value's invariant holds "by construction", changing what the
> value is *derived from* can delete the invariant with no diff at the site that relies on it, and
> no test failure. Ask what a shared constant was silently guaranteeing before making it vary.
> Here it took two review rounds to find both halves of the same root cause.

### A process poll is not the only evidence of a process

`_sample_now` reads state through a Car0 handshake that blocks for up to 5 s, so a session that
starts after one poll and exits inside that window moves the render packet while every
`acs_alive` reading is `False`. `cycle_delivered` therefore also accepts packet **movement** — the
same "only a live writer can move a packet id" insight `SectionOwnershipGate` is built on.

Round 2 sharpened this: it must be **any** movement, not an advance. The common shape is a
**regression** — the corpse-handover of #628, where the dead session's section stays mapped at a
high id for ~6 s and the new generation publishes from ~0 (`16983 → 121`). A corpse never changes
on its own, so a decrease proves a new writer exactly as an increase does. Requiring `>` would
have missed precisely the trace where the process also died before any liveness poll saw it.

### Scope creep with a regression, correctly rejected

I had also made a *delivered* `never_live` reset the Content Manager cold-restart streak, reasoning
by analogy with `WEDGED_INIT`. Codex pointed out that a delivered `never_live` also covers the
rendering-but-never-ready session — the stale cached-session / pre-drive-overlay failure of
#537/#558, whose **proven** recovery is exactly that restart. Delivery proves AC started; it does
**not** prove CM honored the requested preset. Reverted. The issue asked for recording, not a
behavior change.

### The pre-registration is code, not prose

I held `PLAN_SCHEMA` at v2 on the reasoning that the plan's policy text is documentation
`load_plan` never reads. Wrong: the plan's `endpoints` block **is** the pre-registration, so
analyzing a v2 plan under cycle-counted rules scores it against an endpoint it never registered.
Bumped to v3 with an explicit rejection for v2. The cost turned out to be nil — pre-#710 boot
reports are `resilient-launch-report/v1` and already rejected, so no v2 plan can have usable
reports to strand.

### The remainder

Reject any non-`True` delivery for a live verdict (not just `False`, or the producer can emit a
report its own analyzer rejects); check the eligibility floor against `delivered_cycles`, **scoped
to boots that actually reach the test** (block eligibility is paired, so an excluded boot's
shortfall must not force `insufficient_sample`); void a burst window containing an
unknown-delivery row rather than skipping over it; and drop the `classified == 0` usability guard,
since delivery now answers that question directly (a boot of 20 delivered `never_live` cycles is a
valid censored observation).

*(The paired-block scoping came from qodo, which is retired fleet-wide and therefore advisory —
but the finding was objectively correct and this PR is what made it reachable: before the floor
counted delivered cycles, a short boot required a hand-edited plan.)*

## What this does NOT change

The #703/#716 blocker is untouched: live 3/3 verification is still blocked at the CSP hijack, so the
#625 experiment has not been run. This change makes the experiment cheaper in reboots when it *is*
run; it does not unblock running it.

## Verification

Off-rig only, by construction — the verdict/delivery logic is pure and unit-tested with no Assetto
Corsa present (the same design constraint `classify` has carried since #624). `make ci-fast` green
on both rounds. New tests cover both `never_live` shapes on both sides of the schema boundary, the
delivered-cycle onset shift, the extended burst window, the v1/missing/inconsistent report
rejections, and each Codex finding — including two deliberately non-vacuous regression tests
(without their fixes the doubly-censored blocks yield alternating ±1 differences, and the
cycle-short boot reports a passing 20 raw launches).

**This change is not rig-verified and cannot be**: #703/#716 still blocks live 3/3 verification at
the CSP hijack, and the delivery flag only becomes observable in a real report when the #625
experiment runs. The evidence here is the pure-function test suite, which is the same standard the
rest of `classify` is held to.
