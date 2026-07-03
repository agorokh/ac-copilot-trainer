---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-03
updated: 2026-07-03
issue: https://github.com/agorokh/ac-copilot-trainer/issues/381
relates_to:
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-441-voice-signature-gate-2026-07-01.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Issue #381 — intensity scaling acoustically verified; at-wheel listen still human-gated (2026-07-03)

`/autonomous-deliver 381`. #381 was reopened (2026-07-02) **only** for the human-gated at-wheel
A/B listening confirmation after PR #451 shipped the code. Reconciled against live state, then
produced operator-grade acoustic proof so the human step is a ~15-second desk listen, not research.

## Live state (reconciled, not parroted)
- **PR #451 MERGED** 2026-07-02T07:50:14Z (merge `81be1f3`, ancestor of `origin/main` `9e88794`).
- `git show origin/main:tools/ai_sidecar/voice/vocabulary.py` → `INTENSITY_CHAIN_VERSION = 3`,
  `EXPECTED_SIGNATURE_SUFFIX = race-engineer-original-v1+prosody2+intensity3` — **matches** the baked
  bank `kokoro:am_fenrir+ff8+race-engineer-original-v1+prosody2+intensity3`. Code and bank consistent.
- Machine-checkable ACs met in merged code: persona license documented (`vocabulary.py:101-102`),
  `voice_signature`+`vocabulary_hash` drift gate, ≥3 tiers baked (`late_brake` calm/alert/urgent/critical).

## Acoustic proof on the REAL bank (`.scratch/coach-bank-kokoro-fenrir-v3-intensity3-20260702`)
Independent numpy measurement (fleet precedent: *acoustic measurement proves the headline*).
- **Same-word "Brake" ladder** alert→urgent→critical: duration `432.6→379.6→361.4 ms` (monotonic
  **terser**); centroid `2640→2967→3762 Hz` (monotonic **brighter**, +42%); RMS `−21.79→−20.65→−21.94
  dBFS` (near-flat; critical ~1.3 dB **sub-JND** dip below urgent — not a defect; rate+brightness are
  the dominant urgency cues per Hellier/Edworthy).
- **Headline A/B** (the literal AC): calm apex "More entry speed." (1109 ms, −24.78 dBFS) vs critical
  "Brake!" (361 ms, −21.94 dBFS) → critical **+2.84 dB louder, 3× terser**. **PASSES.**
- Repo `tools.ai_sidecar.voice.timing_report --bank <intensity3>` (run from intensity3 code):
  `brake_alarm_within_450ms=True`, `critical_brake_alarm_spoken=True`, `anticipatory_onset_before_mark=True`.
- **Triple cross-validation** of urgent 379.6 ms / critical 361.4 ms: PR #451 comment · numpy · repo tool.

## Disposition (Council-reviewed, 2 voices)
Ship intensity3 as-is; **do NOT re-bake**. The sub-JND loudness dip does not warrant re-opening merged
work (scope discipline — outcome observably true via the unmodified path). Do **not** autonomously
close #381 — the AC explicitly requires the operator's at-wheel listen (genuinely theirs).

## Operator heads-up (durable)
The main working tree is on `fix/issue-408-reference-review-hardening` (`cd75ad5`, **intensity2**). If
the sidecar runs from that checkout it rejects the intensity3 bank as a signature mismatch → **voice
disables**. Run the at-wheel test from an **`origin/main`** checkout. `AC_COPILOT_VOICE_BANK` already
points at the intensity3 bank.

## What remains / artifacts
Human ~15-second confirm. Desk-listenable A/B rendered at native levels under
`C:\Users\arsen\Projects\ac-copilot-trainer\.scratch\`: `issue381-full-sweep.wav`,
`issue381-AB-calmapex-vs-criticalbrake.wav`, `issue381-ladder-brake.wav`, plus
`issue381-waveforms.svg` and `issue381-acoustic-ab.json`. Evidence comment:
[#381#issuecomment-4874323968](https://github.com/agorokh/ac-copilot-trainer/issues/381#issuecomment-4874323968).

**Minor separable find:** `timing_report.py` main() crashes with `UnicodeEncodeError` on its final
`print("… → …")` under Windows cp1252 stdout (artifact is written first) — trivial `→`→`->` fix.
