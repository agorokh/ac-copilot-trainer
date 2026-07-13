# Tablet GT dashboard — design spec (v3 "glance spine + stable boards")

**Status:** design-frozen, implementation-pending (rig PC). **Issue:** [#531](https://github.com/agorokh/ac-copilot-trainer/issues/531).
**Reference mock:** [`reference_mock.html`](reference_mock.html) — pixel-faithful, interactive (Car / Coach-lane / Page toggles). Open it; it *is* the spec made concrete.
**Provenance:** 11-agent design council (research + 3 competing designs + judge synthesis) + gemini/mistral. Research files: `.scratch/design2/*.md`. This doc is the durable distillation.

---

## 1. What this is

A **GT race dashboard first**, for a 7″ tablet permanently mounted on the rig, in the club's **Racing Atelier** design language. It is a **modal** surface — you sweep between pages:

`STINT ◀ · RACE (home) · COACH ▶ · MAP`

**RACE** is the default and the calibre bar is a real GT3 wheel display (Porsche 992 GT3 R class). **COACH** is the post-lap debrief. **MAP** is the spatial/pace-note page. **STINT** is tyres+fuel+strategy detail. The hero (shift ribbon + gear + delta) and the electronics/tyres boards are never swept away; only the *detail* pages change.

**The point is coaching** — teaching the operator to drive. So coaching is woven into RACE (not bolted on): the live delta is the always-on coaching instrument, a quiet next-corner lane sits under it, and it repaints in place to a BRAKE takeover in the braking zone. Voice leads; the visual lane confirms.

### The three hard requirements this design solves
- **(a) Car-adaptive electronics** — TC/ABS/MAP shown *with the car's real range and presence* (`TC 6/12`, not `TC 6`). A car with no ABS greys the tile. Ranges are read live per car — never hardcoded. See §5.
- **(b) Setup-aware** — brake bias, TC, ABS, MAP, compound come from the **loaded setup**; the **setup name** + car + track headline the top. See §4, §5.
- **(c) Rig-adapted** — USB transport, Allwinner-A133 performance ceiling (DOM/CSS only, no WebGL/blur, ≤15 Hz), 1024×600 landscape, glanceable at the wheel. See §7.

---

## 2. Architecture — the sidecar is the single data plane

The tablet is **one more `browser`-class WebSocket peer** of the existing sidecar, over the proven **USB `adb reverse tcp:8765`** path (no WiFi — mesh cross-AP TCP is blocked on this rig). The sidecar already fans every produced frame to all external peers; the tablet subscribes and renders. **SimHub is not required for the data plane** — our own WS contract can drive the whole RACE page (§6). SimHub stays available but the tablet dashboard is *our* surface, not the generic SimHub skin.

```
AC ─► CSP Lua trainer ─► sidecar (WS hub, :8765)
                              │  coaching.snapshot / coaching.cue / coaching.voice
                              │  telemetry_tick / delta / tire_temps / setup.active
                              │  setup.spinner.list.result  ← per-car ranges (the "/max" fix)
                              ▼
        sidecar HTTP+WS ──(adb reverse, USB)──► tablet Fully Kiosk ◄─ our Racing-Atelier HTML
```

Connect exactly like `tools/ai_sidecar/voice/web/tablet_voice.html`:
```js
ws.send(JSON.stringify({ v:1, type:"hello", client:"tablet-dash", client_class:"browser" }));
ws.send(JSON.stringify({ v:1, type:"state.subscribe",
  topics:["coaching.snapshot","coaching.cue","coaching.voice","telemetry_tick","delta","tire_temps","setup.active"] }));
ws.send(JSON.stringify({ v:1, type:"setup.spinner.list" })); // request per-car ranges
```
Loopback (adb reverse) is **untokened**. `hello`-before-anything and the `KNOWN_TOPICS` allow-list are hard gates (a topic produced but not listed is unsubscribable).

---

## 3. Page model

| Page | Role | Consumed |
|---|---|---|
| **RACE** (home) | full GT dashboard + woven coaching | at speed |
| **COACH** | post-lap debrief: reference-vs-you, per-phase delta, biggest opportunity, brake-mark calibration | stopped / on straights |
| **MAP** | circuit + live position + sector/delta + pace-note queue | glance |
| **STINT** | tyres (I/M/O + wear) + fuel/energy plan + pit window + trends | glance / pit |

Pages are **swept** (a wheel button cycles them); the header carries a 4-dot page indicator. Switching is a plain show/hide — **no layout ever resizes** (the A133 rule).

---

## 4. RACE page — layout (1024×600, exact)

Device 1024×600, **2px border + 8px/12px padding** → usable **996×580**. Five stacked bands; **no region ever resizes**; every band has `overflow:hidden` so nothing can spill into a neighbour. Vertical budget sums with slack (the v2 bug was forgetting the 2px border → 4px overflow).

```
┌ 1024×600 ─────────────────────────────────────────────────────────────────────┐
│ A  SETUP HEADER  (h34)  ▍ ENDURO·LONG-RUN  911 GT3 R — MAGIONE   DRY 26/45° ● LIVE ○●○○ │
│ B  SHIFT RIBBON  (h34, +6)  ████████▌ green→amber→red ............ 6789 / 8500  │
│ C  GLANCE BODY   (h300, +6) ─────────────────────────────────────────────────  │
│    ┌ LEFT 210 ─────┐  ┌ CENTRE 552 ───────────┐  ┌ RIGHT 210 ────────────┐      │
│    │ ENGINE (quiet)│  │        187 km/h        │  │ P3 · L6/28            │      │
│    │  oil/water    │  │           4  (gear156) │  │ CUR / LAST / BEST /   │      │
│    │  °C · bar     │  │                        │  │ PRED                  │      │
│    │ ───────────── │  │  Δ −0.125 ◀██│░░▶ bar  │  │ ───────────────────   │      │
│    │ FUEL 18.4 laps│  │  (speed→gear→DELTA)    │  │ STINT +1.4 lap · gaps │      │
│    └───────────────┘  └────────────────────────┘  └───────────────────────┘     │
│ D  COACH LANE    (h56, +6, repaints in place)                                   │
│    cruise:  NEXT ▸ LESMO 2·T5 · 3rd·min118      BRAKE 5 M LATER·T4   T6·T7       │
│    braking: BRAKE ▸  ███▌░ (to marker)  42 m   prev T3·LATE   TC● ABS○           │
│ E  SETUP·ELECTRONICS (left 600) │ TYRES (right 386)  (h120, +6)                  │
│    BRAKE BIAS 54.5% F◀▍▶R │ TC 6/12 │ TC CUT 4/12 │ ABS 3/12  │ FL84°27.6 FR86°..│
│    (▓ brass fill/count)                                        │ RL88°.. RR92°.. │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Band C columns:** 210 + 552 + 210 (gaps 14). **Band E columns:** 600 + 386 (gap 14). **Centre spine (300h):** SPEED 50 → **GEAR ~156** (single largest glyph) → **DELTA ~94** (DeltaBar + signed number).

### Importance hierarchy (argued, not defaulted)
- **HERO:** gear (biggest glyph) + speed satellite + **delta welded under gear** (the delta is the coaching spine, co-hero).
- **PRIMARY / full-width:** shift ribbon, setup header.
- **SIGNATURE / permanent boards:** setup·electronics (left of band E) + tyres (right).
- **PERIPHERAL, colour-only-when-it-matters:** engine vitals (near-mono, colour only out-of-range), fuel-as-laps, timing, light stint strategy, the coach lane when silent.
- **Deleted vs v2:** duplicate rpm/MAP/DRY/throttle renders, clutch pedal, boost tile on NA cars, the "AC Copilot" vanity wordmark.

### Band detail
- **A · Setup header (h34):** brass SegMark + **SETUP NAME** (Saira SC 700 ~19px) · `car — track` (mute) · DRY/WET StatusField · air/track temp mono · ● LIVE dot · 4-dot page indicator. **Composed client-side** by joining `setup.active`(name) + `setup.list.result`(car/track/electronics chips) + `telemetry_tick`(weather/temps) — `setup.active` alone carries only the name.
- **B · Shift ribbon (h34):** full-width SegmentBar, chunky gapped cells green→amber→red, leading lit cell amber, **rpm-banded from the car's live `rpm_max`** (never hardcoded), full-bar flash at redline, doubles as flashing pit-limiter box. `rpm / redline` mono right-aligned inside. The ONE rpm representation.
- **C · Glance body:** LEFT = ENGINE (quiet StatusRow strip, colour only out-of-range) + FUEL (laps-remaining big, litres small — a decision not a count). CENTRE = SPEED→GEAR→DELTA spine. RIGHT = timing (P/lap, cur/last/best/pred) + a **light** strategy nod (fuel-to-flag margin + gaps).
- **D · Coach lane (h56):** repaints in place (§8).
- **E · Setup·electronics + tyres (h120):** electronics tiles (§5) + 2×2 thermal tyre cells (core temp + pressure over a compound-window colour field; full I/M/O + wear on STINT).

---

## 5. Car-adaptive electronics contract (the key engineering payload)

**Rule:** the current VALUE is the loud figure; the MAX is always present but demoted; position-in-range is a preattentive block count; colour is **brass (structure)** — never a signal colour — *unless* the electronic is intervening right now.

### 5.1 Data source (verified in codebase — nothing new to invent)
- `ac.getSetupSpinners()` is normalized to `{name,label,value,min,max,step,unit,items}` per knob in `src/ac_copilot_trainer/.../setup_library.lua` (~`:748-899`) and published as WS **`setup.spinner.list.result`**, **relayed sidecar↔tablet both ways** (`tools/ai_sidecar/server.py` ~`:343-402`; the ESP32 screen already consumes this exact shape).
- **Denominator (the "/max"):** `steps = ((max − min) / step) + 1`. Display value/steps.
- **Proof the hardcode is wrong** (checked-in 911 GT3 R schema `assets/setups/_schema/ks_porsche_911_gt3_r_2016/*.json`): `ABS 0..11`, `TC 0..11`, `FRONT_BIAS 50..70`, **no engine-map spinner**. So this car renders `ABS n/12`, `TC n/12`, bias `%`, and **no MAP tile**. Never trust a hardcoded `/12`.
- Semantic accessors exist in `tools/ai_sidecar/setup_model.py` (`brake_bias_pct`, `abs_level`, `tc_level`, `compound_index`, …).

### 5.2 Discrete tile (TC, TC CUT, ABS, MAP) — 3 lines, identical rhythm across tiles
1. **Label** — disambiguated (`TC`, `TC CUT` not the opaque `TC-2`, `ABS`, `MAP`), Saira SC 600 ~10px tight caps `--dim`.
2. **Value / max** — `6`/`12`: value Saira 700 ~30px `--chalk`; `/12` Spline Mono ~13px `--mute`. **`/max` never omitted.**
3. **LevelSegments** — a `.bar` row (fixed 12px height so all tile bars align) containing N cells where **cell count = the max**; cells 1..value filled **brass**, rest `--raise`. Bar *length* encodes the range preattentively (< 250 ms: "half-way up a tall scale" vs "maxed on a short scale").

### 5.3 Continuous tile — BRAKE BIAS (a centre-anchored lean bar, echoing DeltaBar)
- Value `54.5%` Saira 700 hero. Below it, a `.bar` row: `F` | bar | `R` inline, **baseline-aligned with the segment bars**. The bar has a **centre tick (neutral 50%)** and a **brass marker + fill** offset from centre by the front-lean: `lean = value − 50; markerPct = clamp(6..94, 50 − lean/20·50)` (front → left toward F). `FRONT_BIAS` is already a % in AC; the spinner min..max only sets scale extents.

### 5.4 Presence + fallbacks (car-adaptive correctness)
- **Absent spinner → tile omitted / greyed** (GT2/GTE with no ABS → greyed `ABS —` / `NOT FITTED`; tiles reflow to fill). **Value 0 → `ABS OFF`**, never `ABS 0/0`.
- **No turbo → no boost tile** (kills the v2 NA-car "boost 0.9" bug). **No engine-map spinner → no MAP tile.**
- **MAP resolves its NAME when available** (`MAP 3/8 · QUALI`) — "MAP N" is semantically overloaded per car.
- **No range exposed → show the value with a mono `?` and no bar. Never invent a range.**
- Levels are 0-indexed; `value+1 / max+1` display is a UI convention (confirm per game/car on the rig MFD).
- **ACC differs:** `Graphics.{TC, TCCut, ABS, EngineMap}` give live values but no max/count → a per-car table is needed (Ferrari/McLaren 12 maps, Porsche 10, Audi/Aston/Lambo/Honda 8; `EngineMap+1` on the raw page). AC path (setup spinners) is the primary; ACC is a documented follow-on.
- **Live-intervention flash (the one legal signal colour on these tiles):** when TC cuts / ABS modulates, briefly flash the lit segments amber/red — mirroring the real 911 side-LEDs — separating "what I dialled" (brass, steady) from "what the car is doing" (signal, transient). Needs `tc_active`/`abs_active` live flags (slot exists, producer doesn't fill yet → degrade to steady brass).

---

## 6. Vitals data plane — HAVE vs NEW vs data-gated

| Vital | Source | Status |
|---|---|---|
| rpm, gear, speed, throttle/brake/steer, lat/long-G | `telemetry_tick` (`telemetry_publisher.lua`) | **HAVE** |
| live **delta** | `delta` topic 10 Hz (`delta.lua`) — **we compute it** | **HAVE** |
| tyre **core** temps | `tire_temps` | **HAVE** |
| fuel litres + capacity, lap/best/valid, session | telemetry / session topics | **HAVE** |
| electronics **ranges** (the `/max`) | `setup.spinner.list.result` | **HAVE** |
| setup name + car/track (header) | `setup.active` + `setup.list.result` | **HAVE** |
| coaching (brake point, corner approach, cues, voice) | `coaching.snapshot` / `coaching.cue` / `coaching.voice` | **HAVE** |
| **`rpm_max`** (shift-ribbon redline) | `car.rpmLimiter` — already read for the in-game HUD | **NEW (S)** — add to `telemetry_tick` |
| **`tc_active` / `abs_active`** (intervention flash) | producer slot exists, unfilled | **NEW (S)** |
| live tyre **pressures / brake-temps / wear** | captured to lap trace, not streamed | **NEW (S)** — add to live tick |
| clean **fuel-per-lap / laps-remaining / predicted-lap** | computed sidecar-side (inside a cue detail) | **NEW (S)** — surface as fields |
| engine **water / oil temp** | **absent from base-AC shared memory** (SimHub can't supply either) | **DATA-GATED** — source via CSP extended physics per car, or omit; never placeholder |
| reference-lap trace + predictive delta (COACH page) | confirm the sidecar emits its own reference (not a removed SimHub path) | **VERIFY** |

**"NEW (S)"** = small Lua-producer/validator additions, no new architecture. The RACE page can be driven **today** from HAVE + the shift-ribbon needing only `rpm_max`.

---

## 7. Rig / A133 constraints

- **Transport:** USB `adb reverse tcp:8765` (WS+page). No WiFi. Fully Kiosk Browser is the render host (kiosk lockdown, keep-screen-on-while-charging, launch-on-boot).
- **Perf:** DOM/CSS only. **No WebGL, no `backdrop-filter`/blur, no `box-shadow`, no CSS `filter`, no `mix-blend-mode`.** `translate3d` for any motion. Throttle WS→DOM writes to ≤10–15 Hz; batch. If Phase-2 pulls SimHub vitals via the bridge, **downsample vitals to 2–5 Hz**; keep `coaching.*` on the 10–20 Hz priority loop (dual-rate).
- **Offline kiosk:** vendor **Saira Semi Condensed / Saira / Spline Sans Mono** + any framework locally — no CDN (the mock uses the CDN for convenience only).
- **Resolution:** design at **1024×600 landscape** (confirm; a 1920×1200 P7 variant exists).

---

## 8. Coaching integration (three-tier attention budget)

- **Tier 1 (always-on):** the centre **DeltaBar** is the glance-free "am I on line". Silence-of-colour = "you're fine".
- **Tier 2 (default coach lane, quiet, near-mono):** `NEXT ▸ <corner>·<id>` + target gear + min-speed (CornerNote, rally-timed on approach) + **at most one** CommandVerb-lite micro-cue, prescriptive/quantified/phase-scoped (`BRAKE 5 M LATER · T4`), blank when nothing to say.
- **Tier 3 (braking-zone takeover, in place):** the lane repaints (never resizes) to `BRAKE ▶` CommandVerb + a brake-point SegmentBar counting to the marker + previous-corner one-word verdict + live TC/ABS pips (suppressed on cars without the system). Collapses at corner exit. **Exactly one live imperative** (CommandVerb one-per-surface). Auto-suppresses to delta + pace-note in traffic/battle. **Voice leads, the lane confirms** (A133 native-audio latency unverified — see #511 Part D; the visual must be able to lead).
- **COACH page** is the debrief the live lane withholds: reference-vs-you trace, per-phase (brake/entry/apex/exit) delta split, the single biggest opportunity, priorities ranked by time lost, per-corner brake-mark calibration.

---

## 9. Design tokens + components (Racing Atelier)

Source of truth: `docs/10_Development/design/racing-atelier/project/tokens/*`. **Derive; do not hand-copy hex** (the #432 drift pitfall).

- **Colour:** carbon `--carbon #0B0C0D`, panel `--graphite #141618`, trough `--raise #20242A`, border `--edge #2A2F35`. Signal (state only): `--brake #F23B2C`, `--lift #F4A52C`, `--clear #2FBE6E`, `--data #49B6C9`. House accent `--brass #C8983E`. Ink `--chalk #EEF1F3` / `--mute #9BA1A8` / `--dim #79808A`.
- **Type:** `--fd` Saira Semi Condensed (display/commands/labels), `--fr` Saira (tabular readouts), `--fm` Spline Sans Mono (units/ids). **Not Michroma** (that's the retired gold pass).
- **Geometry:** square corners (`--r 0`); flat/matte, no glow; brass corner brackets (2px, 14px arms); chunky segment bars (26px, 3px gap); bidirectional delta block.
- **Components used:** CommandVerb (one per surface), SegmentBar (count, not slider), DeltaBar (bidirectional), LevelSegments (electronics), CornerNote, StatusRow/StatusField, Panel (flat `variant=panel`, **not** glass on the A133).

---

## 10. Reference mock — how to read it

[`reference_mock.html`](reference_mock.html) is a self-contained, DOM/CSS-only implementation of the RACE/COACH/MAP/STINT pages at true 1024×600. It renders every token, component, and state faithfully and is the coding agent's ground truth. Toggles:
- **Car** (911 GT3 R ↔ M3 GT2): watch the electronics board reflow — ranges change (`TC 6/12` → `TC 3/8`), **ABS greys to "NOT FITTED"** on the no-ABS car, engine values change, redline changes, and the braking-lane ABS pip suppresses.
- **Coach lane** (Cruise ↔ Braking zone): the in-place repaint.
- **Page** (Stint / Race / Coach / Map): the sweep.

The mock hardcodes illustrative telemetry; production binds the same DOM to the WS topics in §6 and the spinner ranges in §5.

---

## 11. Open questions — verify on the rig before/while building

1. **Levels 0- vs 1-indexed** per game/car (display `value+1`?) — check the in-sim MFD.
2. **`rpm_max`, `tc_active`/`abs_active`, live pressures/brake-temps/wear, fuel-per-lap** — confirm which the Lua producer actually sends vs the validator merely accepts.
3. **Engine map spinner** presence is car-dependent (911 has none) — MAP tile hides.
4. **Water/oil temp** — source via CSP extended physics per car, or omit (never placeholder).
5. **Reference-lap + predictive delta** — confirm the sidecar emits its own (not a removed SimHub path).
6. **P7 resolution/orientation** (1024×600 vs 1920×1200 variant).
7. **ACC per-car level tables** if ACC support is added.
8. **Native-audio latency** on the A133 (#511 Part D) — decides whether the tablet can ever own critical cues; PC WASAPI stays authoritative until measured < 450 ms.

---

## 12. See also
- Issue [#531](https://github.com/agorokh/ac-copilot-trainer/issues/531) — the implementation order.
- Research: `.scratch/design2/{gt3-real-dashboards,sim-dashboard-bestpractice,car-adaptive-electronics,codebase-setup-electronics,codebase-telemetry-vitals,coaching-in-dash-ux,realestate-layout-critique}.md`.
- Racing Atelier package: `docs/10_Development/design/racing-atelier/project/`.
- Tablet transport + audio: `docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-511-partd-tablet-voice-endpoint-2026-07-11.md`, `.../01_Decisions/usb-serial-screen-transport-2026-07-02.md`.
