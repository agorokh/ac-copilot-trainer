---
name: racing-atelier-design
description: Use this skill to generate well-branded interfaces and assets for Racing Atelier — the dark, instrument-grade design language for AC Copilot Trainer / the Game Point cockpit (an Assetto Corsa in-sim driving coach). The night register of the Atelier house system. Contains tokens, fonts, components, UI kits and templates for the OLED rig screen, the in-game overlay, the Windows launcher, and the Track Atlas.
user-invocable: true
---

Read the `readme.md` file within this skill first, then explore the other files.

If creating visual artifacts (slides, mocks, throwaway prototypes), copy assets out and create static HTML files for the user to view. If working on production code (LVGL firmware, the Tkinter launcher, the CSP Lua HUD), copy assets and read the rules here to become an expert in this brand.

If the user invokes this skill without other guidance, ask what they want to build, ask a few questions, and act as an expert designer who outputs HTML artifacts _or_ production code.

## Where things are
- `readme.md` — the full guide: context, sources, voice, visual foundations, iconography, the Track Atlas data model, and a file index. **Read first.**
- `styles.css` — single CSS entry point (link it; it `@import`s every token + font file).
- `tokens/` — colors, typography, spacing, effects, brand, fonts.
- `components/` — React primitives: `core/`, `instrument/`, `brand/`, `track/`. Each has a `.d.ts` (props contract) and a shared card per directory.
- `templates/` — starting points (`ingame-hud`, `rig-screen`, `windows-launcher`, `track-atlas`).
- `ui_kits/` — interactive recreations (`esp32_rig`, `ingame_hud`, `game_point`).
- `data/spa.json` — Track Atlas dataset schema + example.
- `guidelines/` — foundation cards + `firmware-fonts.md` (TTF → LVGL).

## House rules (don't break these)
- **Night register of Atelier.** Inherit the discipline (authored tokens, restraint, named lexicon, instrument rigor); refuse the dress (no serif, no italic, no hairline data scales, no lowercase prose at the wheel).
- **Colour = state.** Brass = house · brake red = danger/too-hot · lift amber = caution · clear green = on-line/healthy. Flat & matte, never glowing.
- **Carbon, black-first.** `#0B0C0D` ground; `#000` on OLED = pixel off.
- **Type:** Saira Semi Condensed (commands/labels, tight bold caps), Saira (tabular readouts), Spline Sans Mono (units/ids). No serif, no italic.
- **Magnitude is a count, not a position:** shift-light segment bars + chunky delta blocks. Hairline data scales are banned — unreadable at speed.
- **Square corners (`--r: 0`).** Machined brass corner brackets + the seg-mark are the brand devices.
- **One decision per surface, sized to matter.** Information design, not text.
- **Ergonomics:** ESP32 is 320×480 portrait, 60px tap floor; keep connection/telemetry status visible.
