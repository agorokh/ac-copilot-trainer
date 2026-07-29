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

## START HERE — run the SCREEN first (#724), not the 16-boot design

**Do not open with the confirmatory run.** #625 sat unrun for over a week because the cheapest
question this tool could ask cost **16 physical reboots**: `MIN_BOOTS_PER_ARM = 6` makes it return
`insufficient_sample` below 12 boots. Four sessions found real instrument defects
(#657 → #708 → #710 → #719) and fixed every one; none of them moved that price, because the price
was never a defect — it was the design being **confirmatory-only for a screening question**.

The power target was also wrong for the decision. The 16-boot design separates onset ~14 from ~8, a
*modest* shift. But #627's resilient launcher already retries past the freeze, so
"disable the overlays permanently" is only worth adopting if it roughly **eliminates** the freeze.
That is a large effect, and a large effect is visible in ~4 boots.

```bash
python -m tools.ac_harness.init_perturber_ab plan --screen --out .scratch/<name>.json
# ... run the 4 printed boots (one reboot each) ...
python -m tools.ac_harness.init_perturber_ab screen --plan .scratch/<name>.json --reports-dir .scratch
```

| screen verdict | what to do |
|---|---|
| `no_large_effect` | **Close #625.** The overlays are not a mitigation worth adopting over the existing retry. A **modest** effect is *not* ruled out — the screen cannot see one, by design. |
| `large_effect_plausible` | Now spend the confirmatory 16 boots (`plan` without `--screen`). |
| `ambiguous` / `insufficient_usable_boots` | Operator decides. |

The screen **never computes a p-value** — at 2 blocks the permutation floor is `2/2**2 = 0.5`, so
any number would be false precision. `analyze` and `screen` refuse each other's plan artifacts, in
both directions, so neither can be scored by the wrong rule.

Everything below describes the **confirmatory** stage, which is now stage 2.

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

~~`never_live` covers both "acs.exe appeared then exited" (a cycle happened) and "nothing was ever
spawned"~~ — **RESOLVED 2026-07-28 by [#710](https://github.com/agorokh/ac-copilot-trainer/issues/710)
(PR #717 merged `d78c10b`).** Every attempt now records `cycle_delivered`; onset is counted in
delivered cycles, so a boot containing a merely undelivered attempt scores instead of being dropped.
`onset_ambiguous` narrows to genuinely unknown delivery.

## Treatment receipt is verified (#719) — plan/report/analysis **v4**

**Read this before spending the 16 reboots.** PR #721 lands treatment-**receipt** verification:

- **Report schema** `resilient-launch-report/v3` records per-attempt + boot roll-up `perturbers`
  (`injected` / `not_observed` / `unavailable`). v2 reports are refused.
- **Plan/analysis schema** `init-perturber-ab-plan/v4` + `…-analysis/v4` pre-register the receipt
  policy. v3 plans are refused — regenerate with `python -m tools.ac_harness.init_perturber_ab plan`.
- Plan commands emit `--expect-perturbers on|off`. Off-arm positive sighting (or on-arm STABLE miss)
  stops the trial loop early with a **unique** salvage path
  `{stem}.arm_contradicted.{UTC}Z{suffix}` so the planned exclusive JSON stays free for re-run after
  settings fix + reboot. Exit is nonzero — scripted boot chains must treat that as stop-and-fix.
- Analyzer **excludes** contradicted boots (and drops their block); never re-labels. Unverified
  receipt withholds causal conclusions (`treatment_receipt_unverified`) without inventing exclusions.
- `go_live_timeout` must be ≥ 5 s (injection race ~3 s). Absence is dispositive only on delivered
  **`stable`** (full stability window past the race). `froze` misses stay non-dispositive.
  Module sampling requires **64-bit Python** on the rig; mid-attempt PID replacement freezes
  presence and invalidates absence if injection was seen. Analyzer resolves
  `{stem}.arm_contradicted.*` salvage when the planned report is absent.

Design detail: [[issue-719-treatment-receipt-2026-07-28]].

## Verified rig facts (AG_PC, 2026-07-28) — do not re-derive

- **Fast Startup is DISABLED** (`HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power`
  → `HiberbootEnabled = 0`). A shutdown/power-on here is a true cold boot, so step 3's boot-epoch
  check is sound on this host. This was worth checking: a hybrid boot would **not** reset the
  launch-cycle accumulator while potentially still passing the epoch check — silently pooling two
  arms, the exact failure the boot-scoped design exists to prevent.
- Both perturbers are installed and **do** inject into a live `acs.exe`:
  `c:/program files (x86)/steam/GameOverlayRenderer64.dll` and
  `C:\Windows\System32\nvspcap64.dll`.
- The injection **races process startup** — measured on one `acs.exe` (pid 27616): at 45 modules
  loaded neither DLL was present; ~3 s later at 115 modules both were. So a perturber check must
  sample late (or union across samples); **presence is dispositive, absence is not**.
- The perturbers inject into **games, not globally** — neither appears in `steam.exe`. There is
  therefore **no pre-flight** that can read the treatment state without starting `acs.exe`.

## Status

Tooling merged (PR #708, plus #710/PR #717). **The physical A/B has still never run** — it remains
gated on operator sign-off for the two settings and on rig availability. #719 should land first so
the 16-reboot investment is spent on verifiable arm labels.
