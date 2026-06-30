import React from "react";

/** SegMark — the brand atom: a short brass bar set before a wordmark/section. */
export function SegMark({ height = "var(--seg-mark-h)", width = "var(--seg-mark-w)", color = "var(--brass)", style = {} }) {
  return <span aria-hidden="true" style={{ display: "inline-block", width, height, background: color, flex: "0 0 auto", ...style }} />;
}

/**
 * BrandMark — the RACING ATELIER identity lockup: the brass seg-mark + the
 * wordmark in tight Saira caps. The single recognisable house signature.
 */
export function BrandMark({ text = "RACING ATELIER", size = "md", color = "var(--chalk)", markHeight, style = {} }) {
  const fs = { sm: 14, md: 18, lg: 22 }[size] || 18;
  const mh = markHeight || (fs + 4) + "px";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 12, ...style }}>
      <SegMark height={mh} />
      <span style={{ fontFamily: "var(--font-disp)", fontWeight: 800, fontSize: fs, letterSpacing: "0.16em", textTransform: "uppercase", color }}>{text}</span>
    </span>
  );
}

/**
 * CornerBracket — a single machined brass L. Place four (tl/tr/bl/br) inside a
 * positioned container, or use Panel's `brackets` prop. The house frame device.
 */
export function CornerBracket({ pos = "tl", color = "var(--brass)", size = 14, style = {} }) {
  const m = {
    tl: { top: -1, left: -1, borderRight: 0, borderBottom: 0 },
    tr: { top: -1, right: -1, borderLeft: 0, borderBottom: 0 },
    bl: { bottom: -1, left: -1, borderRight: 0, borderTop: 0 },
    br: { bottom: -1, right: -1, borderLeft: 0, borderTop: 0 },
  }[pos];
  return <span aria-hidden="true" style={{ position: "absolute", width: size, height: size, border: "2px solid " + color, pointerEvents: "none", ...m, ...style }} />;
}
