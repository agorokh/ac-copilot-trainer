import React from "react";

/**
 * StatusField — state as a flat colour FIELD plus the verbatim word, or a dot
 * + word for inline use. The loud, periphery-caught status treatment (the
 * launcher headline, a connection state). Colour carries meaning.
 */
const TONES = {
  go: { fill: "var(--clear)", ink: "#06140c", text: "var(--clear)" },
  warn: { fill: "var(--lift)", ink: "#1c1404", text: "var(--lift)" },
  stop: { fill: "var(--brake)", ink: "#fff", text: "var(--brake)" },
  idle: { fill: "var(--raise)", ink: "var(--mute)", text: "var(--dim)" },
  brass: { fill: "var(--brass)", ink: "var(--brass-ink)", text: "var(--brass)" },
};
export function StatusField({ children, tone = "go", variant = "field", style = {} }) {
  const t = TONES[tone] || TONES.go;
  if (variant === "dot") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 7, ...style }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: t.fill, flex: "0 0 auto" }} />
        <span style={{ fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 13, letterSpacing: "0.05em", textTransform: "uppercase", color: t.text }}>{children}</span>
      </span>
    );
  }
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", padding: "3px 9px",
      background: t.fill, color: t.ink, borderRadius: "var(--r)",
      fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 12,
      letterSpacing: "0.06em", textTransform: "uppercase", ...style,
    }}>
      {children}
    </span>
  );
}
