---
type: investigation
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Pocket Technician + Setup Exchange (CSP apps) — surface for our screen

## Install location

Both shipped via `app-csp-defaults`, by [x4fab](https://github.com/ac-custom-shaders-patch/app-csp-defaults).

- `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\PocketTechnician\PocketTechnician.lua` (262 lines, v0.4.1)
- `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\SetupExchange\SetupExchange.lua` (1058 lines, v1.5.6)

`Documents\Assetto Corsa\` is **not** present on this PC; AC's user-data
folder is somewhere else (probably under `OneDrive\Documents\Assetto Corsa\`
or `%APPDATA%\Assetto Corsa\`). Verify before scraping any state files.

## Lua VM isolation matters

CSP apps run in **separate Lua VMs**. Our `ac_copilot_trainer.lua` cannot
`require()` PT/SX modules directly — they aren't in our `package.path`,
and even if they were, their globals don't cross VMs. The only legal
cross-app channels are:

- **CSP API itself** (`ac.*`, `io.*`, `web.*`) — every app sees the same AC
  state.
- **Filesystem** — setup `.ini` files, JSON state, `ac.storage` backing files.
- **`ac.connect()` shared memory** — typed C-struct shared between any apps
  that pre-agree on the layout.
- **HTTP** — both apps talk to internet endpoints.

## Pocket Technician — what it does and how

Tweaks the live setup mid-session. Author x4fab. `LAZY = FULL` (unloads on
window close). Single Lua file, no shared library deps.

Key API calls observed:

- `ac.INIConfig.carData(0, 'setup.ini')` — current car's setup file.
- `ac.getSetupSpinners()` — **returns the list of {name, min, max, step,
  value, ...} for every spinner the current car exposes.**
- `ac.setSetupSpinnerValue(name, newValue)` — **the setter we want.** Drives
  the same path as the in-game Setup window.
- `ac.saveCurrentSetup(file)` / `ac.loadSetup(file)` — round-trip.
- `ac.isCarResetAllowed()` — gate (PT closes its window if false).
- `ac.onSetupsListRefresh(cb)` — re-scan event.
- `io.scanDir(ac.getFolder(ac.FolderID.UserSetups)..'/'..ac.getCarID(0))` —
  enumerate user setups for the current car.

**Critical insight:** PT's whole feature set is just a thin UI wrapper over
`ac.getSetupSpinners()` + `ac.setSetupSpinnerValue()`. **Our trainer Lua
VM has the same API.** We can replicate (and surface to the touchscreen)
without depending on PT being installed or running.

## Setup Exchange — what it does and how

Cloud setup browser/uploader. Author x4fab. `LAZY = 2`. Endpoint:

```lua
-- SetupExchange/Config.lua
return { endpoint = 'http://se.acstuff.club' }
```

Key behaviours:

- Auth: `web.request('POST', endpoint..'/session', ...)` with
  `userID = sha256('LB83XurHhTPhpmTc' .. ac.uniqueMachineKeyAsync(...))` —
  per-machine identity, no login.
- Per-session header signing via `ac.encodeBase64`. Includes carName,
  trackID, trackName.
- Downloads land in `ac.getFolder(ac.FolderID.UserSetups)..'/'..carID..'/'..name`
  via `io.save(filename, data); ac.refreshSetups()`.
- Persisted state via `ac.storage{...}` (table form — note this CSP fork
  apparently *does* support it for SX, in contrast to our experience with
  `AC_Copilot_Trainer` where the table form silently fails — see
  `ac-storage-persistence.md`).
- Temp files: `ac.getFolder(ac.FolderID.AppDataLocal)..'/Temp/ac-se-shared.ini'`
  and `ac-se-backup.ini`.

## Integration paths for our rig screen

Two architectural options, not mutually exclusive:

### A. Same-VM replica (our trainer Lua does the work)

Add to `src/ac_copilot_trainer/modules/`:

- `setup_control.lua` — wraps `ac.getSetupSpinners()` /
  `ac.setSetupSpinnerValue()`. Exposes via `ws_bridge` config.get/set or
  new `setup.spinner.list` / `setup.spinner.set` actions.
- `setup_loader.lua` — scans `UserSetups/<carID>/` directory, exposes
  list via WS `setup.list`; `ac.loadSetup(path)` on a `setup.load` action.

**Pros:** zero new processes, no inter-VM coordination, runs even if PT/SX
windows are closed (LAZY=2/FULL).
**Cons:** we re-implement PT's spinner UX rules (linked spinners, ranges).

### B. Read-only scrape via the sidecar (Python)

Sidecar watches:

- `Documents\Assetto Corsa\setups\<car>\` (or AppData equivalent) for new
  files dropped by SX.
- Exports a `setup.list_changed` snapshot to all WS clients.

**Pros:** zero CSP changes; lets the screen subscribe to setup-list updates
that the actual SX app produces.
**Cons:** read-only — can't drive PT/SX from the screen this way.

### C. (Future) HTTP proxy to se.acstuff.club via sidecar

Have the sidecar mirror SE's REST endpoints so the screen can browse +
download setups even when SX itself isn't open. Stretch goal — not in
scope until A is solid.

## Recommended first build (Phase-2 integration)

1. **Same-VM `setup_control.lua`** + new `{v:1, type:"setup.spinner.list"}` /
   `{v:1, type:"setup.spinner.set"}` messages. This is the highest-value
   integration: rig screen becomes a touch remote for car setup spinners.
2. Sidecar **directory watch on `UserSetups/<carID>/`** with debounce, fanned
   as `state.snapshot { topic="setup.list", payload=[...] }`.
3. Screen UI shows: top-3 spinners as ±buttons (TC, ABS, brake bias);
   second tile screen for full setup list.
4. PT / SX **stay installed**; we coexist, not compete. Document the design
   so users know our screen tile and PT's window can both be open.
5. **Risk:** SE upgrade or a new spinner naming convention could break our
   value-clamping. Cap fallback: read `min/max/step` per call, never cache
   them across session/track changes.

## Open questions (tag for next session)

- Where exactly is `Documents\Assetto Corsa\` on this PC? Need to confirm
  before the directory watch.
- Does `ac.connect()` give us a faster channel than WS for live spinner
  changes? (Latency budget: <50 ms tap-to-feedback.)
- PT's "linked spinner" math (lerp formula on line 90-ish of
  PocketTechnician.lua) — port verbatim or simplify?
