import React from "react";

/**
 * Panel — the carbon instrument surface. Square, flat, edge border. `brackets`
 * adds the machined brass corner L's (the house frame). `glass` is the in-game
 * translucent variant (web/desktop only — never on the ESP32).
 */
export function Panel({
  children, variant = "panel", brackets = false, pad = 0, style = {}, ...rest
}) {
  const bg = {
    panel: "linear-gradient(180deg, var(--graphite), var(--carbon))",
    flat: "var(--graphite)",
    raised: "var(--slab)",
    glass: "var(--glass-fill)",
  }[variant];
  const isGlass = variant === "glass";
  const arm = (pos) => {
    const base = { position: "absolute", width: "var(--bracket)", height: "var(--bracket)", border: "var(--border-bracket)", pointerEvents: "none" };
    const m = {
      tl: { top: -1, left: -1, borderRight: 0, borderBottom: 0 },
      tr: { top: -1, right: -1, borderLeft: 0, borderBottom: 0 },
      bl: { bottom: -1, left: -1, borderRight: 0, borderTop: 0 },
      br: { bottom: -1, right: -1, borderLeft: 0, borderTop: 0 },
    }[pos];
    return <span key={pos} style={{ ...base, ...m }} />;
  };
  return (
    <div style={{
      position: "relative", background: bg, border: "1px solid var(--edge)",
      borderRadius: "var(--r)", padding: pad,
      backdropFilter: isGlass ? "var(--glass-blur)" : undefined,
      WebkitBackdropFilter: isGlass ? "var(--glass-blur)" : undefined,
      boxShadow: isGlass ? "var(--shadow-glass)" : undefined, ...style,
    }} {...rest}>
      {brackets && ["tl", "tr", "bl", "br"].map(arm)}
      {children}
    </div>
  );
}
