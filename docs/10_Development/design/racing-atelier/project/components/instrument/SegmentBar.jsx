import React from "react";

/**
 * SegmentBar — the shift-light magnitude bar. Chunky gapped segments read as a
 * COUNT, never a continuous slider. Fill rises toward a trailing red `zone`;
 * the leading filled segment goes amber. Built for periphery, not precision.
 */
export function SegmentBar({ count = 12, fill = 0.5, zone = 0.34, height, style = {} }) {
  const f = Math.max(0, Math.min(1, fill));
  const filledCount = Math.round(f * count);
  const zoneStart = count - Math.round(zone * count);
  const cells = [];
  for (let i = 0; i < count; i++) {
    const inZone = i >= zoneStart;
    const filled = i < filledCount;
    const leading = i === filledCount - 1;
    let bg = "var(--seg-off)";
    if (filled && inZone) bg = "var(--seg-red)";
    else if (filled && leading) bg = "var(--seg-amb)";
    else if (filled) bg = "var(--seg-lit)";
    else if (inZone) bg = "var(--seg-zone)";
    cells.push(<span key={i} style={{ flex: 1, background: bg }} />);
  }
  return (
    <div style={{ display: "flex", gap: "var(--seg-gap)", height: height || "var(--seg-h)", ...style }}>
      {cells}
    </div>
  );
}
