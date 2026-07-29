---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-29
issue: https://github.com/agorokh/ac-copilot-trainer/issues/719
pr: https://github.com/agorokh/ac-copilot-trainer/pull/721
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-625-boot-scoped-redesign-2026-07-28.md
  - AcCopilotTrainer/03_Investigations/issue-710-cycle-delivered-2026-07-28.md
  - AcCopilotTrainer/00_System/handoffs/2026-07-29-grok-pr721.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #719 — the #625 A/B never verifies that the treatment was received

**Shipped 2026-07-29** via PR [#721](https://github.com/agorokh/ac-copilot-trainer/pull/721)
(`de5bd6b`). Issue CLOSED. See
[2026-07-29-grok-pr721](../00_System/handoffs/2026-07-29-grok-pr721.md).

## The gap, stated precisely

The boot-scoped A/B measures everything about each boot **except the treatment**. A boot's arm
label comes only from the plan file — the operator's assertion that they toggled the Steam overlay
and NVIDIA ShadowPlay before *that* reboot. Nothing observes whether the perturbers were actually
injected into `acs.exe`.

Every other input is measured and defended: `load_plan` refuses withdrawn schemas,
`load_observations` verifies each boot boundary via the implied boot epoch
(`started_at_utc - uptime_h`), `_parse_report` validates per-attempt `cycle_delivered` (#710),
`summarize_boot` right-censors onsets and refuses to score blocks whose difference sign is not
established. Treatment assignment is the last honor-system link — and it is the one input the
p-value is *about*.

**Reframe that makes the fix precise:** this is **treatment-receipt verification**, not
operator-error detection. Whether the operator forgot the toggle or Steam simply failed to inject
while enabled, the boot did not receive its assigned condition and cannot inform the contrast. The
cause is irrelevant; receipt is what the design needs. That framing also settles the awkward
`overlays_on` case — a boot planned ON whose overlay never injected is excluded for the same reason
as one planned OFF that did.

## Measured on the rig — the injection races process startup

AG_PC, 2026-07-28, `uptime_h = 72.3`. Toolhelp32 module snapshot
(`TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32`, `Module32FirstW`/`Module32NextW`) against one live
`acs.exe` (pid 27616):

| snapshot | modules loaded | `gameoverlayrenderer64.dll` | `nvspcap64.dll` |
|---|---|---|---|
| early | 45 | absent | absent |
| ~3 s later | 115 | **PRESENT** | **PRESENT** |

Two things follow, both measured rather than argued:

1. Both perturbers **do** inject into `acs.exe` on this rig and are directly observable — so the
   check is buildable at all.
2. **Presence is dispositive; absence is not.** A snapshot taken early reports "absent" for a
   perturber that is active. This is the exact mirror of what #710 already learned about delivery
   (*"a watched trace can prove delivery but never disprove it"*) and must be encoded the same way:
   a tri-state where only the positive observation establishes anything.

The probed process scored `froze`, so the evidence is available on precisely the attempts the onset
endpoint is built from. Same run: `resilient-launch-report/v2`, 4/4 `froze`, `cycles.delivered = 4`.

## Design decision — never re-label a contradicted boot

A contradicted boot's **block is excluded**; the boot is *not* re-labelled to its observed arm.

Re-labelling is tempting because blocks are scarce (ties already eat them; the floor is 6
informative blocks and the smallest attainable two-sided p is `2/2**6 = 0.03125`). It is still
wrong: the permutation null is over the `2**blocks` arm orders the randomization could actually
have emitted — the labels *are* the randomization. Re-labelling conditions on data observed after
randomization, so the reference set no longer corresponds to the labels being tested. It is an
as-treated mixture with no design-based justification. It can also produce a block whose two boots
share an arm, which carries no contrast and drops anyway.

Recorded because it will be re-proposed: the 2026-07-28 council split on exactly this — `gemini-sub`
argued for re-labelling on physical-reality grounds; `kimi-sub` and this analysis reject it as
label-dependent selection.

## Verified rig facts — do not re-derive

- **Fast Startup is disabled** (`HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power`
  → `HiberbootEnabled = 0`). A shutdown/power-on on this host is therefore a true cold boot, and
  `load_observations`' boot-epoch check is sound here. This mattered: a hybrid boot would not reset
  the launch-cycle accumulator while potentially still passing the epoch check, silently pooling two
  arms.
- Steam is at `c:/program files (x86)/steam`; `GameOverlayRenderer64.dll` present.
  `C:\Windows\System32\nvspcap64.dll` present.
- The perturbers inject into **games, not globally** — neither module appears in `steam.exe` or an
  arbitrary process. So there is **no pre-flight** that can read the treatment state without
  starting `acs.exe`; the bounded substitute is failing fast on the first delivered cycle.
- The rig froze **4/4** launches at 72 h uptime — the accumulator is fully armed on a long-lived
  boot, consistent with the #627/#668 model.

## Status

Issue [#719](https://github.com/agorokh/ac-copilot-trainer/issues/719) filed with the full spec
(Parts A/B/C). **Implementation blocked this session** — see
[[tier3-substrate-unreachable-rig-2026-07-28]]. #625 itself remains blocked on the operator gate
(sign-off for the two settings plus 16 reboots); #719 is what makes that 16-reboot investment
trustworthy before it is spent.
