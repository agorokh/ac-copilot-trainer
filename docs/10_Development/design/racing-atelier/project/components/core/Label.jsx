import React from "react";

/**
 * Label — the tight bold caps label. Saira Semi Condensed 600, NOT spaced-out
 * and thin. Use `tone` to colour it for state.
 */
export function Label({ children, size = "md", tone = "label", style = {} }) {
  const fs = { md: 12, sm: 11, xs: 9 };
  const colors = {
    label: "var(--mute)", dim: "var(--dim)", chalk: "var(--chalk)",
    brass: "var(--brass)", stop: "var(--brake)", warn: "var(--lift)", go: "var(--clear)",
  };
  return (
    <div style={{
      fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: fs[size] || 12,
      letterSpacing: "0.08em", textTransform: "uppercase",
      color: colors[tone] || colors.label, ...style,
    }}>
      {children}
    </div>
  );
}
