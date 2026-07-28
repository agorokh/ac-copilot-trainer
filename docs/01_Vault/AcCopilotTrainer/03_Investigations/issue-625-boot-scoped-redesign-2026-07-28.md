---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/625
supersedes: AcCopilotTrainer/03_Investigations/issue-625-init-perturber-ab-prepared-2026-07-22.md
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-625-init-perturber-ab-prepared-2026-07-22.md
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #625 init-perturber A/B — boot-scoped runbook (live protocol)

**This page replaces the v1 runbook.** The old one is archived at
[[issue-625-init-perturber-ab-prepared-2026-07-22]] and its protocol **must not be run**.

## Why the v1 protocol was withdrawn

v1 interleaved single launches inside **one** boot and compared a pooled per-launch freeze rate —
i.e. it assumed the #619 freeze is an i.i.d. coin flip per launch. #627/#668 refuted that: it is a
**per-boot launch-cycle accumulator**. Launches arm it over roughly 8–14 cycles (hard kills only
accelerate onset ~2×), and the post-onset burst is teardown-independent (~44%) and decays on its own.

So the first ~8–14 launches of any boot are near-deterministically clean in **both** arms. Running
v1 would have returned "no measurable effect" as a near-certain false negative and ruled the
overlays out permanently. Demonstrated on simulated data with a large real effect (onset ~8 vs ~14):

| endpoint | result |
|---|---|
| boot-scoped onset (v2) | `p = 0.03125` → `overlays_off_delays_onset` |
| pooled per-launch rate (v1) | `p = 0.687` → `no_measurable_effect` |

## The live protocol

Tooling: `tools/ac_harness/init_perturber_ab.py` (PR [#708](https://github.com/agorokh/ac-copilot-trainer/pull/708)).
It refuses to load a v1 plan, so a stale plan file on disk cannot be analyzed by mistake.

1. **Operator gate (unchanged).** Disabling the Steam overlay and NVIDIA ShadowPlay are
   operator-owned settings changes: explicit sign-off before toggling, restore both afterward.
2. `python -m tools.ac_harness.init_perturber_ab plan --out .scratch/<name>.json` — prints one
   command per planned boot. Defaults: **8 boots per arm = 16 boots**, 24 launches each.
3. For **each** planned boot in order: apply that boot's two settings → **REBOOT** → run that
   boot's single printed command. **One reboot per boot** — never two arms on one boot, or the
   accumulator is pooled and the onset endpoint is void. The analysis enforces this by comparing
   the implied boot epoch (`started_at_utc - uptime_h`) across the boundary.
4. **If a boot's command aborts** before writing its JSON, its launch cycles already advanced the
   accumulator and no artifact records it. **Reboot again** before re-running that boot.
5. Restore both settings, then
   `python -m tools.ac_harness.init_perturber_ab analyze --plan … --reports-dir …`.
6. Attach the rendered table plus the primary p-value to #625.

## What the analysis will and will not claim

- **Primary:** onset launch-index, via an exact **block permutation** test over the `2**blocks`
  arm orders the randomization could actually have produced. Design-based — assumes nothing about
  the boots beyond the randomization performed.
- **Power floor is real, not advisory.** The smallest attainable two-sided p is
  `2/2**informative_blocks`: 0.0625 at 5, **0.03125 at 6**. Below 6 the tool returns
  `insufficient_sample` no matter how cleanly the arms separate.
- **Ties cost blocks.** Only a block whose two arms *differ* carries information — flipping a
  tied block's labels leaves the statistic unchanged. Onsets are small integers, so ties are
  expected, and each one effectively removes a block. A run scheduled at exactly 6/arm reports
  `insufficient_sample` the moment one block ties; the default is **8/arm (16 boots)** to carry
  two ties of headroom. This is the single most likely way to waste the run.
- **Secondary:** post-onset burst rate over a fixed 6-launch window from onset, one rate per boot.
- It will report `insufficient_sample` if usable blocks fall below the floor (unusable or
  ambiguous-onset boots drop their whole block), and
  `effect_direction_indeterminate_under_censoring` when censoring leaves the sign of the true
  effect open. Both are honest outcomes, not failures.

## Known limitation carried forward

`never_live` covers both "acs.exe appeared then exited" (a cycle happened) and "nothing was ever
spawned", and the report schema cannot distinguish them — so a boot whose onset is preceded by any
`never_live` is excluded from the primary endpoint rather than scored on an assumption. Recovering
those boots needs the launcher to record delivery:
[#710](https://github.com/agorokh/ac-copilot-trainer/issues/710).

## Status

Tooling merged/in review on PR #708. **The physical A/B has still never run** — it remains gated on
operator sign-off for the two settings and on rig availability.
