---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-19
updated: 2026-10-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-627-stable-ac-chain-2026-10-18.md
  - AcCopilotTrainer/03_Investigations/issue-897-setup-list-journal-scan-2026-10-18.md
  - AcCopilotTrainer/03_Investigations/issue-627-journal-scan-stall-2026-07-30.md
  - AcCopilotTrainer/03_Investigations/issue-627-postlap-freeze-same-loop-2026-07-30.md
  - AcCopilotTrainer/03_Investigations/issue-627-strtod-unbounded-loop-2026-07-29.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627 C2 settled: no freeze symptom reproduces on the deployed build (2026-10-19)

C2 asked which present symptom reproduces: the pre-drive menu, finite main-thread work, or a
sustained graphics-pinned wedge. Read-only evidence from AG_PC on boot 2026-10-16 18:05 PDT
(52 h uptime). No AC launch was made this session: a peer session (#86 screen capture, PR #904)
was using the rig, Game Point and the COM6 screen at the time.

## Verdict per symptom

| Symptom | Present state | Evidence |
|---|---|---|
| Pre-drive menu read as a freeze | Gone | `NOT_DRIVABLE` (#726); every 2026-10-18 harness run pressed Start and hijacked on probe 1/3 |
| Finite post-Start pause (~10 s, then ~3.7 s) | Ours, fixed | `[COPILOT][HITCH] gap=9.54s ours=9532ms u:wsInbound=9515ms` before #898; after `cb9304d`, 0 HITCH ≥ 0.25 s |
| Post-lap 5–10 s freeze | Ours, fixed by #730 | #854 PresentMon, four 330 s drives on 2026-10-17: no displayed interval over 33 ms |
| Sustained wedge (graphics pinned for minutes) | Not seen since 2026-07-22 | see the denominator below |

## The post-#898 observation that settles the pause

Peer harness run `capture-drive2` (`auto_drive`, Porsche 911 GT3 R @ Spa, Game Point sidecar,
COM6 screen attached, app provenance match, Start pressed 21:28:47 PDT). Its CSP log was copied
and hashed (`custom_shaders_patch.log` SHA-256 `3e3d308c…0c0b`). Results:

- 0 `[COPILOT][HITCH]` and 0 `[COPILOT][WS-SLOW]` over 1068 s, ending in `CLEAN EXIT`.
- 355 `RT-DIAG` lines at 3000 / 3008 / 3016 ms min / median / max, unbroken across Start.

The watchdog runs as the first call of `script.update`, before the menu check
(`ac_copilot_trainer.lua:2347`), so it covers the menu and the Start press. Launches 2 and 3 of
#897 (one on deployed `cb9304d`) reported no HITCH either; their CSP logs were overwritten.

## Sustained-wedge denominator (this boot)

About 12 launches are proven main-thread-alive through init, Start and the drive window:
- 7 harness `auto_drive` runs (two #854 verify drives on 2026-10-16, five on 2026-10-18), all
  `drove=True`. The trainer published 265 to 3002 `coaching.snapshot` frames per run from AC's
  main thread.
- 4 #854 PresentMon drives of 330 s each.
- Stable AC run 9 (`ae95ffd`, the 20 s rule): `stable` on attempt 1.

Under the 2026-07-22 regime (~60 % per launch), 0 in 12 has probability ~2e-5. A residual near
20 % per launch (~7 %) is not excluded. About 24 Stable AC attempts on the morning of 10-18 were
killed 5 s after the post-Start pause began, so they say nothing about sustained wedges.

**Unattributed:** Stable AC run 10 (12:28 PDT, build `435c971`, before #898 was deployed) logged
two `froze` verdicts under the 20 s rule. No packet trace covers them. Both attempts that resumed
paused for 3.9 s and 3.6 s, which matches the warm-cache `setup.list` scan. That fits, but it is
not proven.

## Mechanism (hypothesis, not established)

The 2026-07-22 wedge #3 and the 2026-07-30 post-lap stall hit the same three RVAs inside CSP's
÷100 parser loop. The stall was our whole-journal scan, which also ran on every session load
(#730: largest main-thread gap 21.9 s → 3.0 s). Both captures also show raw addresses outside any
module, consistent with LuaJIT code calling the parser. The only historical refutation, "froze
with the app disabled 0/5", used the instrument that scored the pre-drive menu as a freeze.
Hypothesis: the init wedge was our own session-load scan in the parser's slow regime.

## Disposition

Council (perplexity, kimi, mistral; gemini auth-expired, grok late) voted CLOSE, 3–0. Reopen on
any ≥ 20 s graphics pin with physics advancing on the v6 instrument, or a `freeze_forensics`
capture. Upstream acc-extension-config#622 stays open. Correcting its stated direction is the
operator's call.
