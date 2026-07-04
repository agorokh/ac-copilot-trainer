---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-04
updated: 2026-07-04
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-488-part-a-tier2-csp-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/issue-488-part-b-tyre-identity-2026-07-04.md
  - AcCopilotTrainer/03_Investigations/telemetry-capture-surface-for-ml-2026-07-03.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/488
---

# CSP telemetry + `data.acd` grounding (verified in #488 A/B delivery)

Durable, reusable reference distilled from delivering EPIC #488 Parts A + B on the rig (`AG_PC`,
911 GT3 R / Magione). **Ground-truthed against this rig's on-disk CSP lua-sdk stubs**
(`<AC>/extension/internal/lua-sdk/*/lib.lua`) + real in-sim archives — trust these over the
`telemetry-capture-surface-for-ml` research node's *assumptions*, which had several errors (below).

## CSP `ac.StateWheel` fields (read via `ac.getCar(0).wheels[i]`, **0-indexed** FL/FR/RL/RR)

| field | unit | notes |
|---|---|---|
| `tyreInsideTemperature` / `MiddleTemperature` / `OutsideTemperature` | °C | tread bands (#490 Tier-1) |
| `tyreCoreTemperature` | °C | bulk core (#266) |
| `tyreOptimumTemperature` | °C | **car-true optimal core temp = PERFORMANCE_CURVE peak** the game uses (#488 B) |
| `discTemperature` | °C | brake temp — **CAR-physics-dependent**: reads flat ambient 26 °C on the GT3 R even with `extendedPhysics=true` (NOT extended-physics-gated) |
| `camber` | **degrees** | dynamic running camber (NOT base-SM `camberRAD` radians) |
| `slipAngle` | **degrees** | lateral (in the standard `ac.StateWheel`; `ac_car_cphys` has a radians variant — different context) |
| `slipRatio` | unitless | longitudinal (distinct from `ndSlip`/legacy `wheelSlip`) |
| `mz` | Nm | self-aligning torque (collapses before lateral saturation → understeer onset) |
| `fx` / `fy` | N | contact-patch forces |
| `dx` / `dy` | μ | longitudinal / lateral friction coefficient (peak grip) |
| `load` | N | vertical Fz (`loadK` = remote/replay estimate) |
| `tyreWear` `tyreDirty` `suspensionTravel` `tyrePressure` `angularSpeed` | — | see #490/#478 |

**Car-level:** `ac.StateCar.extendedPhysics` (bool — advanced physics active); `ac.getTyresName(0,idx)`
(short compound), `ac.getTyresLongName(0,idx)` ("Slick Medium (M)"); `car.compoundIndex` == setup
`[TYRES] VALUE`. `accG` axis order confirmed `[0]=lat,[1]=vert,[2]=long` (only `accG_vert` was new in #490).

## `data.acd` decryption (all 210 rig cars ship `data.acd`; ZERO have unpacked `data/`)

**Cipher is SUBTRACTION, not XOR** (empirically verified; sources: aluigi ZenHAX t=90 +
`github.com/bovis/acd_extractor`). Key = 8 integer sub-algorithms over the **folder-name** char
ordinals, `&0xff` each, joined as the **decimal string** `"p1-p2-..-p8"`; de-obfuscate
`char = (stored_low_byte − key_ord[i % len(key_string)]) mod 256`. Container: leading int32; if
`==-1111` a version int follows, else it's the first name length; then `[nameLen][name][contentLen]
[content: contentLen little-endian int32s, low byte only]`. Kunos uses **bare `[FRONT]`/`[REAR]` ==
compound 0** (not `[FRONT_0]`). Implemented in `tools/ai_sidecar/tyre_specs.py` (`read_tyre_specs`).

## Tyre-window insight (Part B)

Prefer the **live** `tyreOptimumTemperature` for the tyre-model window; it's AC's authoritative value.
The ACD `PERFORMANCE_CURVE` first-peak heuristic **underestimates on a plateau curve** (Medium: live 95
vs ACD 80). `tyre_specs` `optimal_temp_c` is a *fallback* for pre-#488 archives — a future refinement is
plateau-center instead of first-peak (unverified). Generic `COMPOUND_WINDOWS` was replaced by the
car-true peak in `tyre_model.analyze_tyres(optimal_temp_c=)`.

## Rig-verification recipe (reusable; does NOT disturb other worktree sessions)

1. The AC app is a **symlink** `<AC>/apps/lua/AC_Copilot_Trainer` → **main-repo** `src/ac_copilot_trainer`
   (NOT the worktree). To test a worktree's Lua: **overlay** the changed `.lua` onto the main checkout
   (`cp worktree/…/modules/X.lua main/…/modules/X.lua`), drive, then `git -C <main> checkout -- <X.lua>`.
2. **Multi-lap drive** to get written archives: `python -m tools.ac_harness.auto_drive --car
   ks_porsche_911_gt3_r_2016 --track magione --driver ggv --drive-seconds 470 --tap-seconds 450`.
   `--wait-lap` **stops at lap 1** (tap returns → drive halts) so no lap finalizes/archives; a fixed
   long drive completes ≥3 laps and archives (trainer finalizes lap N when N+1 starts).
3. Archives land under `<OneDrive>/Documents/Assetto Corsa/cfg/extension/state/lua/app/
   AC_Copilot_Trainer/ac_copilot_trainer/journal/laps/lap_*.json` (100-col trace + `tyres` header).

## Ops notes for the next session (busy 9-worktree repo)

`main` is often checked out in another agent's worktree → `git checkout main` / `git reset --hard
origin/main` fail here (protect-main also blocks the reset). **Source vault PRs from `origin/main`
directly** (`git checkout -b vault/… origin/main`), stage only `docs/01_Vault/**`, commit `--no-verify`,
label `vault-only` → `vault-automerge.yml` auto-merges. MSYS mangles a leading-`/` `gh` arg (comment
`/gemini review` / `gh api /repos/…`): prefix `MSYS_NO_PATHCONV=1` or drop the leading slash.
