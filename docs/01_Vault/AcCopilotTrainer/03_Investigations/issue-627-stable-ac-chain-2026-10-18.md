---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-18
updated: 2026-10-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/issue-86-native-se-live-readback-2026-10-17.md
---

# Stable AC: why it never worked, and why it is now a service tool (2026-10-18)

Operator report: Stable AC relaunched AC forever ("race cancelled"). The resilient-launch log held
**0 `stable` verdicts ever** (37 froze, 7 never_live, 4 not_drivable, 1 wedged_init).

## The chain (each step verified on the real button, not a script)

| PR | Mechanism | Live result |
|---|---|---|
| #876 `8fade2c` | gave the post-Start Car0 *miss* a settle window | **Wrong branch.** Car0 *succeeds* right after Start; a #876 build still failed 12/12 and its new log line never fired |
| #877 `ae95ffd` | `classify` post-go-live stall rule now also needs `DEFAULT_STALL_SECONDS` = 20 s of pinned graphics | Start pins `acpmf_graphics.packetId` ~10 s (physics +333/s), then it resumes. 4 one-second samples called it a wedge. With the floor: `stable` on attempt 1. Schema → **v6**; v3/v4/v5 superseded |
| #879 `435c971` | Stable AC's drivability check no longer uses the CSP Car0 handshake | See below. Operator confirmed wheel/pedals work |
| #884 `465905b` | operator decision: Stable AC off the main Game Point screen | CLI only: `--resilient-launch` / `--resilient-release`. Play = Content Manager + START |

## The Car0 handshake takes the car from the driver (#879)

Creating `CustomAI.CarControls0` makes CSP open the section itself and log
`Car control provider is ready: 0`; the launcher closing *its* handle does not hand the car back.
Measured: after `_probe_car0_drivable()` returned, the section still existed, and `gas=1`
written to it from a fresh handle revved the car 900 → 9044 rpm. Zero-filled controls then
override the MOZA wheel for the rest of the session. A session with no handshake drove normally
with the operator at the wheel. Replacement: `session.start` with `probe_only` → trainer Lua
answers from `isInMainMenu` and returns before `ac.tryToStart`. **Never create `CarControls0` in a
session a person will drive** — fine for `auto_drive`, which is autonomous by design.

## Why Stable AC is not a play mode

It launches a fixed car/track from Game Point `settings.json` (`resilient_car`/`resilient_track`,
here Porsche @ Magione) and ignores Content Manager's selection. During its 140 s proving window a
driver quitting AC is indistinguishable from a crash, so it relaunches up to 12 times.

## Lessons

- Verify a fix on the deliverable's own button before writing the root cause anywhere. #876 passed
  tests and review and fixed nothing; the real-button run caught it within one attempt.
- A component docstring that says "control is returned to the driver" was never exercised by a
  human; Stable AC had never produced a session to drive in.
- Rig evidence: `.scratch/issue86-live/` (`stable-ac-trace*.jsonl`, `diag-*.log`,
  `car0_handover_test.py`).

## Open

- **Post-Start render pause** (graphics stop, physics runs; ~10 s then ~3.7 s measured) happens on
  any launch. Unproven whether our trainer app's session-start work causes it (precedent: #730).
  Next: A/B launch with the trainer app disabled, same trace.
- 13 local `make ci-fast` failures on this Windows rig are host environment (no C compiler for
  keypad firmware; live #854 inference config read by coach tests) and fail identically on `main`.
