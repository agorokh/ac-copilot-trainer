import React from "react";

/**
 * LevelSegments — a discrete level read as lit cells (TC 2, ABS 1, wings 4/8).
 * Chunky cells, brass when lit. The cockpit way to show a small integer.
 */
export function LevelSegments({ value = 0, max = 6, tone = "brass", style = {} }) {
  const lit = { brass: "var(--brass)", go: "var(--clear)", warn: "var(--lift)" }[tone] || "var(--brass)";
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center", ...style }}>
      {Array.from({ length: max }).map((_, i) => (
        <span key={i} style={{ width: "var(--level-w)", height: "var(--level-h)", background: i < value ? lit : "var(--raise)" }} />
      ))}
    </div>
  );
}
