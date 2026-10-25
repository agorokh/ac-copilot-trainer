---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-25
updated: 2026-10-25
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-22-061100Z-issue401-roadmap-reconcile-696292.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-23-074507Z-post-merge-pr934-815-run07-pass.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-072038Z-issue534-operator-gate-0ce53e.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-184420Z-issue529-retained-diagnostic-f793a1.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-24-192500Z-issue401-roadmap-expansion-c5d194.md
  - AcCopilotTrainer/pitfalls/linkage-autoclose-against-intent.md
---

# Issue #401 roadmap reconciliation — paired body and `Roadmap.md` refresh (`469e2b5`)

Operator invoked `/autonomous-deliver 401` (`STATE=OPEN`, labels `["enhancement", "epic"]`, no `not-this-cycle`/`paused`/`blocked`). Reconciled the [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401) GitHub issue body (previously at `2026-10-21` / `696292a`) and its durable twin [`Roadmap.md`](../Roadmap.md) together at `origin/main` `469e2b5` (through merged PRs #899, #918..#939).

## Reconciled deltas since `696292a` (PR #916, 2026-10-21)

1. **#815 live voice engineering acceptance PASS (`2026-10-22..23`, PRs #921..#935):**
   - [PR #921](https://github.com/agorokh/ac-copilot-trainer/pull/921) (`612328d`): band-limited zero-phase chirp search + `adc_time_diagnostic` (WASAPI `inputBufferAdcTime` callback-period artifact moved to diagnostic).
   - [PR #923](https://github.com/agorokh/ac-copilot-trainer/pull/923) (`5700ca4`): canonical `rig_lock hold` + `auto_drive --rig-owner-pid` + `remote_launcher` allowlisting to compose live voice capture with `auto_drive`.
   - [PR #925](https://github.com/agorokh/ac-copilot-trainer/pull/925) (`78e1fe9`): monotonic clock (`mono_ms` / `t_mono_ms`) cross-process timebase joins (`monotonic_timebase_valid`, `dispatch_monotonic_stamped`).
   - [PR #927](https://github.com/agorokh/ac-copilot-trainer/pull/927) (`f3b2b28`), [PR #928](https://github.com/agorokh/ac-copilot-trainer/pull/928) (`629c648`), [PR #929](https://github.com/agorokh/ac-copilot-trainer/pull/929) (`f86fcc4`): restored 6-channel `Rig Speakers - Front and Rear` (`0x60F`) and isolated game-audio masking (`audio.ini` `MASTER=0.08`, restored byte-exact after each run).
   - [PR #930](https://github.com/agorokh/ac-copilot-trainer/pull/930) (`3e9732a`): leave-one-out room-response phrase completeness criterion (`z >= 6` over 6 equal-energy segments + local null + loopback proof).
   - [PR #932](https://github.com/agorokh/ac-copilot-trainer/pull/932) (`3d88b17`): earliest-onset brake-lead anchoring (`mark - 50 m`).
   - [PR #934](https://github.com/agorokh/ac-copilot-trainer/pull/934) (`1deb45d`, handoff [#935](https://github.com/agorokh/ac-copilot-trainer/pull/935) `b4cf35d`, [run-07 handoff](2026-10-23-074507Z-post-merge-pr934-815-run07-pass.md), [#815 comment 6360080008](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6360080008)): coast-reachable brake-cue suppression (`v² − v_apex² ≤ 2·0.1 g·d`) + `act_latency_budget` in `not_exercised_gates`. Run 07 on installed `1deb45d` (`lamborghini_huracan_gt3` @ `magione`) achieved `engineering_acceptance: PASS`, `failed_gates: []`, `12/12` phrases complete, timebase `±25.0 ms`, brake heads-ups T9 lap 0 (`4773 ms`) and T1 lap 1 (`2000 ms`, coverage `2/2`), `audio.ini` restored byte-exact, and assisted laps registered `authority=ai` (ledger `160 → 165`; `human_live_qualification: NOT_ESTABLISHED_BY_THIS_ENGINEERING_CAPTURE`). Also corrected [`Roadmap.md`](../Roadmap.md)'s earlier PR #939 shorthand (`982909f` / `22/22 clauses, 7/7 phrases`) to match the verified `1deb45d` receipt and checkbox state on #815 (Part D voice-path verification checked `[x]`; only the autonomous green Porsche @ Spa rendered-application-state inspection checkbox + human-live qualification decision remain open).
2. **#534 operator-gate stop receipt (`2026-10-24`, [PR #936](https://github.com/agorokh/ac-copilot-trainer/pull/936) `c5d1948`):**
   - Re-verified `#534` Parts A+B complete on `main` and recorded the operator-gate stop on Parts C (`#117` `not-this-cycle`), D (dormant pedal haptics), and E (optional ShakeIt seat experiment) ([handoff](2026-10-24-072038Z-issue534-operator-gate-0ce53e.md), [#534 comment 6381413959](https://github.com/agorokh/ac-copilot-trainer/issues/534#issuecomment-6381413959)).
3. **#529 retained-state diagnostic & self-play provenance policy gate (`2026-10-24`, [PR #937](https://github.com/agorokh/ac-copilot-trainer/pull/937) `00bf871`):**
   - Recorded the 9-lap AC-valid retained-plant `ks_mclaren_650_gt3` @ `magione` diagnostic (`97.369 / 97.449 s` at `1.0` → `95.226 / 95.273 s` at `1.025` → `95.267 / 95.276 s` at `1.025`, +1 lateral bin `f19c614bcd61`, QSS `91.94 s`, `+27.33%` off TT P10 `74.784 s`; diagnostic only, not cold-start G1; ledger `165 → 174` as `authority=ai`) ([handoff](2026-10-24-184420Z-issue529-retained-diagnostic-f793a1.md), [#529 comment 6388233038](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388233038)).
   - Surfaced the concrete policy gate between `#815` Part B and `#529` self-play refits: `tools/lap_qualification.py:577` (`if authority != "human" and use != "analysis":`) rejects explicitly attributed `authority=ai` native harness archives for `use="plant_fit"` (`control_authority_not_human:ai`), causing `observe_lap_tyre_state` to return `fit_eligible=false`. Operator decision pending on whether to allow explicitly evidenced native harness self-play archives for `plant_fit` (keeping human progression/references and MOZA/imports excluded) or retain the blanket ban, alongside supplying the existing human session selection for Gate G3.
4. **2026-10-24 `/roadmap-expansion` slate (`2026-10-24`, [PR #939](https://github.com/agorokh/ac-copilot-trainer/pull/939) `469e2b5`):**
   - Synced the three `explore`-qualified finalist decision cards from [`roadmap-expansion-2026-10-24.md`](../../03_Investigations/roadmap-expansion-2026-10-24.md) ([#401 comment 6388404529](https://github.com/agorokh/ac-copilot-trainer/issues/401#issuecomment-6388404529)) into `#401`'s GitHub body so `#401` and [`Roadmap.md`](../Roadmap.md) no longer drift (`REX-20261024-01` on `#529` Gate G1, `REX-20261024-02` in [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938) / open PR [#940](https://github.com/agorokh/ac-copilot-trainer/pull/940), and `REX-20261024-03` held on `#529` Gate G3 / Vertical 7).

## Requirement / output verification table

| Controlling clause (`#401` body + `Roadmap.md` invariant) | Concrete output / consumer surface | Verification |
|---|---|---|
| State-consistency invariant: update `#401` body and `docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md` together | `#401` GitHub issue body updated via `gh issue edit 401 --body-file` (`issue-401-body.after.md`, backup + `restore.sh` in `.scratch/backlog-steward/body-refresh-20261024/`); `Roadmap.md` updated in lockstep | Live `gh issue view 401 --json body,state,labels` readback matches `issue-401-body.after.md`; `Roadmap.md` vertical table & sequencing match `#401` |
| One dated evidence handoff node; no edits to shared hot vault files (`governance-hub#918`) | `docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-25-045500Z-issue401-roadmap-reconcile-469e2b5.md` | `make ci-vault` (`test_no_shared_vault_edits.py`, `ci_policy.py`, `policy_tracked_files.py`) and `python3 scripts/hook_session_start_handoff.py` consumer surface |
| Product-source work stays with its existing owner; preserve existing acceptance, labels, and open/closed states | No product source modified; `#401` stays `OPEN` (`Refs #401`, `closingIssuesReferences=[]`); `#813` (`CLOSED`), `#86`, `#529`, `#534`, `#815`, `#938`, and `#117` (`not-this-cycle`) unchanged | Verified via `gh issue list --state open` and `gh pr view --json closingIssuesReferences` |

## Fan-out report

- Fan-out: **none created** (operator-started run budget: 2; 0 issues/follow-ups created).
