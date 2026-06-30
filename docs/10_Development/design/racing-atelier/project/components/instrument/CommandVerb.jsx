import React from "react";

/**
 * CommandVerb — the one action, periphery-caught. Huge Saira Semi Condensed
 * caps in a signal colour, with an optional direction arrow. This is the
 * loudest thing on any cockpit surface; there is only ever one.
 */
const TONES = { stop: "var(--brake)", warn: "var(--lift)", go: "var(--clear)" };
export function CommandVerb({ children, tone = "stop", arrow = null, size = 66, style = {} }) {
  const c = TONES[tone] || TONES.stop;
  const arrows = { down: "▼", up: "▲", left: "◀", right: "▶" };
  return (
    <div style={style}>
      <div style={{
        fontFamily: "var(--font-disp)", fontWeight: 800, fontSize: size,
        lineHeight: 0.82, letterSpacing: "0.01em", textTransform: "uppercase", color: c,
      }}>
        {children}
      </div>
      {arrow && <div style={{ fontSize: size * 0.42, lineHeight: 0.6, color: c }}>{arrows[arrow] || arrow}</div>}
    </div>
  );
}
