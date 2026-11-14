---
type: index
status: active
created: 2026-05-06
updated: 2026-05-06
scope: Assetto Corsa Competizione (ACC) — Steam app id 805550
relates_to:
  - 00_Graph_Schema.md
---

# Competizione (ACC) — sibling sim, file-first knowledge

This sub-tree lives in the same Obsidian vault as `AcCopilotTrainer/` but
covers a **different game**: Kunos's *Assetto Corsa Competizione* (ACC).

ACC is **not** classic Assetto Corsa. No CSP. No Lua. No Python apps.
Its mod surface is JSON config files in `Documents\Assetto Corsa
Competizione\` plus a small set of community-maintained external tools
(Race Element, ACC Manager, etc.). Setups, server configs, controls,
HUD, FFB, assists — all editable as JSON.

## Why this tree exists

Arseny installed ACC for online play (May 2026) on top of an existing
classic AC + CSP + MOZA R3 Base + SimHub stack. Goal: never reset a
control config in-game by hand again — drive everything from version-
controllable files.

## Sub-areas

- `03_Investigations/` — one-off research notes (file layouts, encodings,
  community practices, what is and isn't configurable from disk).

## First-load reading order

1. `03_Investigations/acc-config-files-and-moza-2026-05-06.md` —
   environment audit, file map, MOZA R3 Base recommendations, plan to
   pre-populate controls without using the in-game UI.
