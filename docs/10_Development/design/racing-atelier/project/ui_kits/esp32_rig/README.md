# OLED rig touchscreen (UI kit)

Click-through recreation of the **320×480 rig screen** (LVGL 8.3) in the Racing
Atelier instrument language. True-carbon ground (pixels off on OLED), one
decision per screen, segment bars and big tabular numerals.

- `index.html` — the device + a tab bar (outside the bezel): **AC Copilot**
  (brake-zone coaching), **Pocket Technician** (block stepper + level cells +
  saved setups), **Track Atlas** (Spa map + key corners).

Composes `CommandVerb · SegmentBar · DeltaBar · Stepper · LevelSegments ·
SetupRow · NavTile · TrackMap · CornerLine · ElevationProfile · StatusField`.
LVGL has no blur/shadow/images — surfaces are flat colour; the instrument
elements are `lv_obj` rectangles (see `guidelines/firmware-fonts.md`).
