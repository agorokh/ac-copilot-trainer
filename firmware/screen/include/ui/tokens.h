// Design tokens for the rig screen UI — issue #86 Part A6.
//
// These mirror the Figma "In-game Coaching Trainer Design" palette and the
// HUD color rules carried over from PR #73. The Figma file is the authority
// for screen-side colors; the HUD keeps its own #FFC43D amber for line-hint
// rendering — both coexist (see screen-ui-stack-lvgl-touch.md and
// dashboard-visual-design-figma.md).
//
// Note: LVGL's color API has no `.filter()` operator. The Figma spec uses
// translucent fills like `rgba(255,255,255,0.12)` for soft borders; in LVGL
// 8.3 we render those with a base color + LV_OPA_* on the style. The
// `_OPA` defines below name the canonical opacity for each token.

#pragma once

#include <lvgl.h>

/* Backgrounds */
#define UI_BG_BASE          lv_color_hex(0x000000)
#define UI_BG_PANEL         lv_color_hex(0x1E1E1E)   /* rgba(30,30,30,0.92)  */
#define UI_BG_PANEL_OPA     ((lv_opa_t)235)          /* 0.92 × 255           */
#define UI_BG_HEADER        lv_color_hex(0x141414)   /* rgba(20,20,20,0.95)  */
#define UI_BG_HEADER_OPA    ((lv_opa_t)242)          /* 0.95 × 255           */

/* Text */
#define UI_TX_PRIMARY       lv_color_hex(0xFFFFFF)
#define UI_TX_MUTED         lv_color_hex(0xA3A3A3)   /* neutral-400          */
#define UI_TX_QUIET         lv_color_hex(0x737373)   /* neutral-500          */

/* Accents — Figma authoritative for screen */
#define UI_ACCENT_GOLD      lv_color_hex(0xFFD700)   /* primary accent       */
#define UI_ALERT_RED        lv_color_hex(0xEF4444)
#define UI_OK_GREEN         lv_color_hex(0x22C55E)   /* "ON PACE" chip       */
#define UI_LINE_AMBER       lv_color_hex(0xFFC43D)   /* HUD-side line hint   */

/* Borders — base color + suggested opacity for the style */
#define UI_BORDER_SOFT      UI_TX_PRIMARY            /* rgba(255,255,255,0.12) */
#define UI_BORDER_SOFT_OPA  ((lv_opa_t)31)           /* 0.12 × 255             */
#define UI_BORDER_ALERT     UI_ALERT_RED
#define UI_BORDER_ALERT_OPA ((lv_opa_t)102)          /* 0.40 × 255             */

/* Layout — Part A7 tap-target floor */
#define UI_TAP_MIN_PX       60
#define UI_RADIUS_TILE      8
#define UI_GAP_TILES        12

/* Animation — Part A7 active-state feedback */
#define UI_ANIM_PRESS_MS    120
#define UI_ANIM_PRESS_SCALE 251   /* 0.98 × 256 — LVGL transform_zoom unit  */
