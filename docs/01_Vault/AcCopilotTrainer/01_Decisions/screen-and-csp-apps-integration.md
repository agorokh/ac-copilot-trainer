---
type: decision
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/_index.md
---

# Rig screen ↔ Pocket Technician + Setup Exchange integration

## Context

Phase-2 of the rig touchscreen needs to drive **three** Lua surfaces:

1. **AC Copilot Trainer** — already connected via the `{v,type}` protocol
   on the sidecar (issue #81 / PR #83).
2. **Pocket Technician** (`x4fab`, v0.4.1) — live setup spinners.
3. **Setup Exchange** (`x4fab`, v1.5.6) — community setup browser.

CSP's per-app Lua VM isolation rules out direct cross-app calls. PT
exposes its functionality via stock CSP API (`ac.getSetupSpinners()` /
`ac.setSetupSpinnerValue()`); SX exposes its setups by writing files into
`UserSetups/<carID>/`.

## Decision

1. **Replicate, don't bridge.** Add `setup_control.lua` and
   `setup_loader.lua` modules in `src/ac_copilot_trainer/modules/`. They
   call the same CSP APIs PT and SX already call, exposed to the screen
   via our existing WS protocol. **PT and SX stay installed as user-facing
   apps** — they coexist with our touchscreen control, never replaced.

2. **Protocol additions** (still backward-compatible v1, additive types):

   | Direction | Type | Body |
   |---|---|---|
   | client → sidecar | `setup.spinner.list` | `{}` |
   | sidecar/Lua → client | `setup.spinner.snapshot` | `{ spinners: [{name,min,max,step,value,...}] }` |
   | client → sidecar | `setup.spinner.set` | `{ name, value }` |
   | sidecar/Lua → client | `setup.spinner.ack` | `{ name, applied, reason? }` |
   | client → sidecar | `setup.list` | `{}` |
   | sidecar/Lua → client | `setup.list.snapshot` | `{ setups: [{ track, name, path, mtime }] }` |
   | client → sidecar | `setup.load` | `{ path }` |
   | sidecar/Lua → client | `setup.load.ack` | `{ path, applied, reason? }` |

   These flow through the same hub fan-out the existing `action`/`config.set`
   already uses.

3. **Scrape parallel via the sidecar** (read-only):

   - Sidecar watches `<UserSetups>/<carID>/` for new files dropped by SX
     (debounced 250 ms) and broadcasts `state.snapshot { topic="setup.list",
     payload=[...] }`.
   - `<UserSetups>` resolves to whatever `ac.getFolder(ac.FolderID.UserSetups)`
     returns on this machine — Lua reports the path on first connect via
     a new `state.snapshot { topic="paths", payload={ userSetups, ... } }`.

4. **Three-tile screen layout** (Phase-2 SquareLine):

   - Tile 1: live spinner adjust (top-3 by use frequency: TC, ABS, brake
     bias). ± buttons, hold-to-repeat at 200 ms cadence.
   - Tile 2: setup library list (track-grouped), tap to load. Shows mtime
     so newly-downloaded SX setups are obvious.
   - Tile 3: trainer controls (toggles for `focusPractice`, racing-line
     mode, etc. — already wired via `action` in PR #83).

5. **No PT-style linked-spinner math in Phase-2.** Single-spinner edits
   only. Linked spinners (e.g. anti-roll bar pairs) are deferred to
   Phase-3 once the per-spinner UX is stable.

## Consequences

- We commit to running `ac.getSetupSpinners()` / `ac.setSetupSpinnerValue()`
  from our trainer's Lua. These are CSP-stable since at least patch 2578.
- The sidecar gains a directory-watch dependency (use `watchdog` or
  Python's `os.scandir` polling at 1 Hz — avoid asyncio file watchers on
  Windows).
- Never cache `min/max/step` across session or track changes — re-fetch
  on every spinner snapshot.
- Setup Exchange, when present, is the canonical *source* of setup files;
  we never download from `se.acstuff.club` directly until/unless option
  C below ships.
- Pocket Technician keeps its in-game window — users with a desk keyboard
  can still use it; rig users get our touch tile.

## Alternatives considered

- **Cooperative same-VM `require("PocketTechnician")`.** Rejected — CSP
  apps are per-VM isolated; not legal.
- **`ac.connect()` typed shared memory** as a fast Lua↔Lua channel.
  Rejected for v1 — adds CSP-version-specific struct schema; latency win
  not yet justified vs. our existing WS path.
- **HTTP proxy to `se.acstuff.club`** via the sidecar so the screen can
  browse setups without SX running. Recorded as future option **C**;
  out of scope until tile 1 + tile 2 ship.
- **Replace PT/SX entirely.** Rejected — both apps have richer UX than we
  intend to ship on a 480×320 panel; coexist, don't compete.

## Open questions

- Resolve `<UserSetups>` exact path on this PC (`Documents\Assetto Corsa\`
  is missing — likely under OneDrive or `%APPDATA%`).
- Latency budget for tap → spinner-set → ack: target < 50 ms LAN-side.
  Measure once tile 1 is wired.
- Hold-to-repeat cadence: 200 ms feels right but verify against PT's
  in-game spinner repeat rate.

## References

- Investigation: [`csp-app-pocket-tech-setup-exchange-2026-04-21`](../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md)
- Protocol base: [`external-ws-client-protocol-extension`](external-ws-client-protocol-extension.md)
- Screen UI: [`screen-ui-stack-lvgl-touch`](screen-ui-stack-lvgl-touch.md)
- Source repos: [PocketTechnician](https://github.com/ac-custom-shaders-patch/app-csp-defaults/tree/main/PocketTechnician), [SetupExchange](https://github.com/ac-custom-shaders-patch/app-csp-defaults/tree/main/SetupExchange)
