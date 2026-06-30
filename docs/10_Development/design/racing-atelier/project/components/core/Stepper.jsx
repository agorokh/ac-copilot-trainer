import React from "react";

/**
 * Stepper — block −/+ adjust control for one parameter (brake bias, FOV…).
 * Big Saira readout value; square block buttons; optional fill bar showing the
 * value's position in range. Minus muted, plus brass.
 */
export function Stepper({
  label, value, unit = "", fill = null, onDecrement, onIncrement, disabled = false, style = {},
}) {
  const btn = {
    fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 16, color: "var(--chalk)",
    background: "var(--raise)", border: 0, width: 30, height: 30, cursor: disabled ? "not-allowed" : "pointer", flex: "0 0 auto",
  };
  return (
    <div style={{ opacity: disabled ? 0.4 : 1, ...style }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{ flex: 1 }}>
          {label != null && <div style={{ fontFamily: "var(--font-disp)", fontWeight: 600, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--mute)" }}>{label}</div>}
          <div>
            <span style={{ fontFamily: "var(--font-read)", fontWeight: 700, fontSize: 24, fontVariantNumeric: "tabular-nums" }}>{value}</span>
            {unit && <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--mute)" }}>{unit}</span>}
          </div>
        </div>
        <button aria-label="decrease" onClick={onDecrement} disabled={disabled} style={btn}>−</button>
        <button aria-label="increase" onClick={onIncrement} disabled={disabled} style={{ ...btn, color: "var(--brass)" }}>+</button>
      </div>
      {fill != null && (
        <div style={{ height: 8, background: "var(--raise)", marginTop: 8, position: "relative" }}>
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: Math.max(0, Math.min(1, fill)) * 100 + "%", background: "var(--brass)" }} />
        </div>
      )}
    </div>
  );
}
