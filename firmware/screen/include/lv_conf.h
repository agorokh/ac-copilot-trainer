// LVGL 8.3 config for the JC3248W535 rig screen — Phase 2 (issue #86).
//
// This file is a minimal copy + prune of the upstream lv_conf_template.h
// shipped with LVGL 8.3.11. Only the flags that diverge from upstream
// defaults are documented; everything else inherits the template default.
//
// References:
//   docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
//   firmware/screen/src/main.cpp (LV_COLOR_16_SWAP rationale on the
//                                 AXS15231B big-endian RGB565 byte order)

#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

/* =====================
 *   COLOR
 * ===================== */
#define LV_COLOR_DEPTH       16
/* AXS15231B + Arduino_GFX expects big-endian RGB565 — same byte order as the
 * Phase-1 raw-GFX path (see firmware/screen/src/main.cpp comment near COL_*). */
#define LV_COLOR_16_SWAP     1
#define LV_COLOR_SCREEN_TRANSP 0
#define LV_COLOR_MIX_ROUND_OFS 0
#define LV_COLOR_CHROMA_KEY  lv_color_hex(0x00ff00)

/* =====================
 *   MEMORY
 * ===================== */
/* 64 KiB pool. LVGL 8.3 widgets + 4 screens budgeted under 150 KiB total
 * including the two 240×40 RGB565 partial buffers (~38 KiB) allocated in
 * PSRAM by main.cpp. Bump if `lv_mem_monitor` reports > 80% used. */
#define LV_MEM_CUSTOM        0
#define LV_MEM_SIZE          (64U * 1024U)
#define LV_MEM_ADR           0
/* LV_MEM_AUTO_DEFRAG is documentation-only on LVGL v8.3 with LV_MEM_CUSTOM=0:
 * the v8.3 builtin allocator (lv_tlsf) does not honor this flag (only the
 * legacy custom allocator path read it pre-v8). Kept here so the intent is
 * obvious if we ever flip to a custom allocator. (CodeRabbit nit on PR #91.) */
#define LV_MEM_AUTO_DEFRAG   1
#define LV_MEM_BUF_MAX_NUM   16
/* ESP32 newlib's memcpy/memset are word-aligned and use Xtensa hardware loops,
 * generally faster than LVGL's portable implementations on the partial-buffer
 * flush path. Cheap perf win. (CodeRabbit nit on PR #91.) */
#define LV_MEMCPY_MEMSET_STD 1

/* =====================
 *   HAL / TICK
 * ===================== */
/* main.cpp calls `lv_tick_inc(elapsed)` once per loop(), so the LVGL custom
 * sys-time tick source is intentionally OFF. Enabling both is internally
 * inconsistent (Copilot review on PR #91); pick one and stick with it. The
 * manual path is preferred because we already track `lv_last_tick_ms` for
 * the canvas-flush throttle. */
#define LV_TICK_CUSTOM                 0
#define LV_DPI_DEF                     130

/* =====================
 *   FEATURES
 * ===================== */
#define LV_USE_PERF_MONITOR  0
#define LV_USE_MEM_MONITOR   0
#define LV_USE_LOG           1
#define LV_LOG_LEVEL         LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF        1
#define LV_USE_ASSERT_NULL          1
#define LV_USE_ASSERT_MALLOC        1
#define LV_USE_ASSERT_STYLE         0
#define LV_USE_ASSERT_MEM_INTEGRITY 0
#define LV_USE_ASSERT_OBJ           0

#define LV_USE_FLEX          1
#define LV_USE_GRID          1
/* LV_USE_ANIMATION / LV_USE_SHADOW / LV_USE_BLEND_MODES / LV_USE_OPA_SCALE /
 * LV_USE_IMG_TRANSFORM / LV_USE_GROUP intentionally omitted: the v8.3 release
 * template does NOT define these symbols. In v8.3 they're either gated on
 * draw-engine flags (LV_DRAW_*) or implicit in lv_obj / default-on in
 * lv_conf_internal.h. Defining them here is a no-op and risks rotting if
 * someone copies them into v9. (CodeRabbit nit on PR #91.) */
#define LV_USE_GPU_NXP_PXP   0

/* =====================
 *   WIDGETS (Part A: enable everything Parts B–F will need)
 * ===================== */
/* LV_USE_OBJ is not a v8.3 toggle — lv_obj is unconditionally built into the
 * core. The separately toggleable LV_USE_OBJ landed in v9. Removed on PR #91
 * after CodeRabbit confirmed against upstream lvgl/lvgl release/v8.3. */
#define LV_USE_LABEL         1
#define LV_LABEL_TEXT_SELECTION 0
#define LV_LABEL_LONG_TXT_HINT  1

#define LV_USE_BTN           1
#define LV_USE_BTNMATRIX     1
#define LV_USE_BAR           1
#define LV_USE_LIST          1
#define LV_USE_SPINNER       1
#define LV_USE_LINE          1

/* Part C uses bars + cards; D/E use list + chevrons. */
#define LV_USE_IMG           1
#define LV_USE_CANVAS        1
#define LV_USE_TEXTAREA      0
#define LV_USE_DROPDOWN      0
#define LV_USE_SLIDER        0
#define LV_USE_SWITCH        0
#define LV_USE_CHECKBOX      0
#define LV_USE_ROLLER        0
/* lv_spinner depends on lv_arc in LVGL 8.3; LV_USE_SPINNER=1 above
 * requires LV_USE_ARC=1 here or the LVGL preprocessor refuses to
 * build the spinner widget. (chatgpt-codex P1 on PR #91.) */
#define LV_USE_ARC           1
#define LV_USE_TABLE         0
#define LV_USE_TABVIEW       0
#define LV_USE_TILEVIEW      0   /* ADR mentions tileview as future option. */
#define LV_USE_WIN           0
/* lv_extra/widgets/keyboard and lv_extra/widgets/spinbox both `#error` when
 * LV_USE_TEXTAREA is 0 (they declare an `lv_textarea_t` field). LVGL 8.3
 * pulls them in via `lv_extra.h` regardless of widget needs, so we have to
 * disable them explicitly here. We don't use either widget on the rig
 * screen — issue #86 Parts B–D only need labels, buttons, bars, lists,
 * spinner. (Discovered while building Part C/D locally; CI never runs the
 * pio build, so this never triggered before.) */
#define LV_USE_KEYBOARD      0
#define LV_USE_SPINBOX       0
/* Calendar's "header dropdown" variant references lv_dropdown_* even when
 * LV_USE_DROPDOWN=0. We don't use calendar at all, so disable the whole tree
 * (and other extras we don't use) to keep the link clean. */
#define LV_USE_CALENDAR      0
#define LV_USE_CHART         0
#define LV_USE_METER         0
#define LV_USE_MSGBOX        0
#define LV_USE_SPAN          0
#define LV_USE_COLORWHEEL    0
#define LV_USE_IMGBTN        0
#define LV_USE_LED           0
#define LV_USE_ANIMIMG       0
#define LV_USE_MENU          0

/* =====================
 *   FONTS
 * ===================== */
/* The bundled custom fonts (Syncopate / Michroma / Montserrat) are converted
 * by `lv_font_conv` and registered in firmware/screen/src/ui/fonts/.
 * Until the user runs the converter, the screens default to the built-in
 * Montserrat so the build still links. */
#define LV_FONT_MONTSERRAT_8   0
#define LV_FONT_MONTSERRAT_10  0
#define LV_FONT_MONTSERRAT_12  1
#define LV_FONT_MONTSERRAT_14  1
#define LV_FONT_MONTSERRAT_16  0
#define LV_FONT_MONTSERRAT_18  0
#define LV_FONT_MONTSERRAT_20  1
#define LV_FONT_MONTSERRAT_22  0
#define LV_FONT_MONTSERRAT_24  0
#define LV_FONT_MONTSERRAT_26  0
#define LV_FONT_MONTSERRAT_28  0
#define LV_FONT_MONTSERRAT_30  0
#define LV_FONT_MONTSERRAT_32  0
#define LV_FONT_MONTSERRAT_34  0
#define LV_FONT_MONTSERRAT_36  0
#define LV_FONT_MONTSERRAT_38  0
#define LV_FONT_MONTSERRAT_40  0
#define LV_FONT_MONTSERRAT_42  0
#define LV_FONT_MONTSERRAT_44  0
#define LV_FONT_MONTSERRAT_46  0
#define LV_FONT_MONTSERRAT_48  0

#define LV_FONT_DEFAULT      &lv_font_montserrat_14
#define LV_FONT_FMT_TXT_LARGE 0
#define LV_USE_FONT_COMPRESSED 0
#define LV_USE_FONT_SUBPX    0

/* =====================
 *   TEXT / BIDI
 * ===================== */
#define LV_TXT_ENC           LV_TXT_ENC_UTF8
#define LV_USE_BIDI          0
#define LV_USE_ARABIC_PERSIAN_CHARS 0

/* =====================
 *   THEMES
 * ===================== */
#define LV_USE_THEME_DEFAULT 1
#if LV_USE_THEME_DEFAULT
#  define LV_THEME_DEFAULT_DARK         1
#  define LV_THEME_DEFAULT_GROW         1
#  define LV_THEME_DEFAULT_TRANSITION_TIME 80
#endif
#define LV_USE_THEME_BASIC   1
#define LV_USE_THEME_MONO    0

/* =====================
 *   OS / FS / NETWORK
 * ===================== */
/* LV_USE_OS / LV_OS_NONE is the v9 OS abstraction; the v8.3 release template
 * does NOT define it, and defining it here is a no-op. Removed on PR #91
 * after CodeRabbit confirmed against the upstream lvgl/lvgl release/v8.3
 * lv_conf_template.h. The filesystem flags below ARE in the v8.3 template
 * and stay. */
#define LV_USE_FS_STDIO      0
#define LV_USE_FS_POSIX      0
#define LV_USE_FS_WIN32      0
#define LV_USE_FS_FATFS      0
#define LV_USE_PNG           0
#define LV_USE_BMP           0
#define LV_USE_SJPG          0
#define LV_USE_GIF           0
#define LV_USE_QRCODE        0
#define LV_USE_FREETYPE      0
#define LV_USE_TINY_TTF      0
#define LV_USE_RLOTTIE       0

#define LV_USE_USER_DATA     1

#endif /* LV_CONF_H */
