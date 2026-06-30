# Racing Atelier — Design System

The brand and instrument language for **AC Copilot Trainer** (a.k.a. the **Game
Point** cockpit) — an in-sim driving coach for **Assetto Corsa**. It turns
telemetry into one decision a driver can read in a blink: *brake in 86 m, you're
14 km/h too hot, lift.*

> **Racing Atelier is the night register of Atelier.** It is the dark,
> instrument-grade sibling to the [Atelier](https://claude.ai/design/p/ccffb8e4-dd74-4ec1-8c2c-23438f41a246)
> house language (the warm, editorial system for "all things agentic"). It
> **inherits the discipline** — an authored token system, ruthless restraint, a
> named lexicon, instrument rigor — and **refuses the dress**: no serif, no
> italics, no hairline measures, no lowercase prose at the wheel. Carbon, not
> paper; data, not text; functionality and safety, not luxury.

> **One product, three surfaces.** The OLED rig screen, the in-game overlay, and
> the Windows launcher are the same instrument cluster, re-flowed.

```
Assetto Corsa + CSP Lua app
  → Python WebSocket sidecar (state hub)
      → ESP32 / OLED rig touchscreen (320×480, LVGL)
      → Windows Game Point launcher (Tkinter)
      → voice coach / haptics / SimHub
```

---

## Sources (provenance)

- **`uploads/15_Claude_Design_UI_Package.md`** — the written brief: screen
  inventory, states, copy rules, firmware token table
  (`firmware/screen/include/ui/tokens.h`).
- **`uploads/AC-Copilot-Claude-Design-Package.html`** — a reproduction of the
  original in-game HUD lifted from `src/ac_copilot_trainer/modules/hud.lua` &
  `coaching_overlay.lua`.
- **`uploads/In-game Coaching Trainer Design.make`** — the Figma Make project;
  the real Assetto Corsa cockpit screenshot is kept at `assets/hud-ingame.png`.
- **Atelier** (`claude.ai/design/p/ccffb8e4-…`) — the sibling house language this
  system is cut from. Read its `DESIGN_LANGUAGE.md` + `theme.css` for the shared
  philosophy; Racing Atelier diverges on palette and type (see below).
- Referenced, not provided (record for whoever has the repo): firmware
  (`firmware/screen/src/ui/`), launcher (`tools/rig_launcher/`), CSP Lua app
  (`src/ac_copilot_trainer/`), sidecar (`tools/ai_sidecar/`).

> **History:** an earlier gold/Porsche-themed pass was removed to avoid clutter.
> The Porsche pastiche is retired; Racing Atelier supersedes it entirely.

---

## Content fundamentals (voice & copy)

The product talks to a driver in a vibrating seat, gloved, mid-lap. Copy is an
**instrument readout**, not marketing.

- **One decision, sized to matter.** A surface carries a single action read
  large (BRAKE / LIFT / ON LINE); everything else recedes. Never a wall of text.
- **Imperative + magnitude.** "BRAKE" + `86 m`. "LIFT" + `+14`. The verb leads;
  the number is the only figure that matters.
- **Information, not sentences.** A coaching cue is a *shape* — a closing
  segment bar, a delta block — with one number, not prose. The driver parses
  geometry faster than grammar.
- **Casing carries role.** Tight bold **CAPS** (Saira Semi Condensed) for
  commands and labels — never spaced-out and thin. Big tabular numbers (Saira)
  for readouts. Mono (Spline Sans Mono) for units, ids, provenance.
- **State words are verbatim probe strings.** The launcher prints exactly what
  the supervisor reports: `healthy`, `waiting`, `absent`, `configured`,
  `stopped`, `on`. Never prettified.
- **No emoji. No exclamation. No filler.** Confidence is restraint + precision.
- **ASCII-safe on firmware** until the font bundle ships (`< BACK`, `+`, `-`).

---

## Visual foundations

**Mood.** A race-engineering instrument cluster at night. Carbon, machined
brass, vivid flat signal. High contrast, periphery-legible, calm until there's
something to do.

- **Colour = state, never decoration.** Brass = the house (structure, brackets,
  active). **Brake** red = danger / too hot. **Lift** amber = caution. **Clear**
  green = on line / healthy. Grey = labels and chrome. If a colour appears, it
  *means* something. (`tokens/colors.css`.)
- **Carbon, black-first.** `#0B0C0D` ground; on OLED, `#000` is the pixel
  switched off — deepest contrast, lowest draw. Build up from black.
- **Signal is flat and matte.** Vivid for safety, but **no glow, no gradient** —
  a warning lamp, not a neon sign. Colour fills *fields* (a red command, a green
  status) so peripheral vision catches it.
- **Type, engineered.** Saira Semi Condensed (commands, labels — tight bold
  caps), Saira (the big tabular readouts), Spline Sans Mono (units, ids). No
  serif, no italic — those read as editorial calm, fatal on a dash.
- **Magnitude is a count, not a position.** The shift-light **segment bar** and
  the **delta block** are chunky and gapped; the eye reads quantity of lit
  blocks at a glance. **Hairline scales are banned** for data — unreadable at
  speed.
- **Square corners.** `--r: 0`. Printed instrument, not "app" (shared with
  Atelier). The only round thing is a status dot.
- **Machined corner brackets** are the panel silhouette / house frame. Brass L's
  at the corners. The **seg-mark** (a short brass bar) precedes the wordmark.
- **Flat surfaces.** Carbon panels, edge borders, no drop shadows on UI bands.
  Device shells and the in-game glass overlay get presentational shadow/blur;
  the rig/OLED never does.
- **Motion is minimal.** State snaps; nothing decorative loops. Telemetry ticks
  at the 10 Hz snapshot cadence.

---

## Iconography

Near-iconless by design — instrument clarity over decoration.

- **The instrument elements are the "icons":** the segment bar, the delta block,
  the level cells, the corner bracket, the track map, the status dot/field.
  These are drawn (LVGL objects on firmware), not glyphs — they survive the
  font constraint and read at speed.
- **Typographic glyphs only** where a mark is needed: `›` (navigate), `‹ BACK`,
  `+` / `−` (steppers), `▼ ▲ ◀ ▶` (command direction arrows), `Δ` (delta).
- **No emoji. No icon font.** If a desktop surface ever needs an icon set, use a
  thin-stroke monochrome set tinted to the state colour, flagged as a
  substitution.
- **The brand mark** is the brass **seg-mark + RACING ATELIER** wordmark
  (`BrandMark`); `Game Point` / `AC Copilot` are product lockups in the same
  treatment.

---

## The Track Atlas data model

The Track Atlas (new surface) needs one dataset per circuit. Four ship:
**`data/spa.json`**, **`data/silverstone.json`**, **`data/laguna-seca.json`**,
**`data/magione.json`**; the in-game kit demonstrates all four with a selector.
Full per-element rationale is in **`ELEMENTS.md`**. Fields: `lengthKm`, `cornerCount`,
`climbM`, `drsZones`; a `map` (`viewBox`, `path`, `highlight`, `here`,
`markers`); an `elevation` polyline; the current `now` corner (`gear`,
`minSpeed`, `throttle`, `note`); a `next[]` queue; and a `keyCorners[]` index.
The geometry here is schematic — derive `path`/`here`/`elevation` from real
circuit data for production. **The shipped paths are hand-traced approximations,
not survey-accurate** — recognisable, but replace with real coordinates for a
production build.

---

## Index / manifest

**Root**
- `styles.css` — the entry point consumers link (only `@import`s).
- `tokens/` — `fonts.css`, `colors.css`, `typography.css`, `spacing.css`,
  `effects.css`, `brand.css`.
- `data/*.json` — Track Atlas datasets (spa · silverstone · laguna-seca · magione).
- `ELEMENTS.md` — package description: every element + the logic behind it.
- `assets/hud-ingame.png` — the real Assetto Corsa cockpit (reference).
- `guidelines/` — foundation specimen cards + `firmware-fonts.md` (LVGL).
- `concept/Racing-Atelier-Concept.html`, `concept/Racing-Atelier-Renders.html` —
  the direction board + render gallery.
- `SKILL.md` — Agent-Skill manifest for Claude Code.

**Components** (`window.ACCopilotDesignSystem_bba7a8.<Name>`)
- `components/core/` — **Button**, **Stepper**, **StatusField**, **Chip**,
  **Label**, **Panel** (square, `brackets`), **Toast**.
- `components/instrument/` — **CommandVerb**, **SegmentBar**, **DeltaBar**,
  **LevelSegments**, **StatusRow**, **SetupRow**, **NavTile**.
- `components/brand/` — **BrandMark** (+`SegMark`, `CornerBracket`).
- `components/track/` — **TrackMap**, **CornerNote**, **CornerLine**,
  **ElevationProfile**.

**Templates** (`templates/<slug>/` — consumer starting points)
- `ingame-hud/` · `rig-screen/` · `windows-launcher/` · `track-atlas/`.

**UI kits** (`ui_kits/<product>/index.html` — interactive recreations)
- `esp32_rig/` · `ingame_hud/` · `game_point/`.

**Foundations** — specimen cards in `guidelines/` populate the Design System tab
(groups: Brand, Colors, Type, Spacing).
