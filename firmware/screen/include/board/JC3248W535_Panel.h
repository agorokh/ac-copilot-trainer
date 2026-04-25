// Shared panel-native dimensions for the Guition JC3248W535 board.
//
// Both the display (Arduino_GFX path in JC3248W535_GFX.h) and the touch
// reader (JC3248W535_Touch.h) need to know the native portrait dimensions
// (320x480) so they stay consistent when mapping rotation, mirroring,
// or filtering raw touch coordinates. Keeping the two values in a single
// place prevents subtle mismatches if the panel configuration is ever
// changed -- e.g. a future board swap that flips the panel orientation
// would only need to be edited in this file. (Sourcery review on PR #91.)
//
// Both `JC_TFT_NATIVE_*` and `JC_TOUCH_NATIVE_*` resolve to these values
// so existing call sites continue to compile unchanged.

#pragma once

#define JC_PANEL_NATIVE_W 320
#define JC_PANEL_NATIVE_H 480
