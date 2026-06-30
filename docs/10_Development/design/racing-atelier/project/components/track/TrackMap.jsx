import React from "react";

/**
 * TrackMap — a schematic circuit line drawn from an SVG path. Generic: pass any
 * track's `path` (d string), optional `highlight` sub-path (red), corner
 * `markers`, a pulsing `here` position, and `labels`. The geometry is data, not
 * decoration — drive it from a real circuit dataset.
 */
export function TrackMap({
  path, viewBox = "0 0 290 150", highlight, markers = [], here = null, labels = [],
  stroke = "var(--chalk)", strokeWidth = 2.4, opacity = 1, style = {},
}) {
  const toneColor = (t) => ({ stop: "var(--brake)", warn: "var(--lift)", go: "var(--clear)", data: "var(--data)", house: "var(--brass)", chalk: "var(--chalk)" }[t] || "var(--brass)");
  return (
    <svg viewBox={viewBox} fill="none" style={{ display: "block", width: "100%", height: "auto", ...style }}>
      <path d={path} stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" opacity={opacity} />
      {highlight && <path d={highlight} stroke="var(--brake)" strokeWidth={strokeWidth + 0.6} strokeLinecap="round" />}
      {markers.map((m, i) => <circle key={i} cx={m.x} cy={m.y} r={m.r || 3} fill={toneColor(m.tone)} />)}
      {here && <>
        <circle cx={here.x} cy={here.y} r="5" fill="var(--brake)" />
        <circle cx={here.x} cy={here.y} r="9" fill="none" stroke="var(--brake)" strokeWidth="1.4" opacity="0.6" />
      </>}
      {labels.map((l, i) => (
        <text key={i} x={l.x} y={l.y} fontFamily="Spline Sans Mono" fontSize={l.size || 8} fill={toneColor(l.tone || "chalk")}>{l.text}</text>
      ))}
    </svg>
  );
}
