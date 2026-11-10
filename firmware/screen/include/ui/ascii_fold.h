// UTF-8 -> printable ASCII (0x20..0x7E) display folding — issue #86.
//
// The Phase-2 LVGL fonts (Saira SemiCondensed, Spline Sans Mono) are subset to
// printable ASCII 0x20..0x7F. External strings from Setup Exchange
// (`se.acstuff.club` community titles/authors, e.g. `PORSCHE GT3 ’16 Hotlap V1`),
// AC `ui_car.json` / `ui_track.json` (`Nürburgring`), or user setup filenames
// can carry UTF-8 curly quotes, dashes, ellipses, or accented Latin letters
// that LVGL otherwise renders as missing-glyph tofu boxes.
//
// Call `ui_ascii_fold` on display-bound copies only; keep wire/filesystem
// identifiers (`setup.load` name/path, `se.download` car_id/track_id) lossless.

#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Fold UTF-8 `src` into printable ASCII `0x20..0x7E` in `dst` (always NUL-terminated
// when `dst_n > 0`). `dst` and `src` must not overlap.
void ui_ascii_fold(char* dst, size_t dst_n, const char* src);

#ifdef __cplusplus
}
#endif
