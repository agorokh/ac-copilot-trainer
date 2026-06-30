# Firmware fonts — getting Racing Atelier type onto the OLED (C++ / LVGL)

The two display faces are plain TTFs, so they convert straight to LVGL C font
arrays. Nothing in the type system needs a browser.

## Tool: `lv_font_conv`

```bash
npm i -g lv_font_conv

# Big readouts — Saira 700, 4bpp anti-aliased (colour IPS like the JC3248W535)
lv_font_conv --font Saira-Bold.ttf \
  --size 46 --bpp 4 --format lvgl \
  --symbols "0123456789:.+-/%km/h MΔ" \
  -o saira_46.c

# Commands / labels — Saira Semi Condensed 700
lv_font_conv --font SairaSemiCondensed-Bold.ttf \
  --size 28 --bpp 4 --format lvgl --range 0x20-0x7F \
  -o saira_sc_28.c
```

```cpp
LV_FONT_DECLARE(saira_46);
lv_obj_set_style_text_font(dist_label, &saira_46, 0);
```

## Recommended cut list (matches the type scale)

| Face | Sizes (px) | bpp | Use |
|---|---|---|---|
| Saira Semi Condensed Bold/Black | 54, 34, 28 | 4 | commands (BRAKE), corner names |
| Saira Semi Condensed 600 | 12, 11, 9 | 4 | tight-caps labels |
| Saira Bold | 46, 34, 26 | 4 | readouts (distance, delta, speed) |
| Spline Sans Mono 500 | 12, 11, 10 | 4 | units, ids |

## The instrument elements are LVGL objects, not glyphs

The signature pieces are drawn, not typeset — they survive the font constraint:
- **Segment bar** — a row of `lv_obj` rectangles (`lv_obj_set_style_bg_color`);
  set each to chalk / lift / brake / a dim zone fill. This is the most legible
  motorsport idiom and trivial in LVGL.
- **Delta block** — one `lv_obj` whose `x`/`width` you drive from the signed
  delta around a centre line.
- **Level cells (TC/ABS)** — N small `lv_obj`s, brass when lit.
- **Corner brackets** — four 2px `lv_obj` L's at the panel corners (brass).
- **Track map** — `lv_canvas` + `lv_canvas_draw_line` along the circuit
  polyline, or a pre-baked indexed bitmap if the MCU is tight.

## Monochrome OLED (SSD1306 / SH1107)

Convert with `--bpp 1`. Saira Semi Condensed stays crisp at the big command
sizes; for anything ≤12px prefer the heavier weight. The segment/delta/level
elements are *more* at home on 1-bit (on/off blocks) than any anti-aliased bar.

```bash
lv_font_conv --font SairaSemiCondensed-Bold.ttf --size 30 --bpp 1 \
  --range 0x20-0x7F --format lvgl -o saira_sc_30_mono.c
```

## Flash budget

Always **subset**. The readouts need only digits + a few symbols
(`--symbols "0123456789:.+-/%kmhMΔ"`). Subsetting each face to what a screen
prints keeps every font a few KB on the 16 MB flash.

## ASCII-safe copy

Until the `.c` fonts ship, keep on-device copy ASCII (`< BACK`, `+`, `-`, plain
words). The `Δ` and `›`/`‹` glyphs become available once they're in the subset.
