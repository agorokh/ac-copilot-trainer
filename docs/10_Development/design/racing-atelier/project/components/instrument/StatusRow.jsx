import React from "react";

/**
 * StatusRow — one Game Point launcher line: tight-caps label, the verbatim
 * probe word coloured by tone, and a muted mono detail. Maps 1:1 to a
 * GamePointStatus field.
 */
const TONES = { go: "var(--clear)", warn: "var(--lift)", stop: "var(--brake)", idle: "var(--dim)", info: "var(--chalk)" };
export function StatusRow({ label, state, tone = "idle", detail, last = false, style = {} }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "11px 0",
      borderBottom: last ? "none" : "1px solid var(--line)", ...style,
    }}>
      <span style={{ width: 96, fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 12, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--mute)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 13, letterSpacing: "0.04em", textTransform: "uppercase", color: TONES[tone] || TONES.idle }}>{state}</span>
      {detail && <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--dim)" }}>{detail}</span>}
    </div>
  );
}
