---
type: investigation
status: active
created: 2026-07-24
updated: 2026-07-24
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/pitfalls/cross-issue-pointer-rot.md
---

# Backlog reconciliation sweep — 2026-07-24 (all 12 open issues)

`/backlog-steward` ultracode run: 12 per-issue evidence agents + dep-map agent
(60 dependency claims) + synthesis, then a 6-agent adversarial panel on both
close candidates. Read-only; no board (no `ops/board_manifest.yml`). **Tier-3
substrate (ac_copilot) was UNREACHABLE the whole session** — grounded on Tier-2
vault + gh + local main (3bcd3a2). Full evidence:
`.scratch/backlog-steward/ledger.json` + `reconcile-2026-07-24-full.json`
(gitignored, this worktree).

## Verdicts (evidence-grounded, ≥2 signals each)

| Issue | Verdict | Key fact |
|---|---|---|
| #627 rig-freeze master | **drifted** | Investigation alive; body 4 evidence-generations stale (§6.1/§6.2 answered, §6.3 killed, §6.5 resolved by #668; §3.4→launch-cycle accumulator; §3.5 hash-loop retracted → float→decimal formatting loop; upstream acc-extension-config#622 FILED, open) |
| #625 overlay spike | **drifted** | Hypothesis intact + untested; method rests on refuted i.i.d. coin-flip model — needs boot-scoped redesign before running (tooling merged, PR #657) |
| #619 voice/WASAPI wedge | **stale:superseded** | Panel 3–0 upholds close, CONDITIONAL: atomic extract-then-close (3 residues tracked nowhere else: telemetry_tick hello-ack gate; voice-endpoint own-headset invariant; VOICE_BANK env switch) |
| #534 enrichment registry | **live** | Zero delivered; both hardware gates point at closed issues (#59/#119 phantom chain) — repoint Part C→#117, resolve Part D |
| #531 tablet dashboard | **partially-delivered** | Parts A–F merged (#547/#590/#595/#615/#618); remaining: Part G latency gate (MUST), H build-or-strike, I, P7 rig-verify |
| #529 Alien Lap epic | **partially-delivered** | P1–P5 code merged, all 8 children closed; gates G1-pace/G2/G3 + L4/L0/meta-prior unowned; rig-blocked on #627 |
| #522 brake cues | **partially-delivered** | V1 fully shipped (#523/#525/#538; re-measured 7/7 actionable); V2 remains; PR #656 refutes its COACH_V2 premise + creates calibration-bypass risk |
| #432 Atelier adoption | **partially-delivered** (panel-amended from stale) | Close REFUTED 2–1: hud_settings.lua (Part A scope) never restyled/descoped/tracked; racing_line.lua colors off-token; headline surfaces delivery itself verified solid |
| #401 ROADMAP | **drifted** | All 7 spawned epics (#402–#408) delivered within 48 h of filing; matrix + vault Roadmap.md frozen at 2026-06-30 — rewrite both in one change |
| #381 expressive voice | **partially-delivered** | All machine-checkable ACs shipped (#429/#441/#451/#519); sole remainder is human A/B listen — against baked clips, NOT a live lap (PR #523 removed live critical imperatives) |
| #117 Arduino fan/OLED | **live** | Premises re-verified; not absorbed anywhere; #534 Part C depends on it |
| #86 rig-screen Phase-2 | **partially-delivered** | A4/E/token-rotation shipped under other issues (#430/#365/#361); remaining: on-glass smoke (blocked-on-rig accurate) + Part F residue |

## Proposals (report-only; nothing executed)

Closes → operator: #619 (after filing 3 extraction issues), #432 (only after
extraction, or keep open narrowed). Rewrites → github-issue-creator: #627, #625,
#534, #531, #522 (split V2), #401 (+vault Roadmap.md same change), #86.
Priority (ICE): #401 rewrite → #522 V2/calibration-bypass → #381 listen →
#627 brief refresh → #534 Part A (rig-independent) → #86 reconcile.

## Open threads for next session

- Re-run Tier-3 prefetch; spot-check #619/#432 verdicts against substrate.
- #522/#529 calibration-bypass: alien-line launches skip #525 driver brake
  calibration (`_brake_calibration_active`) — behavioral risk, route to a fix.
- Unnamed 0x7ff910 module from wedge #3: if a future wedge names it as an
  overlay DLL, #625/#627 mechanism sections change materially.
