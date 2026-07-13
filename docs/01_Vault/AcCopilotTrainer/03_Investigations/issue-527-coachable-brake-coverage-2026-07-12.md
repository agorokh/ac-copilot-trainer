---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-12
updated: 2026-07-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/527
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-522-parts12-coverage-calibration-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/issue-522-actionable-coaching-2026-07-12.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #527 — semantic_timeliness brake coverage: exclude uncoachable onsets

Split from #522 (parts 1-2 merged in #525, `56048ae`).

## Root cause

`semantic_timeliness.analyze()` computed the `brake_events_coached` gate as
`coached_onsets / ALL_gate-grade_brake_onsets`. The denominator included onsets that
**cannot** be coached because no reference brake mark sits near them:

- a mid-straight **correction dab** (issue's measured case: spline 0.729, nearest mark
  d=0.043 ≈ 105 m away on the 2455.7 m track), and
- **repeat dabs inside one already-cued zone** (T4: 4 onsets at 0.634/0.640/0.647/0.672).

So a scrappy autonomous-driver lap read the gate **red (7/9 = 77.8%)** while *every reference
zone crossed drew an ACTIONABLE cue* (7/7 dispatches ACTIONABLE, junk 0). The metric was
driver-scrappiness-sensitive around the 0.8 threshold — noisy about the very thing it means
to measure.

## Fix (`tools/ai_sidecar/voice/semantic_timeliness.py`)

**Occurrence-based** coverage (each `late_brake` advisory, urgency prepare/act, is one distinct
brake-mark *pass* — its identity is the advisory index; `t` separates passes/sub-zones):

1. **Classify each onset** by metric distance to the nearest mark occurrence within the **50 m**
   `realtime_observer._CAL_MATCH_TOL_M` (`COACHABLE_TOL_M = 50.0`; value-synced, not imported —
   `analyze` stays stdlib-pure). No mark within tol → *off-zone*, excluded from the denominator.
2. **Gate on coachable occurrences only**; repeat dabs at one mark collapse to that occurrence.
   An occurrence is **coached iff it drew an ACTIONABLE cue** — grading on the per-cue verdict,
   not sub-window onset timing, so a driver braking a hair before an actionable cue does not flip
   the zone red (the actual noise #527 targets; TOO_LATE/AFTER_FACT stay caught globally).
3. **Report both ratios** — raw per-onset + off-zone count, and the coachable-occurrence ratio —
   plus **zones-cued / zones-crossed** (flagged brake passes vs passes that drew an actionable
   cue), stating the #522 guarantee directly.

### Self-hosted cursor daemon #538 review (round 3)
- **[HIGH] deterministic dispatch binding**: `_dispatch_occ` binds a cue to its advisory by the
  **known corner relation** (`occ.corner + 1 == dispatch.corner` — advisory 0-based, dispatch
  spoken 1-based), nearest time only as the sub-zone tie-break — not a fuzzy time-only match.
- **[MEDIUM] encapsulation**: `_CAL_MATCH_TOL_M` → public `CAL_MATCH_TOL_M` in the observer
  (alias kept); analyzer imports the public name.

### Codex #538 P1 (round 3) — stale cross-lap occurrences
`_onset_occ` binds only to a **time-local** advisory (fired within `ONSET_CUE_LEAD_MAX_MS`=10 s
before the onset). A later-lap pass whose advisory was dropped is a distinct uncoached `("gap",…)`
pass, never a stale earlier-lap occurrence — so a later uncued lap can't be masked. Test:
`test_later_lap_dropped_cue_not_masked_by_earlier_lap`.

### Qodo #538 review (all three addressed)
- **Single source of truth (Rule 263211)**: `COACHABLE_TOL_M` is now
  `from realtime_observer import _CAL_MATCH_TOL_M as COACHABLE_TOL_M` — imported, not
  re-declared, so analyzer/observer can't drift. Observer is stdlib-pure → `analyze` stays so.
- **`CueVerdict.corner` doc**: corrected — it is the SPOKEN 1-based corner (`corner+1`) that
  `coaching.voice` forwards, not 0-based; the metric binds by timestamp, never by that field.
- **Occurrence double-count**: WONTFIX (does not manifest) — the observer emits one advisory
  per corner pass (deduped, lap-wrap reset), `late_brake` has no live `act` cue (#522), so each
  `brake_mark_occ` entry is a distinct gate-grade pass (`zones_crossed=8` == #522 Magione 5→8).

### Codex #538 P1 hardening (all three addressed)
- **Occurrence distinctness**: keying by *occurrence* (not `corner`) keeps merged-corner
  sub-zones (`detail.zone`) and multi-lap re-crossings distinct — one coached pass can't mask an
  uncued one.
- **No vacuous pass**: brake onsets with **zero** brake marks fail the gate (a pipeline emitting
  no marks is not evidence of coverage).
- **Same-mark coverage**: a cue binds to its own occurrence by **nearest recorder timestamp**
  (advisory↔dispatch ~1 ms; other passes seconds away) — T1's cue can't cover T2's onset. Time,
  not corner: `coaching.cue` is 0-based, `coaching.voice` is the SPOKEN 1-based corner
  (`corner+1`, `voice/resolver.py`) — an intentional convention, **not** a bug.

## Verification — real rig taps (`.scratch/pr525-*.jsonl`, Magione 2455.7 m)

Ran the NEW `analyze` on the actual #525 live-drive taps. The metric is now **stable** where the
raw ratio was noisy, and honest:

| tap | raw (old-style, noisy) | coachable zones (gate) | cued/crossed |
|---|---|---|---|
| pr525-final-tap | 6/9 | **4/4 ✅** | 7/8 |
| pr525-main-tap3 | 6/12 | **3/4** (1 real dropped-pass gap) | 7/9 |
| pr525-tap2 | 6/9 | **4/4 ✅** | 8/9 |
| pr525-main-tap2 (from-main control) | 0/13 | 0/4, `evidence_present:false` | 0/9 |

The issue's narrative mis-attributed the 2nd uncovered onset as a "T4 repeat"; the real data
shows it was the **T5 pass** (driver braked ~0.02 s before the actionable cue). Under the fix,
final-tap/tap2 are GREEN (every coachable pass drew an actionable cue); main-tap3's 3/4 is a
**genuine** dropped-heads-up pass (9 crossed, 7 cued) = **#522-V2 phase-slot scheduler** scope,
surfaced cleanly rather than as pre-fix noise.

- Unit: `tests/test_semantic_timeliness.py` — `test_off_zone_onset_excluded_from_gate`,
  `test_repeat_onsets_in_one_zone_count_once`, `test_no_brake_marks_but_onsets_fails_gate`,
  `test_cue_for_one_zone_does_not_cover_another`; all existing tests still green; `make ci-fast` OK.

## Files

- `tools/ai_sidecar/voice/semantic_timeliness.py`
- `tests/test_semantic_timeliness.py`
