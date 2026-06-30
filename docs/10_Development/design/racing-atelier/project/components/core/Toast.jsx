import React from "react";

/**
 * Toast — brief acknowledgement / failure notice. A flat field bar with the
 * state word + one short line. Tone carries meaning.
 */
const TONES = { ok: "var(--clear)", error: "var(--brake)", info: "var(--mute)" };
export function Toast({ children, tone = "info", title, style = {} }) {
  const c = TONES[tone] || TONES.info;
  return (
    <div role="status" style={{
      display: "flex", flexDirection: "column", gap: 2, padding: "9px 12px",
      background: "var(--graphite)", borderLeft: "3px solid " + c, border: "1px solid var(--line-2)",
      borderRadius: "var(--r)", maxWidth: 300, ...style,
    }}>
      {title && <span style={{ fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c }}>{title}</span>}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--mute)", lineHeight: 1.4 }}>{children}</span>
    </div>
  );
}
