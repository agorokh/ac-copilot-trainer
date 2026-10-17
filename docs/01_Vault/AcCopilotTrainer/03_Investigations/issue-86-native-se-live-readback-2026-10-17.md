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

## Distribution (verified)

The installed trainer app is a junction to the **primary checkout**, which sat at
`origin/main` `8907ddf` with 0 commits behind. `src/ac_copilot_trainer/modules/setup_exchange.lua`
hashed `9ff6bd57e9abb26ca332a29b4d20a6ebdb6cf733`, byte-identical to `origin/main`. The harness
independently reported `installed app provenance: match`. No firmware flash was needed or done:
#862 touched no device firmware, only the sidecar, trainer Lua and the host simulator.

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

## Rig state left behind

Baseline restored: no `acs.exe`, nothing listening on 8765 — matching the pre-session state. The
duplicate `Extrapiramidal-2.ini` test residue was removed; the one real community download
`Extrapiramidal.ini` was retained in the user library and reported to the operator. No firmware
write, no user-setup overwrite, no peer process stopped.

Evidence (gitignored): `.scratch/issue86-live/` — `readback-load_refused.json`, `load-probe.json`,
`drive/report.json`, `drive/hud.png`, `drive2/report.json`, `auto_drive*.log`, `pit_launch2.log`.
