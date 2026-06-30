import React from "react";
import { Chip } from "../core/Chip.jsx";

/**
 * SetupRow — a saved setup in Pocket Technician. Name + best-lap meta + compact
 * chips. The loaded setup gets a brass left-marker and tinted band.
 */
export function SetupRow({ name, meta, chips = [], active = false, onClick, last = false, style = {} }) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
      padding: "9px 8px", background: active ? "linear-gradient(90deg, rgba(200,152,62,0.10), transparent)" : "transparent",
      border: 0, borderLeft: active ? "2px solid var(--brass)" : "2px solid transparent",
      borderBottom: last ? "none" : "1px solid var(--line)", cursor: "pointer", ...style,
    }}>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 13, letterSpacing: "0.03em", textTransform: "uppercase", color: "var(--chalk)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{name}</span>
        {meta && <span style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, color: "var(--dim)" }}>{meta}</span>}
      </span>
      {chips.map((c, i) => <Chip key={i} tone={c.tone}>{c.text}</Chip>)}
    </button>
  );
}
