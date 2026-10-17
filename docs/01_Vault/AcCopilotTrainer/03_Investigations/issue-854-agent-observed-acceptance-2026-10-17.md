---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-17
updated: 2026-10-17
issue: https://github.com/agorokh/ac-copilot-trainer/issues/854
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-854-remote-inference-2026-10-17.md
  - AcCopilotTrainer/pitfalls/assisted-drive-archive-rotation.md
---

# #854 — agent-observed coaching acceptance and the efficacy fixes it drove

Operator direction (2026-10-17): acceptance is seen and judged by agents, not a human
driver ("humans should not be a monkey in the middle").

## Method (reusable)

- `auto_drive --hud-every 3` (PR #871, `e4750db`): timestamped full-screen frames for the
  whole run under `<evidence>/hud-frames/`, captured by a child `hud_capture` process in the
  console session (the per-pixel conversion would otherwise hold the GIL and jitter the
  driver); bounded, failure-tolerant, `stop()` terminates an in-flight child. The remote
  launcher's payload allowlist excludes `hud_capture`, so capture lives inside `auto_drive`.
- Rig scratch kit `.scratch/inference854/`: `ab_run.py observe` (persistent operator env,
  archive guard, PresentMon, preservation checks), `tapped_sidecar.py` (read-only tap on
  every model call / queue submit), `score_observe.py` (coverage, delta-band correctness,
  arrival vs time-to-corner, narration grounding), `contact_sheet.py` (COACHING-tile crop of
  every frame, decoded from hud_capture's own filter-0 PNGs — no imaging library needed).

## What the first observed drive showed (remote qwen3.5-4b)

In-race model hints: 143 calls, 41% missed the 2 s deadline under load, 82/84 delivered were
"ACCELERATE, BUILD SPEED" (only restating the rules band), 12% arrived after the corner,
visible in 11/103 frames. Post-lap narration: 1/3 laps (corner priority starved it), and that
one claimed "consistent under-steer" — not in its facts. After every lap the tile showed
~25 s of `Sidecar v1: ack lap N`: `protocol.py` sent it as a hint, and any non-empty `hints`
replaces the trainer's own rules lines (`ac_copilot_trainer.lua` `#sidecarHints > 0`).

## Fixes (operator-approved) and re-verification

- PR #872 (`d1c8982`): empty `hints`; in-race model hints opt-in
  (`AC_COPILOT_INFERENCE_CORNER_HINTS`), skipped before the queue; priorities narration 3 >
  between-lap 2 > corner 1; deterministic narration grounding (diagnosis terms, corners,
  numbers must be in the facts).
- PR #873 (`7874f01`): ≤2-sentence HUD-sized prompt; capped reply without a complete
  sentence dropped; positional corner claims grounded.

| | before | #872 | #873 |
|---|---|---|---|
| in-race model calls | 143 | 0 | 0 |
| narration delivered / grounded | 1/3 (ungrounded) | 3/3 (1 cut, 1 positional slip) | 3/3 clean |
| narration latency | 6.4 s | 2.5–4.7 s | 1.2–2.6 s |
| ACK stub on tile | ~25 s/lap | none | none |
| fps / displayed p99 | 69.77 / 15.46 | 69.72 / 15.49 | 69.49 / 15.53 |

Driver now sees the specific rules line ("T5: MIN SPEED 55 VS REF 66 KM/H — CARRY MORE
MID-CORNER") then a grounded summary ("Carry more mid-corner at T1, T5, and T6 to increase
minimum speeds."). Archives identical after every run.

## Limits

Narration adds a modest multi-corner summary, not new insight. Between-lap model focus not
selected by Coach v2's gate on this reference (`track.map … 0 corners`). Lap 1 shows the
"DRIVE A LAP" placeholder until a reference exists. HA-voice contention untested; NVIDIA
0x133 not reproduced (~10 drives), cause unresolved. GPU health logging re-enabled at the
operator's request (a `STOP-MONITOR` flag "at operator request" had stopped it at 03:23 UTC;
kept as `STOP-MONITOR.reenabled-20261017-operator-request.txt`).
