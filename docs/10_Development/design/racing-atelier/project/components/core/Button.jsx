import React from "react";

/**
 * Button — the instrument action. A flat field, square corners, tight bold
 * caps. `primary` is the single brass action; `ghost` is a hairline-bordered
 * secondary. Colour fields, never pills.
 */
export function Button({
  children,
  variant = "field",   // "field" | "primary" | "ghost"
  size = "md",          // "sm" | "md" | "lg"
  block = false,
  disabled = false,
  iconLeft = null,
  style = {},
  ...rest
}) {
  const pads = { sm: "7px 12px", md: "11px 16px", lg: "0 20px" };
  const minH = { sm: 30, md: 40, lg: "var(--tap-min)" };
  const fs = { sm: 12, md: 14, lg: 15 };
  const variants = {
    field: { background: "var(--raise)", color: "var(--chalk)", border: "1px solid var(--line-2)" },
    primary: { background: "var(--brass)", color: "var(--brass-ink)", border: "1px solid var(--brass)" },
    ghost: { background: "transparent", color: "var(--mute)", border: "1px solid var(--line-2)" },
  };
  const v = variants[variant] || variants.field;
  return (
    <button
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
        width: block ? "100%" : "auto", minHeight: minH[size], padding: pads[size],
        ...v, borderRadius: "var(--r)",
        fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: fs[size],
        letterSpacing: "0.08em", textTransform: "uppercase",
        cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1,
        transition: "opacity var(--dur-press) var(--ease)",
        ...style,
      }}
      onMouseDown={(e) => { if (!disabled) e.currentTarget.style.opacity = "0.75"; }}
      onMouseUp={(e) => { if (!disabled) e.currentTarget.style.opacity = "1"; }}
      onMouseLeave={(e) => { if (!disabled) e.currentTarget.style.opacity = "1"; }}
      {...rest}
    >
      {iconLeft}{children}
    </button>
  );
}
