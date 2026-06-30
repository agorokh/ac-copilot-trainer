import React from "react";

/**
 * CornerNote — the "now entering" pace-note panel: the corner read large with
 * its gear / minimum speed / throttle as big tabular readouts, and one line of
 * coaching. The Track Atlas's focal instrument.
 */
export function CornerNote({ eyebrow = "Now entering", id, name, gear, minSpeed, throttle, note, style = {} }) {
  const stat = (label, value, color) => (
    <span>
      <div style={{ fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--dim)" }}>{label}</div>
      <div style={{ fontFamily: "var(--font-read)", fontWeight: 700, fontSize: 26, fontVariantNumeric: "tabular-nums", color: color || "var(--chalk)" }}>{value}</div>
    </span>
  );
  return (
    <div style={style}>
      <div style={{ fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--brake)" }}>
        {eyebrow}{id ? " · " + id : ""}
      </div>
      <div style={{ fontFamily: "var(--font-disp)", fontWeight: 800, fontSize: 34, letterSpacing: "0.01em", textTransform: "uppercase", marginTop: 6 }}>{name}</div>
      <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
        {gear != null && stat("gear", gear)}
        {minSpeed != null && stat("min speed", minSpeed)}
        {throttle != null && stat("throttle", throttle + "%", "var(--clear)")}
      </div>
      {note && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--mute)", lineHeight: 1.6, marginTop: 14, borderTop: "1px solid var(--line)", paddingTop: 12 }}>{note}</div>
      )}
    </div>
  );
}
