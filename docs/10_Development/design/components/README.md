# Claude Design — component cards (design-sync source)

Per-component preview cards for **Claude Design** (`claude.ai/design`). Each `*.html` is
self-contained (fonts via Google Fonts) and starts with a `<!-- @dsCard group="…" -->`
marker, so Claude Design indexes it into the Design System pane automatically.

The **in-game HUD is the north star** (`group="HUD"`, reproduced from
`src/ac_copilot_trainer/modules/hud.lua` + `coaching_overlay.lua`); the launcher and rig
screens are aligned to it.

```
foundations/  colors.html, type.html          # tokens + Michroma/Montserrat/Syncopate
hud/          active-suggestion.html, approach-panel.html
launcher/     healthy.html, recovery.html
rig/          ac-copilot.html, pocket-technician.html, settings.html, voice-haptics.html
```

## Push these into a Claude Design project (`/design-sync`)

Run from an **interactive** Claude Code session (or Claude Desktop with design login),
because the first sync needs a one-time design-access grant (`/design-login`):

```
/design-sync
```

Point it at this directory (`docs/10_Development/design/components`). It will:
`list_projects` → `create_project` (or target an existing **design-system** project) →
`finalize_plan` (you approve the exact file list) → `write_files` (uploads each card).
Sync is **incremental** — one component at a time, never a wholesale replace.

Alternatively, from Claude Design use **"Send to Claude Code Web"** to seed a project into
the workspace, then sync these cards up.

Keep the HUD cards in step with the Lua source first when the design changes — the HUD
leads, the other surfaces follow. Regenerate all cards with
`python .scratch/build_ds_components.py` (kept in scratch; promote to `tools/` if it earns a
permanent home).
