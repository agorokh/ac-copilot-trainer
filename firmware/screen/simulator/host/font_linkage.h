#pragma once
#include <lvgl.h>
#ifdef __cplusplus
#undef LV_FONT_DECLARE
#define LV_FONT_DECLARE(font_name) extern "C" const lv_font_t font_name
#endif
