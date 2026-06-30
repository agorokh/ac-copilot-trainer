# Design — canonical source

**The design language of record is [`racing-atelier/`](racing-atelier/)** — the *Racing
Atelier* handoff bundle exported from Claude Design (the dark, instrument-grade cockpit
system for AC Copilot Trainer / Game Point). Brand: **RACING ATELIER**; product footer
lockup: **AC COPILOT**. An earlier gold / "AG Porsche Academy" pass is **retired and
removed** — Racing Atelier supersedes it entirely (see `racing-atelier/project/readme.md`).

## Where things are (read the source — it's authoritative)

- **`racing-atelier/project/tokens/`** — canonical tokens: `colors.css`, `typography.css`,
  `fonts.css`, `spacing.css`, `effects.css`, `brand.css`. `styles.css` is the entry point.
- **`racing-atelier/project/templates/`** — per-surface starting points: `ingame-hud`,
  `rig-screen`, `windows-launcher`, `track-atlas`.
- **`racing-atelier/project/ui_kits/`** — interactive recreations: `esp32_rig`,
  `ingame_hud`, `game_point`.
- **`racing-atelier/project/components/`** — React primitives (core / instrument / brand / track).
- **`racing-atelier/project/guidelines/firmware-fonts.md`** — Saira → LVGL (`lv_font_conv`).
- **`racing-atelier/project/SKILL.md` / `readme.md`** — how to consume the system.

> The package README says: read the source (tokens + templates + ui_kits); don't rely on
> screenshots. The `racing-atelier-renders/` PNGs below exist only as a **visual-comparison
> gate** because we explicitly want UI work checked against a picture, not shipped blind.

## Visual targets

[`racing-atelier-renders/`](racing-atelier-renders/) — PNGs rendered from the **current**
ui_kits (`esp32_rig`, `ingame_hud`, `game_point`) + the concept gallery, plus the map +
comparison gate in its `README.md`. Use these (not the package's `templates/*/.thumbnail`,
two of which are stale from the retired pass).

## Owning issues

- [#400](https://github.com/agorokh/ac-copilot-trainer/issues/400) — apply the design
  language across HUD + launcher + shared tokens.
- [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) — rig firmware (LVGL).
