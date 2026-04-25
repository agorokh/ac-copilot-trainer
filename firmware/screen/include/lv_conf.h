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
#define LV_MEM_AUTO_DEFRAG   1
#define LV_MEM_BUF_MAX_NUM   16
#define LV_MEMCPY_MEMSET_STD 0

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
#define LV_USE_ANIMATION     1
#define LV_USE_SHADOW        1
#define LV_USE_BLEND_MODES   1
#define LV_USE_OPA_SCALE     1
#define LV_USE_IMG_TRANSFORM 1
#define LV_USE_GROUP         1
#define LV_USE_GPU_NXP_PXP   0

/* =====================
 *   WIDGETS (Part A: enable everything Parts B–F will need)
 * ===================== */
#define LV_USE_OBJ           1
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
#define LV_USE_ARC           0
#define LV_USE_TABLE         0
#define LV_USE_TABVIEW       0
#define LV_USE_TILEVIEW      0   /* ADR mentions tileview as future option. */
#define LV_USE_WIN           0

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
#define LV_USE_OS            LV_OS_NONE
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
