import React from "react";

/**
 * DeltaBar — the bidirectional pace block + big number. A thick block grows
 * from a centre reference: right = too fast (stop), left = too slow (warn),
 * centred = on line (go). Direction and amount land in one glance.
 */
export function DeltaBar({ value = 0, max = 20, slack = 4, unit = "", refLabel, style = {} }) {
  const v = Math.max(-max, Math.min(max, value));
  const tone = v > slack ? "var(--brake)" : v < -slack ? "var(--lift)" : "var(--clear)";
  const half = (Math.abs(v) / max) * 50;
  const left = v >= 0 ? 50 : 50 - half;
  return (
    <div style={style}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ flex: 1, position: "relative", height: "var(--delta-h)", background: "var(--raise)" }}>
          <span style={{ position: "absolute", left: "50%", top: -3, bottom: -3, width: 2, background: "var(--mute)" }} />
          <span style={{ position: "absolute", top: 0, bottom: 0, left: left + "%", width: half + "%", background: tone }} />
        </div>
        <span style={{ fontFamily: "var(--font-read)", fontWeight: 700, fontSize: 40, lineHeight: 0.8, color: tone, fontVariantNumeric: "tabular-nums", minWidth: 84, textAlign: "right" }}>
          {v > 0 ? "+" : ""}{v}
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--dim)" }}>−{max}</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--dim)" }}>{refLabel || "0"}{unit}</span>
        <span style={{ fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--dim)" }}>+{max}</span>
      </div>
    </div>
  );
}
