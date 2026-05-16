---
type: investigation
status: active
created: 2026-05-06
updated: 2026-05-06
scope: ACC v1.x on Windows, Steam build, MOZA R3 Base wheelbase
relates_to:
  - Competizione/_index.md
sources:
  - https://www.assettocorsa.net/forum/index.php?faq/assetto-corsa-competizione-general-troubleshooting.32/
  - https://www.acc-wiki.info/wiki/Mods_and_Tweaks
  - https://mozaracing.com/blogs/blog/moza-settings-guide-for-assetto-corsa
  - https://simracingsetup.com/product-guides/acc-moza-force-feedback-settings/
  - https://support.mozaracing.com/en/support/solutions/articles/70000627983-assetto-corsa-ac-assetto-corsa-competizione-acc-
  - https://www.trophi.ai/post/assetto-corsa-competizione-ffb-setup-guide
  - https://steamcommunity.com/app/805550/discussions/0/3712684644824906822/
  - https://www.overtake.gg/downloads/acc-g29-controls-json.26804/
---

# ACC config files + MOZA R3 Base — file-first audit and plan

## Goal

Configure ACC the way we configure classic AC: **from disk, in version
control, reproducibly**. No manual re-bind sessions in the in-game
controls UI on every reinstall or hardware change. Specifically: keybinds,
TC / TC2 / ABS / engine map / brake bias rotaries (where applicable),
FFB chain, assists, HUD, realism flags.

## Environment (probed locally, not assumed)

| Item | Value | Source |
|------|-------|--------|
| OS | Windows 11 | Desktop Commander listings |
| ACC user folder | `C:\Users\arsen\OneDrive\Documents\Assetto Corsa Competizione\` | folder probe |
| Documents redirected to OneDrive? | **Yes** — `%USERPROFILE%\Documents` is empty; OneDrive owns it | folder probe |
| Wheelbase (live, in `controls.json`) | **MOZA R3 Base** (5.5 Nm class) | controls.json line 11 |
| Wheel-attached rim | None reported as a separate `commandDevices` entry | controls.json |
| Pedals | Same device — no separate pedal device entry | controls.json |
| Device GUID | `{679F6460-E7C8-11F0-8001-444553540000}` — **machine-specific, do not copy across PCs** | controls.json |
| Product ID | `341102-0-0-00807368867368` | controls.json |
| MOZA Pit House | Installed (shortcut on desktop, `Documents\MOZA Pit House\` exists) | folder probe |
| Other relevant stacks present | classic AC, iRacing, CrewChiefV4, SimHub, RaceLabApps | OneDrive\Documents listing |
| Game launched at least once | Yes — `Config/`, `Customs/`, `Replay/`, `Results/`, `Savegames/`, `MoTeC/` all populated | folder probe |
| Existing custom controls preset in `Customs\Controls\` | **None** (folder empty) | folder probe |

## File map — what is where, and what each file controls

All paths under `C:\Users\arsen\OneDrive\Documents\Assetto Corsa Competizione\`.

### `Config\` — active runtime state

These are the live config files ACC reads on startup and writes on exit.

| File | Purpose | Edit risk |
|------|---------|-----------|
| `controls.json` | The **active** wheel/pedal binding, FFB gains, steer lock. Sourced from `Customs\Controls\<name>.json` when one is loaded; otherwise auto-populated. | Medium — invalid JSON makes ACC re-create a default; backups mandatory. |
| `ffbUserSettings.json` | Per-car FFB gain overrides (`mapCarUserGain`). Tiny file. | Low. |
| `assists.json` | Driving assists (TC, ABS, auto-clutch, ideal line, gearbox, virtual mirror, etc.). | Medium — see encoding note below. |
| `hud.json` | HUD safezone, default page, widget visibility. | Low. |
| `realism.json` | Cockpit camera, mirror behaviour, force-cockpit-view, etc. | Low. |
| `cameraSettings.json`, `cameraDev.json`, `cameraoptionsea.json` | Camera positions, FOV, look-with-wheel. | Low. |
| `menuSettings.json`, `saveSettings.json` | Last-used menu state. | Low — game overwrites freely. |
| `nameplateSettings.json` | Nameplate visibility, transparency, tag style. | Low. |
| `replay.json`, `ghostcar.json`, `broadcasting.json` | Replay buffer size, ghost car opacity, broadcast SDK port (default 9000). | Low (broadcasting port matters for Race Element / SimHub). |
| `account.json` | Steam account-bound state. | **Do not edit / do not commit.** |
| `moduleenabler.json` | Audio / spotter / online-services toggles. **Not a "Lua app enabler"** — ACC has no app system like classic AC. | Low. |
| `ksonmatchmakingparameters.json`, `champState.json`, `seasonEntity.json`, `weatherStatus.json`, `weatherData.json`, `trackStatus.json` | Online matchmaking and last-session state. | Low — game owns these. |

### `Customs\Controls\` — saved control profiles

Each `.json` here is a **named, loadable** copy of `controls.json` that
shows up in the in-game `Options → Controls → LOAD/SAVE` menu. **This is
our canonical edit surface** — we save a profile in-game once, then edit
that file, then reload it. The active `Config\controls.json` is replaced
when a profile is loaded.

Currently: **empty**. Step 1 of the plan (below) creates the first one.

### `Customs\Cars\`, `Customs\Liveries\`, `Customs\Drivers\`

Custom liveries (`exampleCar.json`), custom skin templates, driver
profiles (name, helmet, suit, gloves). Three default driver slots already
present (`driver1.json`, `driver2.json`, `driver3.json`).

### `Setups\<carId>\<trackId>\`

Per-car / per-track car setups. JSON. **Does not exist yet** for any
car/track combo — gets created the first time you save a setup in-game
on that combo. Community setup repos (e.g. `Lon3035/ACC_Setups` on
GitHub) are designed to be cloned straight into this directory.

### `MoTeC\Workspaces\`

ACC writes telemetry to MoTeC i2 format. `base_ACC` workspace already
exists. Out of scope for this note.

### Out-of-tree paths

- `%LOCALAPPDATA%\AC2\Saved\Logs\` — crash + warning logs. **First place
  to look** when ACC misbehaves; the official Kunos FAQ instructs users
  to zip the entire `Logs` folder for any bug report.
- `%LOCALAPPDATA%\AC2\Saved\Crashes\` — crash dumps.

## File encoding — the trap that bites every JSON editor

Different ACC files use **different encodings**. Save the wrong one and
ACC silently rejects it (game generates a fresh default, your edits
vanish or — worse — controls reset).

Empirical observation on this machine:

| File | Encoding |
|------|----------|
| `Config\controls.json` | **UTF-8** (no BOM) — pretty-printed with tabs |
| `Config\ffbUserSettings.json` | UTF-8 |
| `Config\hud.json`, `moduleenabler.json` | UTF-8 |
| `Config\assists.json` | **Binary on read** — almost certainly **UTF-16 LE with BOM** |

The official ACC Server Admin Handbook (v1.10.x) is explicit: server
configs must be UTF-16 LE; using UTF-8 silently misreads. Client-side
files inherit the same engine code, so any file generated as UTF-16
must be re-saved as UTF-16. The Kunos forum and Race Department repeat
the rule: open ACC JSONs only in editors that preserve their original
encoding (Notepad++, VS Code with encoding indicator, etc.) — Microsoft
Word and similar break them.

**Operating rule:** before editing any ACC JSON, check its first 2 bytes.
`FF FE` = UTF-16 LE BOM, save back as UTF-16 LE. Otherwise UTF-8.

A small Python helper (per-file `open(path, 'rb')` + sniff BOM, then
`json.loads` with the right `decode()`, then write back through the
same encoding) is the safe edit path. **Never** hand-edit `assists.json`
or any other UTF-16 file in vanilla Notepad.

## Current state of `controls.json` on this machine

The auto-generated defaults are **partial**. What is bound:

- **Axes** (good): `Steer = axisIndex 0`, `Gas = 2`, `Brake = 5`. No
  combined pedals (`combinedPedals: 0`), no inversion shenanigans.
- **UI navigation**: Forward/Backward, Up/Down/Left/Right.
- **Race essentials present**: IgnitionSequenceOn, Starter, PitLimiter,
  GearUp, GearDown, DisplayPageUp, DisplayPageDown, CycleCamera,
  LookLeft / LookRight / LookBack, EnableFlashingLights.
- **One assist control bound**: `IncreaseABS` only.

What is **missing** vs a typical GT3-ready binding:

- `DecreaseABS` — there's only Increase right now, so the value can
  monotonically rise but never come back down without a reset.
- `IncreaseTC` / `DecreaseTC`
- `IncreaseTC2` / `DecreaseTC2` (= "TC Cut" on most GT3s)
- `IncreaseEngineMap` / `DecreaseEngineMap`
- `IncreaseBrakeBias` / `DecreaseBrakeBias` ← **race-critical**
- `Wiper`, `HeadlightsHighBeam`, `HeadlightsFlash`
- `RaceEngineerActivation` / `PitTalkActivation`

These are all standard ACC `instantActionCode` enum values — community
controls.json packs (G29, G27 packs on Race Department / OverTake) show
the spelling exactly.

### FFB chain currently in `controls.json`

```
forceFeedbackGain: 1.0   (= 100% in-game)
steerScale: 1
steerLock: 1080          (degrees — ACC will scale per-car internally)
dynamicDamping: 1
steerLinearity: 1
roadEffects: 0
minDamper: 0
damperGain: 1
antaniGain: 1            (= "Slip" effect in ACC's UI)
minimumForceFeedback: 0
brakeGamma: 1
combinedPedals: 0
```

`enableManufacturerExtras: true` at the top level — this is the toggle
that lets ACC drive Fanatec/MOZA wheel rim LEDs/displays directly via
the manufacturer SDK. Keep on for MOZA dash output.

## Community best-practices: the FFB chain (MOZA R3 Base in ACC)

The wheel feel for any direct-drive base in ACC is **two-stage** and the
order matters. Tune Pit House first, then ACC, **never the reverse**.

### Stage 1 — MOZA Pit House (driver-level)

The community consensus across MOZA's own ACC guide, simracingsetup.com
(updated Jan 2026), and the MOZA support knowledge base for AC/ACC:

| Setting | Value (R3 / R5 entry-level class) | Why |
|---------|-----------------------------------|-----|
| Maximum Steering Angle | 900° (GT/road), 540° if formula | GT3 cars in ACC use ~480–520° internal lock; 900° gives ACC headroom to soft-lock per car. |
| Game FFB Intensity | **100%** | Don't pre-attenuate at the driver. Cut clipping in-game, not here, on a 5.5 Nm base. |
| Maximum Output Torque | 100% | Same reason — preserve dynamic range on a low-torque base. |
| Road Sensitivity | 8 (R3/R5 class) | More than 8 amplifies grain noise without adding signal. |
| Maximum Wheel Speed | 120% | Lets countersteer keep up. |
| Wheel Spring Strength | **0%** | ACC supplies its own self-aligning torque from physics. Adding spring = mush. |
| Wheel Damper | 50–60% | Smooths jolts; raise toward 70% if street cars feel too jittery. |
| Natural Inertia | 140% (R3/R5) | Adds mechanical-feeling weight without sluggishness. |
| Wheel Friction | 25% (R3/R5) | Subtle resistance, no notch. |
| Speed-Dependent Damping | ~20% activating around 90 km/h | Suppresses high-speed oscillation common on GT3s. |
| FFB Equalizer (10/15/25/40/50 Hz) | 130 / 140 / 150 / 160 / 170 % | Restores detail bands the R3's lower torque tends to mask. |

The community's hard rule, repeated by experienced MOZA owners: **never
attenuate at both Pit House *and* in-game** — that double-cuts your
dynamic range and introduces FFB clipping flat-spots. Pit House at 100%,
then trim in-game.

### Stage 2 — ACC in-game FFB (Options → Controls → Force Feedback)

The trophi.ai guide and simracingsetup's per-base recommendations
converge on roughly:

| ACC Setting | R3 Base value | Notes |
|-------------|---------------|-------|
| Gain | 70–85% | Start 75%. Increase until you feel clipping (wheel goes flat under heavy load over kerbs), then back off 5%. There is **no in-game clip indicator** in ACC — use Race Element's FFB monitor or Pit House's clipping graph. |
| Filter | 0% | Adds latency for no benefit on DD. |
| Minimum Force | 0% | Only relevant for belt/gear wheels. |
| Kerb Effect | 15% | More than 30% drowns the underlying physics. |
| Road Effect | 10–15% | Surface texture. |
| Slip Effect (`antaniGain` in JSON) | 5–10% | Tyre slip cue. Higher (~30) is the convention in classic AC, **not** ACC — ACC's tyre model already pushes slip through main FFB; layering a strong slip effect causes notchy feedback. |
| ABS Effect | 0% | The pedal vibration cue. R3 doesn't have force-cell pedals; the cue is wasted. |
| Dynamic Damping | 100% | Speed-scales a damping floor. |
| Steering Sensitivity | Linear (1.0) | Match the car's actual rack. |

### Stage 3 — Wheel rotation / soft lock

ACC's per-car wheel rack is **fixed** in the physics engine. The
`steerLock` field in `controls.json` (1080 here) is what ACC tells the
wheel base to clamp to. Rule:

- Set Pit House Maximum Steering Angle ≥ ACC `steerLock`.
- ACC will internally soft-lock to the car's actual rack each time you
  enter a car (e.g. Porsche 991 GT3 R = ~480°, McLaren GT4 ~ 580°).
- If the in-game wheel ever rebounds suddenly at the lock, **MOZA
  support's documented fix** is: turn Pit House's hardware soft-lock
  off. ACC's soft-lock and MOZA's soft-lock fight if both are enabled.

## What can be configured purely from disk vs what needs in-game touch

| Configurable from disk alone | Needs in-game step at least once |
|------------------------------|----------------------------------|
| **Button → action** mappings (once `instanceGuid` is known for the device) | Initial discovery of `productName` / `instanceGuid` for any new HID device — ACC writes this on first detect. |
| Axis ranges, inversion, combined-pedals flag, brake gamma | First-time **axis identification** (which axisIndex is throttle vs brake — ACC asks you to press each pedal). |
| FFB gains, steerLock, all the FFB filters | None. |
| Assists (`assists.json`) | None — but watch the UTF-16 encoding. |
| HUD layout (`hud.json`) | HUD position dragging is in-game; `hud.json` only stores the result. |
| Realism flags (`realism.json`) | None. |
| Loading a saved controls profile | Yes — `Customs\Controls\<name>.json` only takes effect after `Options → Controls → LOAD/SAVE → LOAD`. We **cannot** swap the profile silently while ACC is running; it gets cached at load time. |

So the pragmatic split is:

1. **In-game, once:** plug in everything, run ACC's first-time control
   detection, save the result with a name like `Arseny_R3_Base_v1`.
2. **From files thereafter:** edit `Customs\Controls\Arseny_R3_Base_v1.json`,
   reload it from the menu. No more clicking through 30 button-bind dialogs.

## Risks and gotchas (collected from primary sources)

1. **OneDrive lock.** Kunos's official troubleshooting tells users to
   exclude `Documents\Assetto Corsa Competizione` from any cloud-sync
   tool (OneDrive, Google Drive, Dropbox). On this machine the folder
   *is* under OneDrive. If we hit unexplained crash-on-launch or
   "controls reset themselves" later, the first thing to test is
   pausing OneDrive sync on that folder.
2. **Hidden-folder flag.** Same FAQ: the entire `Documents\Assetto Corsa
   Competizione` tree must be visible (not Hidden) or ACC crashes on
   startup with a `secure crt: invalid` error.
3. **Antivirus interference.** Whitelist the ACC executable and the
   user folder; multiple posts attribute "controls won't save" to AV
   blocking writes to `Documents`.
4. **Corsair iCue conflict.** Documented by Kunos: iCue intercepts HID
   init and stops ACC from seeing the wheel. Disable iCue if the wheel
   doesn't appear in ACC after MOZA Pit House confirms it works.
5. **GUID-bound buttons.** `instanceGuid` is per-machine — never copy a
   `controls.json` from another PC verbatim and expect bindings to
   bind. The portable thing to share is the *button-index → action*
   mapping; the device identity must be filled in from the local
   `controls.json` ACC just generated.
6. **Notepad ≠ safe editor.** Anything that re-saves a UTF-16 file as
   UTF-8 (or vice versa) bricks that file. Use VS Code with the encoding
   shown in the status bar, Notepad++, or a script that explicitly
   preserves encoding.
7. **No "force-bind from outside" while ACC is running.** ACC reads
   `Config\controls.json` once at boot. Edits during a session are
   ignored until next launch.

## Plan — file-first ACC bring-up

### Phase 0 — backup (mandatory before any edit)

`tools/acc_backup.ps1` (to write): `Copy-Item -Recurse -Force
"$env:OneDrive\Documents\Assetto Corsa Competizione" "$repo\backups\acc\$(Get-Date -Format yyyyMMdd_HHmmss)"`.
Run before every disk edit. Cheap insurance.

### Phase 1 — capture a real baseline from the live game

1. Plug everything in (wheelbase, any rim if used, pedals, button box,
   handbrake if any). Make sure Pit House sees it all.
2. Launch ACC once. Go `Options → Controls`. Even if everything looks
   right, force a `LOAD/SAVE → SAVE` with the name **`Arseny_R3_Base_v1`**.
3. Quit ACC.
4. `Customs\Controls\Arseny_R3_Base_v1.json` now exists with the
   correct `productName`, `productId`, `instanceGuid`. **This file is
   the canonical edit target from now on.**
5. Commit it (in a fresh repo or sub-tree).

### Phase 2 — fill the gaps from disk

With the baseline file captured, write a Python helper that:

1. Reads `Customs\Controls\Arseny_R3_Base_v1.json` (UTF-8 sniff).
2. Validates the existing button list, finds free button indices.
3. Adds the missing race-critical `instantActionCode` entries listed
   above (DecreaseABS, IncreaseTC/DecreaseTC, IncreaseTC2/DecreaseTC2,
   IncreaseBrakeBias/DecreaseBrakeBias, IncreaseEngineMap/DecreaseEngineMap,
   Wiper, HeadlightsHighBeam, RaceEngineerActivation, PitTalkActivation).
4. Writes back preserving formatting and UTF-8 encoding.
5. Saves a side-by-side diff into `vault/Competizione/03_Investigations/`.

Then in ACC: `LOAD` the profile again. Walk one lap, verify the new
buttons fire the right action.

### Phase 3 — port FFB recommendations

1. In Pit House, apply the R3-class settings from this note (or load
   the equivalent Pit House profile if MOZA's site has one for ACC —
   the `bin\GameConfigs\` directory inside Pit House is what auto-loads
   per-game).
2. Edit `Customs\Controls\Arseny_R3_Base_v1.json` (still our canonical
   profile) so the FFB block matches:
   - `forceFeedbackGain: 0.75` (= 75%)
   - `roadEffects: 0.10`
   - `antaniGain: 0.10`
   - `damperGain: 1.0`
   - `dynamicDamping: 1.0`
   - `minimumForceFeedback: 0`
   - `steerLock: 1080`
3. Reload the profile in-game.

### Phase 4 — assists, HUD, realism (encoding-safe edits)

1. Run the encoding sniffer over each `Config\*.json` and produce a
   manifest mapping path → encoding. Persist that manifest at
   `tools/acc/file_encodings.json`.
2. Edit `assists.json`, `hud.json`, `realism.json` through the helper
   that respects per-file encoding. Suggested baseline:
   - `assists.json`: TC = ON (driver-set), ABS = ON (driver-set),
     stability = OFF, ideal line = OFF, auto-clutch = OFF for race,
     auto-blip = OFF, gearbox = H or sequential per car, virtual
     mirror = ON.
   - `realism.json`: cockpit camera enforced, wheel rotation matches
     wheel = ON.
3. Reboot ACC, validate.

### Phase 5 — bring it under git

Mirror `Customs\Controls\Arseny_R3_Base_v1.json` (and a sanitized
no-GUID template) into the repo at `tools/acc/profiles/`. The local
copy stays under OneDrive (so ACC reads it); the repo copy is the
truth. A small sync script keeps them in lockstep.

## Open questions / next research

1. **Confirm assists.json encoding** definitively — is it always UTF-16
   LE BOM, or only when the file holds a Unicode driver name? Need a
   tiny Python sniffer to write to disk before any human edits.
2. **Race Element vs ACC Manager vs SimHub** — which of these does
   Arseny actually want as a daily driver for runtime overlays/setup
   browsing/post-session analysis? Race Element has the strongest ACC
   integration; SimHub is already on this machine for AC. Pick one for
   ACC and document the integration shape (broadcasting port, shared
   memory, etc.).
3. **MOZA dash output.** Does the R3 Base setup include a dash module
   (CRP1, RM HD, KS-style rim with screen)? If yes, MOZA Pit House's
   dashboard system reads ACC's shared memory directly — no game-side
   plugin needed (unlike classic AC, which uses the Python app at
   `apps/python/Moza`). Confirm vs hardware list.
4. **Setup library.** The community standard is the
   `Lon3035/ACC_Setups` GitHub repo cloned into
   `Setups\<carId>\<trackId>`. Decide whether to consume that wholesale
   or curate.

## TL;DR for the next agent picking this up

- ACC is JSON-on-disk all the way down; controls / FFB / assists / HUD
  are all editable from files **except** initial axis identification.
- The trap is encoding: some ACC JSONs are UTF-8, some are UTF-16 LE
  BOM. Sniff before write.
- The right edit target for controls is **a named profile under
  `Customs\Controls\`**, not the active `Config\controls.json`. Save
  once in-game with a memorable name, then live in that file forever.
- The MOZA R3 Base FFB recipe is: Pit House at 100% torque + community
  R3/R5 advanced values; ACC in-game gain ~75% with low effect filters.
- OneDrive owns this machine's `Documents\` — keep an eye on sync
  conflicts and consider exclusion if controls "drift".
