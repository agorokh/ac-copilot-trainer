---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-30
updated: 2026-07-30
topic: "#627: the load/post-lap stall was OUR whole-journal scan feeding CSP's slow number parser"
source_type: repo
related_issues: [627]
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-627-postlap-freeze-same-loop-2026-07-30.md
  - AcCopilotTrainer/03_Investigations/issue-627-strtod-unbounded-loop-2026-07-29.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627: the multi-second stall was ours — a whole-journal scan whose result was discarded

FIXED by PR #730 (`d5585b8`). This is the operator's long-standing *"loading is delayed 5-15 s"*
and *"after every lap the video freezes 5-10 s while the game keeps running"*.

## The bug

`refreshActiveReference` passed the scan **inline as an argument**:

```lua
persistence.chooseImportedReference(
    state.bestLapMs,
    persistence.bestImportedReference(car, sim),   -- eagerly evaluated
    config.useImportedReference == true)
```

Lua evaluates arguments eagerly, so the scan ran unconditionally — while
`chooseImportedReference`'s FIRST line is `if enabled ~= true ... then return nil end`, and
`useImportedReference` defaults to **false**. The result was discarded unread.

## What it cost (measured, rig, 2026-07-30)

`bestImportedReference` runs `io.scanDir(dir, "lap_*.json")` then **fully parses every hit**:

| | |
|---|---|
| archives | **401** |
| total | **480.5 MB** (~250 KB each, 2000 float samples/lap) |
| `source == "imported"` | **0** |
| parse cost | **9.8 s in Python with C-speed JSON** |

**Unbounded** — every lap ever driven makes it slower, which is why it read as a slowly-worsening
"long time problem" rather than a regression.

## Why it hit CSP's parser

`freeze_forensics` caught the stall live; RIPs at `DWrite+0x14e7169` / `+0x14e7162` — inside the
divide-by-100 loop in `accRenderingAdv.dll` that #627 identified as a **decimal→float parser**. Each
archive's floats are parsed through the same slow path as the #627 wedge. **The scan is what fed
it.** Two symptoms, one loop.

## Before / after — same car, same track, lap completed both times

Largest gap between consecutive app log lines (the app logs unconditionally every ~3 s, so a gap
is a main-thread stall):

| | largest gap |
|---|---|
| before | **21,945 ms (21.9 s)** |
| after (deployed `main` @ `d5585b8`) | **3,017 ms (3.0 s)** |

Every remaining gap is ~3.01 s — the app's own `RT-DIAG` cadence, i.e. **no stall left**. Drive
unchanged: `PASS, laps=1, 210.7 km/h, 2767 m, recoveries=0`, `installed app provenance: match`.

## Guard

**SC-04** in `tests/test_design_conformance.py`, mutation-checked: reverting to the eager form
fails the test.

## Not fixed

The scan itself is still O(journal) for anyone who **enables** imported references. The
discriminating `"source"` key sits at byte ~255,834 of ~256,241 — the very end of each file — so a
cheap header prefilter is impossible; a tail read or a small index is the follow-up. Separately,
the journal is **401 files / 480 MB** with no retention policy.
