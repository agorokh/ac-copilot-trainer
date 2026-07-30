---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-30
updated: 2026-07-30
topic: "#627: the post-lap video freeze is the SAME accRenderingAdv loop as the init wedge"
source_type: repo
related_issues: [627, 466]
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-627-strtod-unbounded-loop-2026-07-29.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627: the post-lap freeze and the init wedge are one bug — and it reproduces on demand

## The capture

The operator's **long-standing** complaint — *"after completing any lap the video freezes 5–10 s
but the game continues"* — was assumed separate from #627. It is not.

Reproduced on demand (it fires after every completed lap), then `freeze_forensics` attached while
it was happening:

```
verdict: long_computation
rips_rebased:
  DWrite+0x14e7169     <-- one of the THREE original #627 wedge RIP samples
  DWrite+0x14e7162     <-- same loop, second imul block
  DWrite+0x14ffcc1
phys_readings: 36307 -> ... -> 42737   (physics advancing throughout)
```

`DWrite` is the game-folder alias for `accRenderingAdv.dll`. `0x14E7169` is the exact address in
this issue's existing live-RIP evidence; `0x14E7162` is in the same block. Both sit inside the
÷100 normalization loop `0x14E70E0 … 0x14E71C5` disassembled in
[issue-627-strtod-unbounded-loop](issue-627-strtod-unbounded-loop-2026-07-29.md).

## Why one loop produces two symptoms

The disassembly predicted this. `r11d` (the loop's only progress variable) is incremented
**conditionally on data**, there is no iteration cap, and every pass walks up to 512 limbs with two
`imul 0x147B` each:

| regime | behaviour | symptom |
|---|---|---|
| `r11d` never advances | non-terminating fixed point | **init wedge** — graphics pinned forever |
| `r11d` advances slowly | very long but finite | **post-lap freeze** — 5–20 s, then recovers |

`long_computation` is the correct verdict for the second: RIP wanders across 45 MB (walking code,
not a tight loop). Both regimes hold the render thread while physics advances — which is exactly
what both symptoms look like from outside.

## Why this is the better instrument

Three weeks went into chasing a stochastic ~coin-flip needing boot-scoped arms and 16-reboot
experiments. **This fires after every lap.** It is a far better vehicle for studying the loop and a
far better artifact for the upstream report than "sometimes, at init".

## Next lead — hypothesis, not established

Lap completion serialises a lap archive (`[COPILOT][ARCHIVE] queued async write samples=2000`).
Two thousand samples of float fields means a very large number of decimal↔binary conversions in a
short window; if each takes the slow path in this loop the cost lands exactly where the freeze is.

**Confidence:** the module and the loop are **established from the capture**. That *our* archive
encoding feeds it is **plausible and untested** — but cheap to test, because the repro is on demand.

## Autonomous drive restored the same session

`main` @ `c11f353`, `REPLACE_MAIN_MENU=0`, shipped `auto_drive`:

```
session.start: ok=True started=True already_started=False
hijack landed (Car0) on probe 1/3
PASS — drove=True laps=1 max_speed=210.7km/h top_gear=6 dist=2766m recoveries=0
```

The mechanism is the merged authenticated `session.start` relay. An in-sim auto-press (PR #727) was
live-verified to work but **violated SC-03** ("human app loads never auto-press Start") and was
closed; the relay lands the hijack on probe 1/3 versus the auto-press's 3/3.

The pit-start stall is **intermittent, not deterministic**: one run capped at
`recovery cap (6) exceeded at 488m`, the next two drove 650 m and 2766 m with `recoveries=0`. When
it does fire, all recoveries log `teleport_to_pits` and never `line_teleport`, i.e.
`_teleport_onto_line`'s 25 m read-back fails — its custom-teleport offsets are doc-extracted and
flagged `VERIFY LIVE` in `custom_ai.py`. Unverified whether the offsets are wrong or the car is
simply pinned; the trace shows it stationary at ~8600 rpm in gear 2, i.e. blocked, not idle.

## Corrections to the record

- **`main` was RED on Windows.** Six `tests/test_rig_launcher.py` tests read the developer's live
  `gui.ini` via `_discover_ac_user_dir()`, so their result depended on the operator's own
  `REPLACE_MAIN_MENU`. Linux CI could never catch it — the probe short-circuits off-Windows. Fixed
  in PR #728 by isolating `Path.home()` (the environment), not the discovery function.
- **Operator-facing regression (mine, undone).** `REPLACE_MAIN_MENU=0` was set before the fix was
  merged, so the rig lost the New UI menu and gained nothing for a day. Merging a PR does not
  deploy to the rig: the junction serves the **primary checkout**, which must be pulled.

## Open

- `menu_config_required` hard-blocks Stable AC unless `REPLACE_MAIN_MENU=0`, forcing a choice
  between the New UI menu and a working harness. The fact is correct (0/12 presses with the New UI;
  success on attempt 2 without); the ergonomics are a design question.
- Lap archives: **419 files / 455 MB**, unbounded, in a OneDrive-synced folder. No retention policy.
