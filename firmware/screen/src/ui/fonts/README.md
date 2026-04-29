# Rig screen fonts (LVGL 8.3 binaries)

This directory ships the **source** TTFs (`src/`) and the **SIL OFL v1.1**
license (`OFL.txt`) bundled with the firmware so the board build is
self-contained. Parts C–F of issue #86 will start using custom faces and
will reference the converted **`.c`** outputs that LVGL's `lv_font_conv`
produces from these TTFs.

**Conversion is optional today.** Part A/B firmware does not yet declare or
use any of the generated faces — the launcher and placeholders fall back to
LVGL's built-in Montserrat 14 (set as `LV_FONT_DEFAULT` in
`firmware/screen/include/lv_conf.h`). When a screen in Parts C–F adds a
`LV_FONT_DECLARE(font_xxx)` and a corresponding style hook, run the
converter (instructions below) before flashing that build.

The font sources are the same files used by the in-game HUD, copied from
`src/ac_copilot_trainer/content/fonts/`. Keep the two trees in sync if
you ever rebuild the HUD font set.

## Glyph range

All four faces should be converted with the same range:

```text
0x20-0x7F,0x2022,0x00D7
```

That covers basic Latin (`!`–`~`), the bullet (`•`, U+2022), and the
multiplication sign (`×`, U+00D7) used for the delta chip. Add more code
points if a screen ever needs accented glyphs.

## Conversion commands

Install the converter once: `npm i -g lv_font_conv`. Then from the repo
root run the four commands below; outputs land next to this README as
`.c` files referenced by `firmware/screen/src/ui/`.

```bash
lv_font_conv \
  --font firmware/screen/src/ui/fonts/src/Syncopate-Bold.ttf \
  --size 14 --bpp 4 --no-compress \
  --range '0x20-0x7F,0x2022,0x00D7' \
  --format lvgl \
  --output firmware/screen/src/ui/fonts/font_syncopate_bold_14.c

lv_font_conv \
  --font firmware/screen/src/ui/fonts/src/Michroma-Regular.ttf \
  --size 18 --bpp 4 --no-compress \
  --range '0x20-0x7F,0x2022,0x00D7' \
  --format lvgl \
  --output firmware/screen/src/ui/fonts/font_michroma_18.c

lv_font_conv \
  --font firmware/screen/src/ui/fonts/src/Montserrat-Regular.ttf \
  --size 11 --bpp 4 --no-compress \
  --range '0x20-0x7F,0x2022,0x00D7' \
  --format lvgl \
  --output firmware/screen/src/ui/fonts/font_montserrat_11.c

lv_font_conv \
  --font firmware/screen/src/ui/fonts/src/Montserrat-Bold.ttf \
  --size 12 --bpp 4 --no-compress \
  --range '0x20-0x7F,0x2022,0x00D7' \
  --format lvgl \
  --output firmware/screen/src/ui/fonts/font_montserrat_bold_12.c
```

## Symbols exported by the `.c` files

LVGL declares converted faces as `LV_FONT_DECLARE(font_xxx)` in the
firmware. The symbol name comes from the `.c` filename, so the four
generated symbols you can use from the screens (Parts C–F) are:

| Symbol                       | Use                                  |
|------------------------------|--------------------------------------|
| `font_syncopate_bold_14`     | Screen titles                        |
| `font_michroma_18`           | Numbers, corner labels, setup names  |
| `font_montserrat_11`         | Body / descriptions                  |
| `font_montserrat_bold_12`    | Emphasis                             |

These symbols become valid the first time a screen pulls one in via
`LV_FONT_DECLARE(...)`; until then the build is unaffected by whether
the `.c` files exist on disk.

## License

`OFL.txt` is a verbatim copy of the SIL Open Font License v1.1 that
covers all four bundled TTFs. Re-ship it with any binary that embeds
the converted glyphs.
