# Elements & logic — the Racing Atelier package

Why each element exists and how it behaves. The throughline: **the eye at speed
reads in periphery — mass, colour fields, and the count of lit blocks — not glyph
style or a thin tick's position.** Every element is built to be parsed in a
blink, with one decision dominant and everything else demoted.

---

## Core (`components/core/`)

- **Button** — the instrument action. Flat field, square, tight bold caps.
  `field` (raised) is the default; `primary` is the **single brass action** per
  surface (Start); `danger`/`ghost` for the rest. Press dims to 0.75. Logic: one
  loud action, so only one brass button competes for the eye.
- **StatusField** — state as a flat colour **field** + the verbatim word, or a
  **dot + word** inline. Colour carries meaning so peripheral vision catches it
  (green ready, red stopped). The launcher headline and connection states use it.
- **Stepper** — block −/+ for one parameter (brake bias, FOV). Big Saira value,
  square block buttons, an optional **fill bar** showing the value's position in
  range. Minus muted, plus brass. Logic: the value is the hero; the buttons are
  chunky 30px hit targets.
- **Chip** — compact mono data token (BB 54 · TC 2). Hairline square, tabular.
  Tone tints the outline for state. For dense setup metadata only.
- **Label** — the tight bold caps label (Saira Semi Condensed 600). **Never
  spaced-out and thin** — that reads editorial, fatal on a dash. Tones colour it
  for state.
- **Panel** — the carbon surface. Square, flat, edge border. `brackets` adds the
  machined brass corner L's (the house frame). `glass` is the in-game
  translucent variant — **web/desktop only, never on the ESP32** (no blur in
  LVGL).
- **Toast** — brief ack / failure. A flat field bar, state word + one line.

## Instrument (`components/instrument/`)

- **CommandVerb** — *the one action*, periphery-caught: huge Saira caps in a
  signal colour with an optional direction arrow. There is only ever **one** per
  surface, and it is the loudest thing on screen. Logic: found before it is read.
- **SegmentBar** — the **shift-light** magnitude bar. Chunky gapped segments read
  as a **count**, not a continuous slider. `fill` (0..1) rises toward a trailing
  red `zone`; the leading filled segment goes amber. Logic: replaces an
  unreadable hairline scale — the driver reads *how close* as quantity of lit
  blocks. (Computed in the component from `fill`/`count`/`zone`.)
- **DeltaBar** — the bidirectional pace block + big number. A thick block grows
  from a centre reference: right past `slack` = too fast (red), left = too slow
  (amber), centred = on line (green). Logic: direction **and** amount in one
  glance; the number is the only figure.
- **LevelSegments** — a small integer (TC 2, ABS 1) as lit cells, brass when on.
  The cockpit way to show a discrete level without reading a number first.
- **StatusRow** — one launcher line: tight-caps label · verbatim probe word
  (tone-coloured) · muted mono detail. Maps 1:1 to a `GamePointStatus` field.
- **SetupRow** — a saved setup: name · best-lap meta · chips. The loaded setup
  gets a brass left-marker + tinted band (state by position, not a badge).
- **NavTile** — an OLED launcher tile: Saira caps title, muted subtitle, brass
  chevron. 60px tap floor; pulses a brass border on press.

## Brand (`components/brand/`)

- **BrandMark** — the **seg-mark + wordmark** lockup (RACING ATELIER / Game
  Point / AC Copilot) in tight Saira caps. The single recognisable signature.
- **SegMark** — the brand atom: a short brass bar. Precedes a wordmark/section.
- **CornerBracket** — one machined brass L; four make the house frame (or use
  `Panel brackets`). The panel silhouette device.

## Track Atlas (`components/track/`)

A new surface: a circuit's *pace-note* drawn as instruments. Driven by one
dataset per track — schema + examples in `data/*.json`
(`spa`, `silverstone`, `laguna-seca`, `magione`).

- **TrackMap** — the schematic circuit from an SVG `path`, with an optional red
  `highlight` sub-path (the signature section), corner `markers`, a pulsing
  `here` position, and `labels`. **Geometry is data** — the paths shipped are
  hand-traced approximations; swap for survey-accurate coordinates for
  production.
- **CornerNote** — the *now-entering* pace note: the corner read large with
  gear / minimum speed / throttle as big tabular readouts + one coaching line.
  The Atlas's focal instrument.
- **CornerLine** — one row of the corner index (mono id · caps name · note).
- **ElevationProfile** — the climb as a polyline with the key crest marked. A
  nuance most dashes drop; for Spa/Laguna Seca the elevation *is* the character.

---

## The data model

`data/<circuit>.json` is the per-track contract the Track Atlas consumes:
`lengthKm · cornerCount · climbM · drsZones`; a `map` (`viewBox` · `path` ·
`highlight` · `here` · `markers` · `labels`); an `elevation` polyline; the
current `now` corner (`gear` · `minSpeed` · `throttle` · `note`); a `next[]`
queue; and a `keyCorners[]` index. Add a circuit by adding a file. The in-game
kit (`ui_kits/ingame_hud/`) demonstrates all four with a selector.

## State & motion logic

- **Colour = state, only.** Brass = house/structure. Brake red = danger/too-hot.
  Lift amber = caution. Clear green = on-line/healthy. If a colour shows, it
  means something. On the reference the frame goes near-mono — **loud only when
  there's something to do**.
- **One decision, sized to matter.** The action (CommandVerb / the brake
  distance) dominates; context (corner, gear, sector, lap) is demoted to mono
  micro-type. Position and size are *argued*, never default.
- **Motion snaps.** State changes are instant or a quick snap; telemetry ticks at
  the 10 Hz snapshot cadence; nothing decorative loops.
- **Square, flat, matte.** `--r: 0`. No glow on signal (a warning lamp, not
  neon), no drop shadow on UI bands (only device shells / in-game glass).
