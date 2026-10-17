---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-17
updated: 2026-10-17
issue: https://github.com/agorokh/ac-copilot-trainer/issues/854
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-854-coaching-default-off-2026-10-17.md
  - AcCopilotTrainer/pitfalls/assisted-drive-archive-rotation.md
---

# #854 clause 3 — model coaching backend: rig RTX3060 vs remote M4 LM Studio

Operator direction (2026-10-17): investigate (1) llama back on the rig's RTX 3060 and
(2) network inference from the canonical Mac Studio's existing LM Studio. Operator then
approved option 2 (shared `qwen/qwen3.5-4b`) and an install–measure–uninstall of option 1.

## Method (matched, AG_PC)

`.scratch/inference854/ab_run.py` (Part B kit): own loopback sidecar per arm (only the
inference env differs), `auto_drive` Porsche 911 GT3 R @ Magione GGV with
`--drive-seconds 360 --tap-seconds 360` via `remote_launcher`, PresentMon 2.6 bound to the
verified `acs.exe` PID, nvidia-smi 2 Hz, typeperf CPU, authenticated archive-off readback
before any lap (abort otherwise), archive-on restore, laps/combo/video verification.
Window: 330 s from guard confirmation + 5 s. Native 3440x1440@144; all frames
`Hardware Composed: Independent Flip`. A–B–A–C order. Gotchas: without `--tap-seconds`
the run ends after the 30 s WS tap; PresentMon must drain after game close (~2 min) — a
kill loses its backlog; `QPCTime` is seconds.

| Arm | fps | display p99 / max ms | present max ms | VRAM peak | CPU mean |
|---|---|---|---|---|---|
| A1 baseline (off) | 69.86 | 15.38 / 21.6 | 64.1 | 3.9 GB | 36% |
| B llama3.2:3b on 3060 | 69.45 | 15.55 / 22.2 | 37.6 | 6.5 GB | 45% |
| A2 baseline (off) | 69.50 | 15.43 / 21.8 | 63.2 | 4.0 GB | 42% |
| C remote M4 qwen3.5-4b | 69.69 | 15.34 / 18.2 | 47.0 | 4.0 GB | 36% |

No arm had a displayed interval over 33 ms. AC alone holds the 3060 at ~73% mean / 100%
peak utilization and at its 170 W power limit.

## Option 1 — llama on the RTX 3060: game unaffected, model starved

Frame pacing stays inside A1/A2 drift. But under game load 105 generations took median
2.6 s, p95 3.4 s, max 4.8 s (idle: sub-second); corner hints have a 2 s deadline, so 154
requests expired and **no model advice reached the panel**. Cost: +2.6 GB VRAM, +~8 points
CPU, plus the unresolved NVIDIA 0x133 history (not exercised by short runs). Verdict: not
viable for real-time coaching. Ollama 0.40.5 was installed (signed Ollama Inc.), measured,
and uninstalled; the pre-existing 31.5 GB `~/.ollama` store was set aside and restored
byte-count identical; the installer's user-PATH entry was removed (receipt kept).

## Option 2 — remote M4 LM Studio: approved and delivered

Existing Tailscale HTTPS face of the fleet LM Studio (shared with the HA voice plane).
Rig RTT ~13 ms, TLS 67 ms. `qwen/qwen3.5-4b` is a thinking model: without
`reasoning_effort=none` every reply was empty. With it, from the rig: 30/30 corner replies
correct and inside the approved set (0.29–1.25 s), narration 1.30–1.43 s, between-lap
exact-echo 6/6. In arm C: 134 requests reached the M4, sidecar ended `ready`, 5 discards,
and **140 accepted model corner advisories were delivered to the HUD** (CSP log, session
00:20–00:26). Rig GPU/CPU indistinguishable from baseline. Between-lap focus was not
selected by Coach v2's gate in this assisted run (reference `track.map` has 0 corners).

Delivered: PR #868 (`5bc4e66`) — approved-origin remote client, reasoning switch, bearer
token, served-model identity check, truncation trim; PR #869 (`31d158a`) labels in-race model advice
`adviceSource=model` (the diagnostic log called all 140 `rules`). Rig user env now selects
the backend (rollback receipt `.scratch/inference854/env-rollback.json`); deployed
`start_sidecar.bat` reports `enabled/remote=true`. Fail-safe live: approved closed port →
corner dropped at 2.04 s, debrief rules; unknown host → rules in 1 ms.

## Limits and open items

- Assisted GGV drives, not human driving; foreground inferred from PresentMode only.
- Shared model with HA voice: contention not load-tested; 0x133 not addressed.
- `Rig - GPU Health Logging` task found **Disabled** (last row 03:23 UTC, before these
  runs; not changed here). No open owner: workstation-ops#4004 is closed; possibly disabled by the concurrent workstation-ops clean-host sweep — operator decision.
- Incident: an earlier unguarded drive evicted one personal lap; restored exactly — see
  [[assisted-drive-archive-rotation]].
