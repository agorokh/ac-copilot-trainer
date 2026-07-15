---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/531
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-531-phase1-tablet-dash-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #531 Part D — live tyre vitals + TC/ABS intervention (PRs #590 and #595)

## The gap Phase 1 left (silent, not failing)

Phase 1 shipped a dash that **read `abs_active` while no producer ever sent it** — the
electronics intervention flash could never fire — and a tyre board whose own header
advertised *"core temp / pressure"* over a **permanently empty psi slot**. The STINT page
carried a hardcoded `pressure — · wear —` string bound to nothing. Nothing errored; the
board just under-reported forever. `DESIGN_SPEC.md` §6/§11 had already flagged the shape of
this: *"confirm which the Lua producer actually sends vs the validator merely accepts."*

**Durable lesson:** the validator accepting a field is not evidence anything emits it. A new
wire contract needs **producer + validator + consumer** updated together (the #547 lesson,
re-learned). PR #590 adds a test pinning page ↔ producer ↔ validator so a field the dash
reads can never again be one nobody sends.

## CSP field names — verified on-disk, not recalled

Read from this rig's `extension/internal/lua-sdk/ac_apps/lib.lua` (`ac.StateWheel` /
`ac.StateCar`), not from memory:

| Vital | CSP field | Note |
|---|---|---|
| tyre pressure | `tyrePressure` | dynamic/hot; `tyreStaticPressure` is the cold set value |
| brake temp | **`discTemperature`** | **NOT** `brakeTemperature` — that SimHub/ACC spelling does not exist and reads nil forever |
| tyre wear | `tyreWear` | 0..1, direction ambiguous in the SDK — see below |
| TC/ABS intervention | `tractionControlInAction` / `absInAction` | both *"Physics-only"* → omit key when not a boolean |

## The wear-scale trap (the important finding)

CSP documents `tyreWear` only as *"Tyre wear, from 0 to 1"*. Read as **CONDITION-remaining**
(1.0 = new) the producer inverts a fresh set to `100`, and
`race_management._tyre_advisory` fires **"tyre wear is high"** — carrying a **voice cue** —
at `>= 70`. Every lap on new tyres would announce high wear.

**Measured, not assumed** — 321 checked-in lap archives, 4 cars (911 GT3 R, 488 GT3,
Huracán GT3, `function_0xff`):

- 340 `tyreWear` corner-columns present; **36 ever nonzero**.
- Every nonzero value ∈ **0.000268 … 0.0720**, growing from an exact `0.0`.
- ⇒ **wear CONSUMED** (0 = new) → plain `×100`, **no inversion**. `0.072 → 7.2%` also matches
  `reference_mock.html`'s illustrative *"7% wear"*.

The inverted build was **reproduced live** on the rig emitting `tyre_wear_pct = 100` on new
tyres; after the fix the same peer/car reads `{fl:0, fr:0, rl:0, rr:0}`. A lupa test pins the
measured direction.

> Even after 2 hard laps (199.8 km/h, 5130 m) `tyreWear` stayed exactly `0.00000` while
> pressure and core temp varied realistically — so "0" is the normal reading on a fresh set,
> not a dead channel (other sessions do populate it).

## `brake_temps_c` — the mistake I made, and the durable rule from it

Reads a **flat ambient 26 °C** on the 911 GT3 R across a full hard lap — reproducing the
#488 caveat already documented in `wheel_read.brakeTemp`. Across the same 321 archives only
**32/340** columns ever vary >1 °C (range 26 → 40 °C). Car/session-dependent, **not a capture
bug**. The frozen design defines **no RACE/STINT slot** for it.

**The error:** from "the dashboard has no slot" I concluded "nothing consumes it" and, when the
self-hosted reviewer flagged it as dead wiring (MEDIUM), I **removed it** — without ever
grepping the sidecar. Codex caught the regression:

```
race_management.py:155   brake = self._brake_advisory(frame, lap)
race_management.py:344   temps = _frame_corner_map(frame, "brake_temps_c", "brake_temp_c")
```

`_brake_advisory` raises brake-management **coaching cues** at `_BRAKE_HOT_C = 650` /
`_BRAKE_CRITICAL_C = 850`. The removal silently disabled them. Restored in `def338e`.

> **Durable rule: the `telemetry_tick` is a WIRE, not a dashboard feed.** Its consumers are the
> tablet dash **and** the sidecar's coaching brain (`race_management`). "The dash has no slot"
> is *not* evidence a field is unused — grep `tools/ai_sidecar/` before deleting any tick field.
> The anti-dead-wiring guard's direction is **page-consumed ⇒ producer-emitted**; the converse
> does **not** hold. Two tests now pin `race_management`'s consumption and the threshold headroom.

Streaming it is safe on cars with no brake model: 26 °C is far below 650, so **no false cue** —
the opposite of the `tyre_wear_pct` inversion, where the wrong value *did* cross its threshold.

**Second-order lesson:** I acted on a reviewer's premise without verifying it. A bot finding is a
*claim to check*, not a fact — the same discipline the wear scale needed. Two reviewers
contradicted each other here; the live code decided it, not their authority.

## Rig lore learned this session

- **AC pauses when it loses focus** → `dt≈0` → the publisher's `_due()` accumulator stalls and
  the tick rate collapses (observed: **1 tick / 18 s**), so the dash correctly shows WAITING.
  **A live tablet capture must be taken DURING a harness drive**, not after it.
- **AC user dir is OneDrive-redirected** here: `C:\Users\arsen\OneDrive\Documents\Assetto Corsa`.
  Lap archives live under `…/cfg/extension/state/lua/app/AC_Copilot_Trainer/ac_copilot_trainer/journal/laps`
  (321 of them) — a cheap, decisive ground-truth source that needs no AC launch. Use
  `auto_drive.resolve_ac_user_dir()`; guessing `Documents/…` finds nothing.
- **`acs.exe` died once at 20 m** with identical code; an immediate retry drove a clean lap
  (`ok=true`, 133.264 s). Sim death here is a **flake** — retry before suspecting the diff.
- The **app junction** (`apps/lua/AC_Copilot_Trainer`) served the *primary* checkout, which is
  parked on another session's branch. It was repointed to this worktree for verification and
  **must be restored** — running a stale trainer is exactly #575.
- Phase 1's `.scratch/dash_feeder.py` — which the #531 Phase-1 node called "reusable for
  Part F" — **is gone**, having lived in gitignored `.scratch/`. The disposability pitfall is
  real: promote durable tooling out of `.scratch/` or it does not survive the session.

## Verified (observed, live)

Browser-class WS peer + real trainer + real sim (911 GT3 R @ Magione, AG_PC):

```
tyre_pressures_psi = {fl: 17.37, fr: 17.33, rl: 17.72, rr: 17.64}   REAL, varying
tyre_wear_pct      = {fl: 0, fr: 0, rl: 0, rr: 0}                   FIXED (was 100)
brake_temps_c      = {fl: 26, fr: 26, rl: 26, rr: 26}               flat ambient
rpm_max = 9000                                                      real 911 redline
```

On the P7 in Fully Kiosk the tyre board renders live per-corner **psi** where it was
permanently blank; car-adaptive electronics still correct from the real 911 schema
(`BRAKE BIAS 68.0%`, `TC 3/12`, `ABS 8/12`, **no** TC-CUT/MAP tile). Harness drives:
`ok=true`, 2 laps @ 199.8 km/h / 5130 m, and `ok=true`, 1 lap 133.264 s.

`make ci-fast` OK (2921 passed, 73 skipped).

## Car-swap acceptance criterion — PASSED (closed this session)

Open since Phase 1. Both cars driven at Magione, tablet on `adb reverse`, electronics from
`ac.getSetupSpinners()` — no hardcoded ranges.

| Tile | 911 GT3 R | **bmw_m3_gt2** |
|---|---|---|
| ABS | `8/12` | **greyed → `NOT FITTED`** (never `0/0`) |
| TC | `3/12` | **`3/13`** — real range `0..12 step 1` ⇒ denominator **13** |
| BRAKE BIAS | `68.0%` | `66.0%` (range `52..80`) |
| TC-CUT / MAP / BOOST | absent | absent |
| `rpm_max` | `9000` | **`8750`** |
| fuel capacity | 120 L | 110 L |

> **The denominator genuinely differs between cars (12 vs 13).** A hardcoded `/12` would have
> been silently wrong on the M3 GT2 — this is precisely why the design forbids hardcoding, and
> the first live proof of it. `bmw_m3_gt2` IS installed on this rig and is the exact no-ABS car
> `reference_mock.html` toggles to; its live schema has **no `ABS` section at all** (63 sections).

Also closes: **RACE hero shift LEDs rpm-banded from real `rpm_max`** (9000 vs 8750, both from
CSP `car.rpmLimiter`).

## PR #595 — make intervention evidence part of the harness run

The remaining capture gap was structural, not a clean-driver coincidence: `telemetry_tick` is
routed by **client class**, while `HarnessClient.hello()` was classless. No subscription could make
the in-run tap receive ticks. PR [#595](https://github.com/agorokh/ac-copilot-trainer/pull/595)
adds an opt-in `observer` class (tick consumer, never a haptic actuator), makes `run_auto_drive`
pass it explicitly to its tap, and persists a three-way `true` / `false` / `absent` summary for
`tc_active` and `abs_active` in every `AutoDriveReport`. Generic `tap_frames()` callers stay
classless by default and receive no unsolicited 20 Hz stream.

Resolution evidence on the functional head `93685d4`: required CI green, 0 GraphQL review threads,
clean resolve-gate ledger, and the current-SHA self-hosted reviewer reported no medium-or-higher
findings. The resolution branch also merged current `main`; focused harness/protocol/endpoint tests
passed **211/211**, and full parity passed **2,961 tests, 77 skipped, 86.85% coverage,
`ci-fast: OK`**. The actual `true` intervention observation remains a rig-driving criterion, but it
is now machine-capturable inside the prescribed run instead of requiring a side-channel tap or
human tablet observation.

Final review hardening caught an important API boundary: making generic `tap_frames()` always use
`observer` would silently attach an unsolicited 20 Hz stream to every topic-tap caller. The final
contract keeps `client_class=None` as the generic default and makes `run_auto_drive` pass
`observer` explicitly. A fake-client test pins both the classless default and explicit opt-in; the
drive orchestration test separately pins that the composed evidence path opts in.

## Still not verified (stated so the next session doesn't assume it)

**`tc_active` / `abs_active` were never observed `true`** — only `false`. That still proves the
CSP field names resolve (a wrong name degrades to nil and the key would be **omitted**; the keys
are present with a real boolean), but the **intervention flash was never seen firing**. Two
reasons it stayed out of reach this session:

1. `--driver ggv` is a **flat-out friction-circle optimal** driver — it may legitimately never
   lock a wheel or spin one, so ABS/TC may simply never engage.
2. The old side-channel attempts returned ~0 ticks during a drive. PR #595 removes that blindness
   by making the harness's own tap an `observer`; a future rig run should use that path plus a
   driver that deliberately provokes lock-up or wheelspin.

The **car-swap acceptance criterion is verified** in the table above. Separately, `acs.exe` died
in 2 of 5 historical runs; an immediate retry drove clean both times.

## Remaining on #531

Part D's **fuel-per-lap / laps-remaining / predicted-lap** fields are NOT in PR #590 — the
dash already computes burn client-side from lap boundaries (Phase-1 live-verified:
*18.4 laps left · 2.61 L/lap*), so that half is a separate non-overlapping change on the same
files. Then Parts E (shift cue + `audio_routing`), F (COACH/MAP/STINT depth + the I/M/O
spread this PR's STINT binding leaves for later), G (native-audio latency gate), H (SimHub
fusion, optional), I (mic upstream). Water/oil temp stays DATA-GATED.
