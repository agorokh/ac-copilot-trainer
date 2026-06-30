import React from "react";

/**
 * CornerLine — one row in a corner list: mono id, Saira caps name, and a right-
 * aligned note. The compact Track Atlas index.
 */
export function CornerLine({ id, name, note, last = false, style = {} }) {
  return (
    <div style={{ display: "flex", gap: 9, alignItems: "baseline", padding: "7px 0", borderBottom: last ? "none" : "1px solid var(--line)", ...style }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--brass)", minWidth: 36 }}>{id}</span>
      <span style={{ fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 13, letterSpacing: "0.03em", textTransform: "uppercase" }}>{name}</span>
      {note && <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--mute)", textAlign: "right" }}>{note}</span>}
    </div>
  );
}
