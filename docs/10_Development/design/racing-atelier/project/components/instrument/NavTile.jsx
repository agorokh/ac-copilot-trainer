import React from "react";

/**
 * NavTile — an OLED rig launcher tile. Saira caps title, muted subtitle, brass
 * chevron. Square, edge border, 60px tap floor. `disabled` dims placeholders.
 */
export function NavTile({ title, subtitle, disabled = false, onClick, style = {} }) {
  return (
    <button onClick={disabled ? undefined : onClick} disabled={disabled} style={{
      display: "flex", flexDirection: "column", gap: subtitle ? 6 : 0, justifyContent: "center",
      width: "100%", minHeight: "var(--tap-min)", padding: "13px 15px", textAlign: "left",
      background: "var(--graphite)", border: "1px solid var(--edge)", borderRadius: "var(--r)",
      cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.45 : 1,
      transition: "border-color var(--dur-press) var(--ease)",
    }}
      onMouseDown={(e) => { if (!disabled) e.currentTarget.style.borderColor = "var(--brass)"; }}
      onMouseUp={(e) => { e.currentTarget.style.borderColor = "var(--edge)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--edge)"; }}>
      <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
        <span style={{ fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 15, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--chalk)" }}>{title}</span>
        <span style={{ color: disabled ? "var(--dim)" : "var(--brass)", fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 16 }}>›</span>
      </span>
      {subtitle && <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--mute)" }}>{subtitle}</span>}
    </button>
  );
}
