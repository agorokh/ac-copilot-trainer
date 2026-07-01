# Rig screen fonts (Racing Atelier / LVGL 8.3)

This directory ships the Racing Atelier firmware font bundle for issue #86
Part A4. The generated `font_*.c` files are committed because the LVGL screens
reference them directly through `firmware/screen/include/ui/tokens.h`.

Source guidance:

- `docs/10_Development/design/racing-atelier/project/guidelines/firmware-fonts.md`
- `docs/10_Development/design/racing-atelier/project/tokens/typography.css`
- Visual gate: `docs/10_Development/design/racing-atelier-renders/esp32_rig.png`

## Source Fonts

The source TTFs under `src/` come from the Google Fonts repository and are
licensed under SIL OFL v1.1 (`OFL.txt`):

| Source | Use |
|---|---|
| `Saira-wdth-wght.ttf` | upstream variable font |
| `Saira-Bold.ttf` | frozen `wght=700, wdth=100` instance for readouts |
| `SairaSemiCondensed-Black.ttf` | command hero |
| `SairaSemiCondensed-Bold.ttf` | command and title labels |
| `SairaSemiCondensed-SemiBold.ttf` | tight-caps labels |
| `SplineSansMono-wght.ttf` | upstream variable mono font |
| `SplineSansMono-Medium.ttf` | frozen `wght=500` instance for units/status text |

The frozen variable instances were generated with `fontTools.varLib.instancer`.
They are committed so `lv_font_conv` can be rerun without installing fonttools.

## Glyph Range

Firmware copy remains ASCII-safe. The generated command/label/mono fonts use
`0x20-0x7F`; the numeric readout fonts are subset to the glyphs below **plus a
trailing space**. The space glyph is required for readout spacing and is part
of every `--symbols "… "` argument in the regeneration commands — keep it when
re-running `lv_font_conv`:

```text
0123456789:.+-/%kmhM<SPACE>
```

Add more glyphs only when a screen actually prints them.

## Regeneration

Install the converter once:

```bash
npm i -g lv_font_conv
```

Then run these commands from the repo root. `--no-compress` is required because
`firmware/screen/include/lv_conf.h` has `LV_USE_FONT_COMPRESSED` disabled.

```bash
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-Black.ttf --size 54 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_black_54.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-Bold.ttf --size 34 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_bold_34.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-Bold.ttf --size 28 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_bold_28.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-SemiBold.ttf --size 12 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_semibold_12.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-SemiBold.ttf --size 11 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_semibold_11.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SairaSemiCondensed-SemiBold.ttf --size 9 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_saira_sc_semibold_9.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/Saira-Bold.ttf --size 46 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --symbols "0123456789:.+-/%kmhM " --output firmware/screen/src/ui/fonts/font_saira_bold_46.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/Saira-Bold.ttf --size 34 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --symbols "0123456789:.+-/%kmhM " --output firmware/screen/src/ui/fonts/font_saira_bold_34.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/Saira-Bold.ttf --size 26 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --symbols "0123456789:.+-/%kmhM " --output firmware/screen/src/ui/fonts/font_saira_bold_26.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SplineSansMono-Medium.ttf --size 12 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_spline_mono_12.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SplineSansMono-Medium.ttf --size 11 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_spline_mono_11.c
lv_font_conv --font firmware/screen/src/ui/fonts/src/SplineSansMono-Medium.ttf --size 10 --bpp 4 --no-compress --format lvgl --lv-include lvgl.h --range 0x20-0x7F --output firmware/screen/src/ui/fonts/font_spline_mono_10.c
```
