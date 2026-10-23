---
type: handoff
status: active
created: 2026-10-23
updated: 2026-10-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-23-001736Z-815-run04-shared-rears-no-go.md
  - AcCopilotTrainer/10_Rig/speaker-endpoint-replug-restore-2026-10-22.md
---

# #815 run 05: AC at −20 dB, digital voice complete, acoustic block criterion still fails

The operator chose a lowered AC master volume for the acceptance run. `audio.ini` MASTER went
from 0.782392026578072 to 0.08 (−19.8 dB if linear), sized from run 04's digital loopback.
It was backed up byte-exact and **restored byte-exact afterwards** (SHA-256 `59024ee9…1944`).
Content Manager did not overwrite it at launch.

The procedure matched run 04: 6-channel rig speakers, voice on [5, 6], composed run on
`78e1fe9`. The `auto_drive` PASS gave 1 lap of 346.622 s and 19 voice dispatches. The guardian
armed about 5 s before the hijack and closed AC and the sidecar gracefully. Cleanup was verified.

## Verdict (`run-05/analysis.json`, SHA-256 `bd14d0a8…a25e`): NO_GO

- **Newly passing:** `loopback_phrase_proof` (digital voice 19/19 on both rears) and
  `all_phrases_inside_calibration` (19/19). Whole-phrase mic scores are 0.41–0.52, onset 11–24
  ms after dispatch, timebase ±26.3 ms.
- **Failing:** `all_phrases_captured_complete`, 0/19. Each phrase fails 2–8 of 27–37 40 ms
  blocks at the same offsets as runs 03 and 04, despite −20 dB game audio and a complete
  digital mix. Failing blocks follow louder blocks more often (24% vs 7% more than 10 dB
  down), which partly supports reverb self-masking. The cause is not fully established. The
  brake reaction and coverage gates follow; there was no `act` cue.
- The lap was registered `authority=ai` with origin `…run05…ac_master_0.08` (ledger 163).

Evidence:
[#815 run 05](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6355585318).

## Next action (#815 open, operator/design decision)

Masking and timing are solved for this condition. The remaining blocker is the acoustic
completeness criterion: every block must correlate ≥ 0.20 with the dry clip through a
reverberant cockpit. Options include matching against the clip convolved with the room
response measured from the chirps, or judging truncation from the recorded endpoint plus the
acoustic tail. Changing the criterion needs an explicit decision; no threshold was changed.
Fan-out: none created.
