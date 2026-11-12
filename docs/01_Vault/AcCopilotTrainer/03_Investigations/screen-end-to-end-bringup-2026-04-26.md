---
type: investigation
status: active
created: 2026-04-26
updated: 2026-04-29
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
---

# Screen end-to-end bring-up — Parts C+D on real hardware (2026-04-26)

PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) Parts C+D first reached
the actual JC3248W535 device today. **Eight distinct root-cause bugs surfaced on the
path from "CI green" to "device shows live AC data + loads setups in-game"**, none of
which CI or static analysis could have caught. Capturing them here so future Phase-2
features (Setup Exchange, polish) skip the same traps.

## Symptom → root cause matrix

Roughly the order they hit during bring-up.

### 1. Windows pio link fails with `ar.exe: invalid option -- @`

The orchestrator that built C+D claimed this was "pre-existing Windows issue" and
moved on. It wasn't. Three layered Windows-toolchain bugs:

* **Binutils 2.31.1 in `toolchain-xtensa-esp32s3` predates `@response-file` for `ar`.**
  The xtensa `ar.exe` rejects `@file` syntax with `invalid option -- @`.
* The previous workaround in `firmware/screen/tools/long_cmd_fix_post.py` substituted
  `gcc-ar.exe` thinking that wrapper would expand `@file` first. **It doesn't** — gcc-ar
  is just a `--plugin=lto` shim that forwards every argv (including `@file`) to the
  inner ar.
* Removing TEMPFILE for AR alone exceeds Windows cmd.exe's 8191-char limit on the
  full LVGL archive (~10K chars).

**Fix** (committed): in `long_cmd_fix_post.py`, replace `ARCOM` with a Python
`subprocess.call` action that batches in chunks of 40 source files, plain
`xtensa-esp32s3-elf-ar.exe`, no shell — `CreateProcess` directly so cmd.exe's limit
doesn't apply. CC / CXX / LINK keep TEMPFILE wrapping (gcc/g++ honour `@file`).

Side-issue: the linker also reported undefined `lv_dropdown_*` because LVGL's
`lv_calendar_header_dropdown.c` references the dropdown widget unconditionally even
when `LV_USE_DROPDOWN=0`. Disabling `LV_USE_CALENDAR` (and 9 other unused extras)
in `lv_conf.h` resolves it. **The reusable lesson: every `LV_USE_*` we set to 0 risks
a transitive undefined-reference unless the entire dependent extra is also off.**

### 2. ArduinoWebsockets v0.5.3 leaks custom headers across reconnects

Symptom: device dials, sidecar rejects with `MultipleValuesError: 'X-AC-Copilot-Token'`
→ HTTP 500 → handshake fails. Each reconnect attempt added a *fresh* token header so
after ~3 retries the upgrade carried 3 copies.

Root cause: `WebsocketsClient::operator=` (websockets_client.cpp:48-79) copies
`_endpoint`, `_client`, callbacks — **but does NOT touch `_customHeaders`**. So the
firmware's per-connect pattern `ws = WebsocketsClient(); ws.addHeader(...)` never
cleared the previous attempt's headers and `addHeader` (which is `push_back`)
accumulated duplicates.

**Fix:** never reassign `ws`. Register callbacks + headers exactly once in
`ws_init_once()` at first connect; each subsequent attempt is just `ws.connect(url)`.

### 3. Sidecar's v1 envelope allow-list missing the new types

PR #91 added `setup.list` / `setup.load` / `setup.list.result` / `setup.load.ack`
to the firmware AND the trainer Lua, but **forgot the sidecar's
`CLIENT_TO_SERVER_TYPES` / `SERVER_TO_CLIENT_TYPES` allow-lists** in
`tools/ai_sidecar/server.py` (and `validate_inbound` in `external_protocol.py`).

`validate_inbound` rejected unknown types with `unknown type: 'setup.list'` →
sidecar replied with an error frame and never forwarded to the trainer. The PT
screen sat in `Loading...` forever.

**Fix:** add new TYPE constants in `external_protocol.py`, accept them in
`validate_inbound`, list them in both `CLIENT_TO_SERVER_TYPES` and
`SERVER_TO_CLIENT_TYPES`. **Architectural lesson:** any new external request/reply
type needs three sites updated — firmware dispatch, trainer Lua handler,
**and** sidecar allow-list. The sidecar shouldn't validate by type when its only
job is relay; consider migrating to a transparent forwarder for unknown types in a
follow-up.

### 4. `start_sidecar.bat` binds loopback-only

`src/ac_copilot_trainer/start_sidecar.bat` runs
`py -3 -m tools.ai_sidecar --host 127.0.0.1 --port 8765`. Without `--external-bind`,
the sidecar listens only on loopback — the device on `192.168.137.110` cannot
connect. **Documented but easy to miss.** Filed as TODO for a follow-up: bat needs
`--external-bind 0.0.0.0 --token <token>` plumbed via env var
(`AC_COPILOT_SIDECAR_TOKEN`) so the trainer's auto-spawn does the right thing
without manual sidecar launch.

### 5. CSP `web.socket` onOpen unreliable on first connect

The trainer Lua's `wsBridge.tryOpen` sent the v1 hello frame inline immediately
after `web.socket()` returned, then suppressed `onOpen`'s hello via a 1-second
dedup window. Empirically, the inline send fires while the TCP+WS upgrade is still
in progress; CSP's web.Socket buffers / drops the frame, no error visible.
`onOpen` then skips the hello believing the inline succeeded.

Result: the trainer's WS opened at the TCP/WS layer but **never registered as a
v1 peer**. The sidecar's `_external_peers` set only contained the device. The
trainer's `coaching.snapshot` frames had no fan-out target, and the device's
`setup.list` request had no loopback peer to forward to.

**Fix:** rely on `params.onOpen` only (the single signal CSP guarantees fires
when the socket is actually writable) AND add a tick-driven retry: every
`M.tick(simT)` while `sock` is open and `sidecarProtocolReady` is false, resend
the hello at most once per second. The sidecar's `_external_peers.add()` is
idempotent so duplicate hellos are no-ops.

### 6. Panel rotation: 4 distinct things must agree

The orchestrator's "rotation=1 in MADCTL gives landscape" assumption was wrong
on this exact panel. Empirical truth for this AXS15231B + JC3248W535:

| AXS15231B `rotation` | MADCTL bits   | Effect                                  |
|----------------------|---------------|-----------------------------------------|
| 0                    | MX \| MV \| RGB | landscape via MV transpose (the only one that displays anything sane on this board) |
| 1                    | MX \| MY \| RGB | black + single white scan line          |
| 2                    | MY \| MV \| RGB | (untested)                              |
| 3                    | RGB only      | black + single white scan line          |

Plus, four separate things need to agree on rotation:
1. **Panel MADCTL** — set in the AXS15231B ctor's `rotation=` arg via
   `Arduino_TFT::begin() → setRotation()`.
2. **Canvas dimensions** — `Arduino_Canvas(W, H, ...)`. The framebuffer is
   sized once at construction.
3. **Canvas `_width` / `_height`** — `Arduino_Canvas::setRotation()` only swaps
   these locally; it does NOT propagate to `_output`. Mismatch with the
   construction-time alloc → `draw16bitBeRGBBitmap` writes with rotated stride
   into a non-rotated framebuffer → diagonal-shear "pixelish" rendering.
4. **`Arduino_TFT::_max_x` / `_max_y`** — derived from the ctor's `w`/`h`, NOT
   from later `setRotation`. Passing native portrait `(320, 480)` and then
   relying on MV to display landscape clips `draw16bitRGBBitmap` calls of
   `WIDTH=480` to 320 cols — exactly the "doesn't fit in wideness, lower part is
   garbage lines" symptom.

**Fix** (committed): construct everything for the *displayed* layout from the
start. AXS15231B ctor with `rotation=0` (the only working MADCTL on this board)
+ Canvas at landscape dims `(480, 320)` so the framebuffer alloc matches
LVGL writes; OR — for the portrait device-mount we landed on — Canvas at
native `(320, 480)`. Never call `setRotation()` after construction.

### 7. Device mount is portrait, UI was coded landscape

The Figma reference at `agorokh/Ingamecoachingtrainerdesign/src/app/components/mobile/`
is **portrait phone** layout, but the orchestrator translated to LVGL with
`SCREEN_W=480, SCREEN_H=320` landscape. The user mounts the JC3248W535 in
**portrait** on the rig (iPhone-style). After fixing the rotation bugs above, the
launcher rendered cleanly but **rotated 90° in user-perceived orientation** —
the AC LAUNCHER header running vertically up the right edge.

**Fix:** flip every `SCREEN_W/H` in screen modules to `320/480` portrait,
restructure layouts that hard-coded landscape (e.g. AC Copilot's TARGET/CURRENT
two-column row → stacked), shrink the launcher status pill from 180→130 px so
it fits inside the narrower header without overlapping the brand label.

### 8. LVGL default Montserrat 14 doesn't include U+2014 em-dash

`format_lap_ms` returned `—` for empty values. The default-shipped Montserrat 14
font only covers ASCII 32-127, so 0x2014 rendered as a tofu placeholder — which
in PT's row layout is a small **gold rectangle** sitting where the lap time
should be. Looks like "0" or some glyph, mystifying.

**Fix:** swap every quoted em-dash fallback in screen `.cpp` files for ASCII
`-`. The proper fix is shipping the bundled Syncopate / Michroma / Montserrat
fonts via `lv_font_conv` — that's `Part A4`, deferred per the existing README.

## Other discoveries

### CSP API names for human-readable car/track

* `ac.getCarName(0)` and `ac.getCarUIData(0)` are NOT exposed on the user's CSP
  build. Returned `nil`. This silently fell back to the directory ID.
* The deterministic answer is to read AC's `ui_car.json` / `ui_track.json` files
  directly: `<AC root>/content/cars/<carID>/ui/ui_car.json` has
  `{name: "Porsche 911 GT3 R 2016", brand: "Porsche", class: "race"}`.
* Resolving `<AC root>` from Lua: try `ac.FolderID.Root` / `ACRoot` / `ACMain`;
  `ac.FolderID.ContentCars` / `ContentTracks` work on some builds. Falling back
  through them all is robust. Negative-cache results so we don't reread per row.

This is committed as `src/ac_copilot_trainer/modules/ac_content_meta.lua`.

### AC setup INI section names (confirmed against real files)

The orchestrator's first extractor used `[BASIC] BRAKE_BIAS=...` / `[ELECTRONICS]
ABS=...` — that's not the AC convention. Verified canonical form across
`ks_porsche_911_gt3_r_2016`, `bmw_m3_gt2`:

```
[FRONT_BIAS] VALUE=66       -- brake bias (front bias %)
[ABS] VALUE=7               -- ABS level
[TRACTION_CONTROL] VALUE=3
[WING_1] VALUE=2            -- front wing / splitter
[WING_2] VALUE=20           -- rear wing
[FUEL] VALUE=25
[TYRES] VALUE=1             -- compound index
```

Each setting lives in its **own section** with key `VALUE`. Useful for any
future "summary chips" / "compare two setups" feature.

### Hotspot auto-flip-off

Windows Mobile Hotspot's "Power saving" feature toggles itself off after the
hotspot has been idle. With AC running and the trainer publishing 10Hz,
the feature shouldn't fire — but observed twice during this bring-up. Worth
documenting in the rig setup runbook: turn off Power Saving in Mobile hotspot
settings.

### Sandbox can't toggle Mobile Hotspot

For interactive bring-up sessions: Claude's PowerShell sandbox blocks
`NetworkOperatorTetheringManager.StartTetheringAsync()` as a host-level network
change. The user has to flip the toggle manually. Worth surfacing this early in
any "device won't connect" troubleshooting flow.

## Known follow-up

**BB chip stale across setups** — TC and ABS update correctly when switching
between setups in the PT list (verified `bb=66 / bb=57` payloads in the trainer
log, both arrive at the device). The rendered BB chip on at least one row was
observed not updating between taps. Diagnostic logs confirm the trainer side
sends correct values. Either a per-row LVGL label cache or an FW
parsing edge case for the specific JSON shape — not yet root-caused.

**Tracking:** filed as GitHub issue [#93](https://github.com/agorokh/ac-copilot-trainer/issues/93) (Part-D polish); the rest of the chips work.

## Files changed

* `firmware/screen/tools/long_cmd_fix_post.py` — batched `subprocess.call` AR
* `firmware/screen/include/lv_conf.h` — disable extras pulling in dropdown
* `firmware/screen/src/main.cpp` — `ws_init_once`, portrait dims, identity
  dispatch with brand
* `firmware/screen/include/board/JC3248W535_GFX.h` + `_Touch.h` — rotation 0
  ctor, native portrait Canvas, identity touch mapping
* `firmware/screen/src/ui/{screen_launcher, screen_ac_copilot,
  screen_pocket_technician}.cpp` — portrait layouts, em-dash → hyphen, brand
  line, setup chips, ACTIVE row
* `tools/ai_sidecar/{external_protocol, server}.py` — Part D type allow-list,
  hello + relay logging
* `src/ac_copilot_trainer/modules/ws_bridge.lua` — onOpen-only hello +
  tick-driven retry
* `src/ac_copilot_trainer/modules/setup_library.lua` — per-track filter,
  display-name plumbing, INI summary extractor
* `src/ac_copilot_trainer/modules/csp_helpers.lua` — `carDisplayName` /
  `trackDisplayName` helpers (best-effort, fall through to `ac_content_meta`)
* `src/ac_copilot_trainer/modules/ac_content_meta.lua` — NEW: ui_*.json reader
* `src/ac_copilot_trainer/ac_copilot_trainer.lua` — `setup.list` handler now
  returns `car_brand`, `car_class`, `track_country`, per-row summaries

## Acknowledgement

A non-trivial portion of "the rotation is fine, the orchestrator already covered
that" turned out to be load-bearing on assumptions that don't hold for this
specific physical panel. Everything in this note was verified against the
actual hardware in a single session.
