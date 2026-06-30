# Racing Atelier — visual targets (comparison gate)

PNGs rendered from the **current** Racing Atelier ui_kits, for **visually comparing** an
implemented surface against the design. **Authoritative source is the package itself**
([`../racing-atelier/project/`](../racing-atelier/project/) — tokens, templates, ui_kits,
guidelines); these images are the gate, not the spec. Regenerate with headless Chrome from
`../racing-atelier/project/ui_kits/*/index.html`.

> Do **not** use `../racing-atelier/project/templates/{rig-screen,windows-launcher}/.thumbnail`
> — those two are stale (retired gold/Porsche pass). The renders here come from the ui_kits.

## Asset map

| PNG | Surface | Compare against (real surface) | Owning issue |
|---|---|---|---|
| `esp32_rig.png` | ESP32 rig 320×480 (AC Copilot brake-zone · Setups · Track Atlas tabs) | photo/capture of the rig screen | [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) |
| `ingame_hud.png` | In-game CSP Lua HUD overlay | in-game HUD capture | [#400](https://github.com/agorokh/ac-copilot-trainer/issues/400) Part B |
| `game_point.png` | Windows Game Point launcher (status rows + brackets) | screenshot of the Tk launcher window | #400 Part C |
| `concept_renders.png` | Render gallery (all surfaces) | — (orientation) | #400 / #401 |

Also in the package: `../racing-atelier/project/assets/hud-ingame.png` (the **real** Assetto
Corsa cockpit reference photo) and per-surface `templates/*/InGameHud.dc.html` etc.

## The comparison gate (mandatory for any UI PR)

1. **Capture the real surface** in the matching state (rig photo / in-game HUD capture / launcher screenshot).
2. **Put it next to the target PNG** here AND check it against `../racing-atelier/project/tokens/colors.css`.
3. **Verify, concretely:** carbon ground `#0B0C0D`/OLED-black; **brass `#C8983E`** house mark (not gold); flat-matte signal **brake `#F23B2C`** / **lift `#F4A52C`** / **clear `#2FBE6E`** / **data `#49B6C9`** (no glow); **square corners** + brass corner-brackets; **Saira / Saira Semi Condensed / Spline Sans Mono**; segment bars + delta blocks (count, not hairline scales).
4. **Attach both images to the PR.** A green code diff is not visual verification.
