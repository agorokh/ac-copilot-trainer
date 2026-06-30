import React from "react";

/**
 * ElevationProfile — the climb, drawn as a polyline. A nuance most dashes drop;
 * for tracks like Spa the elevation IS the character. Pass `points` as an SVG
 * polyline string; mark the key crest.
 */
export function ElevationProfile({
  points, viewBox = "0 0 320 56", peakX, peakLabel, startLabel, endLabel, style = {},
}) {
  return (
    <svg viewBox={viewBox} fill="none" style={{ display: "block", width: "100%", ...style }}>
      <polyline points={points} stroke="var(--chalk)" strokeWidth="2" fill="none" />
      {peakX != null && <line x1={peakX} y1="8" x2={peakX} y2="52" stroke="var(--brake)" strokeWidth="1.4" strokeDasharray="3 3" />}
      {peakLabel && <text x={(peakX || 0) - 24} y="9" fontFamily="Spline Sans Mono" fontSize="8" fill="var(--brake)">{peakLabel}</text>}
      {startLabel && <text x="0" y="54" fontFamily="Spline Sans Mono" fontSize="8" fill="var(--dim)">{startLabel}</text>}
      {endLabel && <text x="262" y="54" fontFamily="Spline Sans Mono" fontSize="8" fill="var(--dim)">{endLabel}</text>}
    </svg>
  );
}
