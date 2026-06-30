import React from "react";

/**
 * Chip — a compact mono data token (BB 54 · TC 2). Hairline square outline,
 * tabular. Tone colours the outline + text for state.
 */
export function Chip({ children, tone = "neutral", style = {} }) {
  const colors = {
    neutral: { c: "var(--mute)", b: "var(--line-2)" },
    stop: { c: "var(--brake)", b: "rgba(242,59,44,0.4)" },
    warn: { c: "var(--lift)", b: "rgba(244,165,44,0.4)" },
    go: { c: "var(--clear)", b: "rgba(47,190,110,0.4)" },
    brass: { c: "var(--brass)", b: "rgba(200,152,62,0.5)" },
  };
  const t = colors[tone] || colors.neutral;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      fontFamily: "var(--font-mono)", fontSize: 10, fontVariantNumeric: "tabular-nums",
      color: t.c, border: "1px solid " + t.b, borderRadius: "var(--r)",
      padding: "1px 6px", whiteSpace: "nowrap", letterSpacing: "0.02em", ...style,
    }}>
      {children}
    </span>
  );
}
