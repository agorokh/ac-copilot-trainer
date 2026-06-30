# In-game overlay (UI kit)

The in-game surface over the track, two modes:
- **Coaching** — the brake-zone instrument (`CommandVerb` + `SegmentBar` +
  `DeltaBar` on a bracketed glass panel).
- **Track Atlas** — the Spa circuit with you-are-here, the entering corner read
  large (`CornerNote`), the elevation climb, and the next-corner queue.

`index.html` toggles between them. Glass (translucent + blur) is web/desktop
only — never on the ESP32. Composes `CommandVerb · SegmentBar · DeltaBar ·
Panel · CornerNote · TrackMap · ElevationProfile · BrandMark`.
