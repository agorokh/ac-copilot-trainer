---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-18
updated: 2026-10-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-native-se-live-readback-2026-10-17.md
  - AcCopilotTrainer/03_Investigations/issue-627-stable-ac-chain-2026-10-18.md
---

# #86 rig screen: long setup names and the empty Setup Exchange (2026-10-18)

Operator on the glass: Pocket Technician names "overlapping severely" with BB/ABS/TC and
"not readable to a human"; Setup Exchange "loading … nothing for this track" at Magione.

## Causes (all reproduced in the native simulator with the operator's real rows first)

- **LVGL `LONG_DOT` needs a bounded height.** With width fixed and height automatic, a label
  wraps downward instead of truncating, and LVGL breaks lines at `_`. The scientist names
  (`Copilot_Scientist_<16 hex>_<16 hex>`, 51 chars) stacked three lines over the chip line.
  The same latent bug sat in the ACTIVE, live-car, track and spinner labels.
- **Names were cut to 47 chars without dots.** The row cache held `name[48]`, requests `[64]`,
  so the load request and the trainer's ack carried different strings.
- **The simulator never had a long name.** Its only Pocket Technician row was "Simulator
  baseline" (two short words), so 61 green assertions proved nothing about real names.
- Setup Exchange was correct but uninformative: Magione + 911 GT3 R genuinely has 0 setups.

## Fix — PR #891 (`54801e6`)

Rows measure the name (`lv_txt_get_size`): up to two lines beside the best-lap readout, chips
below, the row grows; short names keep the 68 px row. One `PT_SETUP_NAME_MAX` (96). One-line
heights on single-line labels. Empty search: "No community setups for this car at <track> yet."

## Evidence

Simulator 127 assertions (was 61), including two-line max, no overlap, distinguishable names,
full-name load request, one-line ACTIVE above LIVE CAR. Flashed with
`PLATFORMIO_UPLOAD_PORT=COM6 pio run -e jc3248w535_serial -t upload` from the primary checkout
(real secret headers; the pre-upload gate re-ran the simulator fresh), hash verified. **Operator
confirmed on the glass**: names readable with BB/ABS/TC below; the Magione message shows.

## Lessons

- Seed simulator scenarios with real operator data (names, lengths, character sets), not
  placeholders — the operator called this out directly.
- `PLATFORMIO_UPLOAD_PORT` must be pinned: the MOZA base is also a USB serial device (COM3).
- A worktree has no `secrets/*.h`; compile-check with the `.example` headers, but flash only
  from the primary checkout.
- `lv_obj_scroll_to_view` scrolls only the immediate parent; use the `_recursive` form for a
  label inside a row inside a list (the simulator tap otherwise hits the header).

## Remaining on #86

Setup Exchange download → install → Pocket Technician load on the glass at a track that has
setups (Spa does; Magione has none), in a human-launched session; on-glass photo vs
`esp32_rig.png`.
