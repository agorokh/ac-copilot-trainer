---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-17
updated: 2026-10-17
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/01_Decisions/setup-exchange-native-csp-session-2026-10-16.md
  - AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
---

# #86 native Setup Exchange — agent-run live service readback

PR [#862](https://github.com/agorokh/ac-copilot-trainer/pull/862) merged as `076361a`
(head `21e6c9a`, one exact-head review, zero unresolved threads). The retained row *"Actual
service and in-game application — Unverified pending reviewed merge/distribution"* was
therefore actionable; this is its live settlement on the rig.

## Distribution (two halves; the sidecar half was initially missed)

The native path needs **both** the trainer Lua and the sidecar. No firmware flash was needed:
#862 touched no device firmware, only the sidecar, trainer Lua and the host simulator.

- **Trainer Lua** — the installed app is a junction to the **primary checkout**, at `origin/main`
  `8907ddf`, 0 behind. `setup_exchange.lua` blob `9ff6bd57e9abb26ca332a29b4d20a6ebdb6cf733` is
  byte-identical to `origin/main`; the harness reported `installed app provenance: match`.
- **Sidecar** — this half was **stale** and was first wrongly counted as distributed. The operator's
  packaged `dist/AC-Copilot-Game-Point.exe` bundles the sidecar and reported `/health
  build_commit 70ed2fe` (built 2026-10-15); `git merge-base --is-ancestor 076361a 70ed2fe` is false,
  so the normal Game Point flow still ran the pre-#862 proxy-only Setup Exchange. The live results
  below used a source sidecar (`auto_drive` from the worktree), not the packaged one.
  Repaired the same night through the documented path: `python -m tools.rig_launcher --build-exe`
  from detached `origin/main`, `--self-test` exit 0 (both tablet routes serving), old EXE kept as
  `dist/AC-Copilot-Game-Point.70ed2fe.exe.bak` (SHA-256 `cb9a1bf5…`), new EXE SHA-256 `e76fe971…`.
  The relaunched Game Point reported `/health build_commit 8907ddf`, opened COM6 and accepted the
  panel's `hello` alongside a tablet dash (`peers=2`). Native SE through the *packaged* sidecar with
  a live trainer remains for the operator's own session.

## Live results (real service, real session)

Session established with the sanctioned harness (`auto_drive`, Porsche 911 GT3 R 2016 /
Magione, PASS, HUD rendering). The physical ESP32 screen was observed attached throughout as
`peer=serial:COM6 client=ac-copilot-screen-01 class=screen`. Probes spoke the production v1
external protocol as a `screen` peer through `HarnessClient`.

| Leg | Observed |
|---|---|
| `se.search` car-only | `ok=true`, `count=10`, **`total=149`** — real authors `si3vgerf`, `NevaFleaks`, `sWoRDfiSh`, `GianniLePLoW / TTV`, `[VIP] Oskison.`; downloads `24759 / 9757 / 9654 / 7753`, descending under `-statDownloads` |
| `se.search` car+`magione` | `ok=true`, `count=0`, `total=0` — the service genuinely holds no Magione setups for this car; a valid empty response, not a failure |
| `se.download` + install | `ok=true` → `…/setups/ks_porsche_911_gt3_r_2016/ks_nordschleife/Extrapiramidal.ini`, 1747 bytes, 61 INI sections |
| Non-overwrite collision | Second download installed `Extrapiramidal-2.ini`; original bytes preserved (identical MD5 `05f5aa61…`). Pre-existing `hotlap_24h.ini` / `hotlap_tourist.ini` untouched |
| `setup.list` (PT listing) | `ok=true`, car `Porsche 911 GT3 R 2016`, track `Magione` / Italy, 7 rows with real `abs` / `wing_f` / `wing_r` / `brake_bias` |
| `setup.load` gate, negative | Refused `must be in pits` on **every** attempt — START spawn, PIT spawn, and with `phase=in_pit` |
| In-game setup application | `auto_drive --setup Copilot_Balanced_Fast` → `applied=True`, verified in-sim via the launch-bake path |

## The positive `setup.load` branch is operator-owned, not a defect

`ac.loadSetup` is gated fail-closed on `ac.isCarResetAllowed()`. That predicate is **never true
for an autonomously launched car** — [#466](https://github.com/agorokh/ac-copilot-trainer/issues/466)
measured 0 OK / 152 `must be in pits` across both START and PIT spawns and concluded a real fix
needs an upstream CSP/CM change, out of harness scope. This session independently reproduced it
(three attempts, including a confirmed `phase=in_pit` session). So the runtime screen-tap *apply*
leg cannot be agent-verified by construction; it belongs to a human-launched resettable session,
which is exactly the physical acceptance #86 already retains. No new carrier is warranted.

Side note for the next session: `entry_launcher` only succeeds on *driving*, so a PIT preset makes
it relaunch and kill AC. `--max-launches 1 --attempt-timeout 200` leaves AC parked in the pit box,
which is the way to hold a pit session open. `auto_drive --setup` still generates `StartType=START`.

## Rig state and the black-screen incident

After the readback the session stopped the AC and source sidecar it had started. The operator then
took the rig and found the **panel black**. Evidence: a Game Point sidecar had COM6 open
(`DTR high, RTS low`) yet `/health screen_peers 0`, and a read-only listen on COM6 returned **0 bytes
in 8 s** — the firmware was silent, not merely disconnected. Most likely the open/close churn on the
native-USB CDC port around the stop left the S3 held in reset or ROM download mode (cause inferred,
not proven). Recovery: stopped the orphaned sidecar child (identity checked by PID + command line),
ran Espressif's esptool `--before default_reset --after hard_reset chip_id` (read-only, no flash
write; chip answered as ESP32-S3, USB-Serial/JTAG), and the same listen then showed **12 `hello`
frames (`client_class: screen`) in 12 s**.

The operator's launcher also refused AC sessions with `ac_session: menu_config_required` — CSP 0.2.11
needs `[NEW_UI] REPLACE_MAIN_MENU=0` in `Documents/Assetto Corsa/cfg/extension/gui.ini`, which was
absent. Added it with operator approval (backup kept); the launcher's own preflight then read
`ac_session: idle — press STABLE AC to start a driver session`.

The duplicate `Extrapiramidal-2.ini` test residue was removed; the one real community download
`Extrapiramidal.ini` was retained in the user library and reported to the operator. No firmware
write, no user-setup overwrite. Lesson: do not stop a sidecar that holds the panel's COM port
without a liveness listen afterwards, and check the packaged EXE's `/health build_commit`, not only
the Lua junction, before calling a sidecar change distributed.

Evidence (gitignored): `.scratch/issue86-live/` — `readback-load_refused.json`, `load-probe.json`,
`drive/report.json`, `drive/hud.png`, `drive2/report.json`, `auto_drive*.log`, `pit_launch2.log`.
