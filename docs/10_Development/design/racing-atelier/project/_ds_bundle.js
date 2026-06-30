/* @ds-bundle: {"format":3,"namespace":"ACCopilotDesignSystem_bba7a8","components":[{"name":"SegMark","sourcePath":"components/brand/BrandMark.jsx"},{"name":"BrandMark","sourcePath":"components/brand/BrandMark.jsx"},{"name":"CornerBracket","sourcePath":"components/brand/BrandMark.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Chip","sourcePath":"components/core/Chip.jsx"},{"name":"Label","sourcePath":"components/core/Label.jsx"},{"name":"Panel","sourcePath":"components/core/Panel.jsx"},{"name":"StatusField","sourcePath":"components/core/StatusField.jsx"},{"name":"Stepper","sourcePath":"components/core/Stepper.jsx"},{"name":"Toast","sourcePath":"components/core/Toast.jsx"},{"name":"CommandVerb","sourcePath":"components/instrument/CommandVerb.jsx"},{"name":"DeltaBar","sourcePath":"components/instrument/DeltaBar.jsx"},{"name":"LevelSegments","sourcePath":"components/instrument/LevelSegments.jsx"},{"name":"NavTile","sourcePath":"components/instrument/NavTile.jsx"},{"name":"SegmentBar","sourcePath":"components/instrument/SegmentBar.jsx"},{"name":"SetupRow","sourcePath":"components/instrument/SetupRow.jsx"},{"name":"StatusRow","sourcePath":"components/instrument/StatusRow.jsx"},{"name":"CornerLine","sourcePath":"components/track/CornerLine.jsx"},{"name":"CornerNote","sourcePath":"components/track/CornerNote.jsx"},{"name":"ElevationProfile","sourcePath":"components/track/ElevationProfile.jsx"},{"name":"TrackMap","sourcePath":"components/track/TrackMap.jsx"}],"sourceHashes":{"components/brand/BrandMark.jsx":"06b9f1be34a5","components/core/Button.jsx":"6100af4b0777","components/core/Chip.jsx":"445c9b582bfd","components/core/Label.jsx":"005253c18f2b","components/core/Panel.jsx":"7138c9b1daec","components/core/StatusField.jsx":"1ab4ad523edc","components/core/Stepper.jsx":"cde549884a3e","components/core/Toast.jsx":"aedd4a0a0f6f","components/instrument/CommandVerb.jsx":"af7362cd0d4c","components/instrument/DeltaBar.jsx":"1d4cf3f55f3b","components/instrument/LevelSegments.jsx":"c3e5cc715f93","components/instrument/NavTile.jsx":"6dc3db6f3b6d","components/instrument/SegmentBar.jsx":"3db46cbbabff","components/instrument/SetupRow.jsx":"5c0d4475a56b","components/instrument/StatusRow.jsx":"cc1ac8c642b4","components/track/CornerLine.jsx":"b4ac447fbd64","components/track/CornerNote.jsx":"7f10a8eadd31","components/track/ElevationProfile.jsx":"c0682fa6bca6","components/track/TrackMap.jsx":"0c5eefa32217"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ACCopilotDesignSystem_bba7a8 = window.ACCopilotDesignSystem_bba7a8 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/brand/BrandMark.jsx
try { (() => {
/** SegMark — the brand atom: a short brass bar set before a wordmark/section. */
function SegMark({
  height = "var(--seg-mark-h)",
  width = "var(--seg-mark-w)",
  color = "var(--brass)",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      display: "inline-block",
      width,
      height,
      background: color,
      flex: "0 0 auto",
      ...style
    }
  });
}

/**
 * BrandMark — the RACING ATELIER identity lockup: the brass seg-mark + the
 * wordmark in tight Saira caps. The single recognisable house signature.
 */
function BrandMark({
  text = "RACING ATELIER",
  size = "md",
  color = "var(--chalk)",
  markHeight,
  style = {}
}) {
  const fs = {
    sm: 14,
    md: 18,
    lg: 22
  }[size] || 18;
  const mh = markHeight || fs + 4 + "px";
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 12,
      ...style
    }
  }, /*#__PURE__*/React.createElement(SegMark, {
    height: mh
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 800,
      fontSize: fs,
      letterSpacing: "0.16em",
      textTransform: "uppercase",
      color
    }
  }, text));
}

/**
 * CornerBracket — a single machined brass L. Place four (tl/tr/bl/br) inside a
 * positioned container, or use Panel's `brackets` prop. The house frame device.
 */
function CornerBracket({
  pos = "tl",
  color = "var(--brass)",
  size = 14,
  style = {}
}) {
  const m = {
    tl: {
      top: -1,
      left: -1,
      borderRight: 0,
      borderBottom: 0
    },
    tr: {
      top: -1,
      right: -1,
      borderLeft: 0,
      borderBottom: 0
    },
    bl: {
      bottom: -1,
      left: -1,
      borderRight: 0,
      borderTop: 0
    },
    br: {
      bottom: -1,
      right: -1,
      borderLeft: 0,
      borderTop: 0
    }
  }[pos];
  return /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      position: "absolute",
      width: size,
      height: size,
      border: "2px solid " + color,
      pointerEvents: "none",
      ...m,
      ...style
    }
  });
}
Object.assign(__ds_scope, { SegMark, BrandMark, CornerBracket });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/BrandMark.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — the instrument action. A flat field, square corners, tight bold
 * caps. `primary` is the single brass action; `ghost` is a hairline-bordered
 * secondary. Colour fields, never pills.
 */
function Button({
  children,
  variant = "field",
  // "field" | "primary" | "ghost"
  size = "md",
  // "sm" | "md" | "lg"
  block = false,
  disabled = false,
  iconLeft = null,
  style = {},
  ...rest
}) {
  const pads = {
    sm: "7px 12px",
    md: "11px 16px",
    lg: "0 20px"
  };
  const minH = {
    sm: 30,
    md: 40,
    lg: "var(--tap-min)"
  };
  const fs = {
    sm: 12,
    md: 14,
    lg: 15
  };
  const variants = {
    field: {
      background: "var(--raise)",
      color: "var(--chalk)",
      border: "1px solid var(--line-2)"
    },
    primary: {
      background: "var(--brass)",
      color: "var(--brass-ink)",
      border: "1px solid var(--brass)"
    },
    ghost: {
      background: "transparent",
      color: "var(--mute)",
      border: "1px solid var(--line-2)"
    }
  };
  const v = variants[variant] || variants.field;
  return /*#__PURE__*/React.createElement("button", _extends({
    disabled: disabled,
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 8,
      width: block ? "100%" : "auto",
      minHeight: minH[size],
      padding: pads[size],
      ...v,
      borderRadius: "var(--r)",
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: fs[size],
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      transition: "opacity var(--dur-press) var(--ease)",
      ...style
    },
    onMouseDown: e => {
      if (!disabled) e.currentTarget.style.opacity = "0.75";
    },
    onMouseUp: e => {
      if (!disabled) e.currentTarget.style.opacity = "1";
    },
    onMouseLeave: e => {
      if (!disabled) e.currentTarget.style.opacity = "1";
    }
  }, rest), iconLeft, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Chip.jsx
try { (() => {
/**
 * Chip — a compact mono data token (BB 54 · TC 2). Hairline square outline,
 * tabular. Tone colours the outline + text for state.
 */
function Chip({
  children,
  tone = "neutral",
  style = {}
}) {
  const colors = {
    neutral: {
      c: "var(--mute)",
      b: "var(--line-2)"
    },
    stop: {
      c: "var(--brake)",
      b: "rgba(242,59,44,0.4)"
    },
    warn: {
      c: "var(--lift)",
      b: "rgba(244,165,44,0.4)"
    },
    go: {
      c: "var(--clear)",
      b: "rgba(47,190,110,0.4)"
    },
    brass: {
      c: "var(--brass)",
      b: "rgba(200,152,62,0.5)"
    }
  };
  const t = colors[tone] || colors.neutral;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      fontFamily: "var(--font-mono)",
      fontSize: 10,
      fontVariantNumeric: "tabular-nums",
      color: t.c,
      border: "1px solid " + t.b,
      borderRadius: "var(--r)",
      padding: "1px 6px",
      whiteSpace: "nowrap",
      letterSpacing: "0.02em",
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Chip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Chip.jsx", error: String((e && e.message) || e) }); }

// components/core/Label.jsx
try { (() => {
/**
 * Label — the tight bold caps label. Saira Semi Condensed 600, NOT spaced-out
 * and thin. Use `tone` to colour it for state.
 */
function Label({
  children,
  size = "md",
  tone = "label",
  style = {}
}) {
  const fs = {
    md: 12,
    sm: 11,
    xs: 9
  };
  const colors = {
    label: "var(--mute)",
    dim: "var(--dim)",
    chalk: "var(--chalk)",
    brass: "var(--brass)",
    stop: "var(--brake)",
    warn: "var(--lift)",
    go: "var(--clear)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: fs[size] || 12,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: colors[tone] || colors.label,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Label });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Label.jsx", error: String((e && e.message) || e) }); }

// components/core/Panel.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Panel — the carbon instrument surface. Square, flat, edge border. `brackets`
 * adds the machined brass corner L's (the house frame). `glass` is the in-game
 * translucent variant (web/desktop only — never on the ESP32).
 */
function Panel({
  children,
  variant = "panel",
  brackets = false,
  pad = 0,
  style = {},
  ...rest
}) {
  const bg = {
    panel: "linear-gradient(180deg, var(--graphite), var(--carbon))",
    flat: "var(--graphite)",
    raised: "var(--slab)",
    glass: "var(--glass-fill)"
  }[variant];
  const isGlass = variant === "glass";
  const arm = pos => {
    const base = {
      position: "absolute",
      width: "var(--bracket)",
      height: "var(--bracket)",
      border: "var(--border-bracket)",
      pointerEvents: "none"
    };
    const m = {
      tl: {
        top: -1,
        left: -1,
        borderRight: 0,
        borderBottom: 0
      },
      tr: {
        top: -1,
        right: -1,
        borderLeft: 0,
        borderBottom: 0
      },
      bl: {
        bottom: -1,
        left: -1,
        borderRight: 0,
        borderTop: 0
      },
      br: {
        bottom: -1,
        right: -1,
        borderLeft: 0,
        borderTop: 0
      }
    }[pos];
    return /*#__PURE__*/React.createElement("span", {
      key: pos,
      style: {
        ...base,
        ...m
      }
    });
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      position: "relative",
      background: bg,
      border: "1px solid var(--edge)",
      borderRadius: "var(--r)",
      padding: pad,
      backdropFilter: isGlass ? "var(--glass-blur)" : undefined,
      WebkitBackdropFilter: isGlass ? "var(--glass-blur)" : undefined,
      boxShadow: isGlass ? "var(--shadow-glass)" : undefined,
      ...style
    }
  }, rest), brackets && ["tl", "tr", "bl", "br"].map(arm), children);
}
Object.assign(__ds_scope, { Panel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Panel.jsx", error: String((e && e.message) || e) }); }

// components/core/StatusField.jsx
try { (() => {
/**
 * StatusField — state as a flat colour FIELD plus the verbatim word, or a dot
 * + word for inline use. The loud, periphery-caught status treatment (the
 * launcher headline, a connection state). Colour carries meaning.
 */
const TONES = {
  go: {
    fill: "var(--clear)",
    ink: "#06140c",
    text: "var(--clear)"
  },
  warn: {
    fill: "var(--lift)",
    ink: "#1c1404",
    text: "var(--lift)"
  },
  stop: {
    fill: "var(--brake)",
    ink: "#fff",
    text: "var(--brake)"
  },
  idle: {
    fill: "var(--raise)",
    ink: "var(--mute)",
    text: "var(--dim)"
  },
  brass: {
    fill: "var(--brass)",
    ink: "var(--brass-ink)",
    text: "var(--brass)"
  }
};
function StatusField({
  children,
  tone = "go",
  variant = "field",
  style = {}
}) {
  const t = TONES[tone] || TONES.go;
  if (variant === "dot") {
    return /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        ...style
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: t.fill,
        flex: "0 0 auto"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-disp)",
        fontWeight: 700,
        fontSize: 13,
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        color: t.text
      }
    }, children));
  }
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      padding: "3px 9px",
      background: t.fill,
      color: t.ink,
      borderRadius: "var(--r)",
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 12,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { StatusField });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/StatusField.jsx", error: String((e && e.message) || e) }); }

// components/core/Stepper.jsx
try { (() => {
/**
 * Stepper — block −/+ adjust control for one parameter (brake bias, FOV…).
 * Big Saira readout value; square block buttons; optional fill bar showing the
 * value's position in range. Minus muted, plus brass.
 */
function Stepper({
  label,
  value,
  unit = "",
  fill = null,
  onDecrement,
  onIncrement,
  disabled = false,
  style = {}
}) {
  const btn = {
    fontFamily: "var(--font-disp)",
    fontWeight: 700,
    fontSize: 16,
    color: "var(--chalk)",
    background: "var(--raise)",
    border: 0,
    width: 30,
    height: 30,
    cursor: disabled ? "not-allowed" : "pointer",
    flex: "0 0 auto"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      opacity: disabled ? 0.4 : 1,
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 9
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, label != null && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 11,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--mute)"
    }
  }, label), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-read)",
      fontWeight: 700,
      fontSize: 24,
      fontVariantNumeric: "tabular-nums"
    }
  }, value), unit && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--mute)"
    }
  }, unit))), /*#__PURE__*/React.createElement("button", {
    "aria-label": "decrease",
    onClick: onDecrement,
    disabled: disabled,
    style: btn
  }, "\u2212"), /*#__PURE__*/React.createElement("button", {
    "aria-label": "increase",
    onClick: onIncrement,
    disabled: disabled,
    style: {
      ...btn,
      color: "var(--brass)"
    }
  }, "+")), fill != null && /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      background: "var(--raise)",
      marginTop: 8,
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: Math.max(0, Math.min(1, fill)) * 100 + "%",
      background: "var(--brass)"
    }
  })));
}
Object.assign(__ds_scope, { Stepper });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Stepper.jsx", error: String((e && e.message) || e) }); }

// components/core/Toast.jsx
try { (() => {
/**
 * Toast — brief acknowledgement / failure notice. A flat field bar with the
 * state word + one short line. Tone carries meaning.
 */
const TONES = {
  ok: "var(--clear)",
  error: "var(--brake)",
  info: "var(--mute)"
};
function Toast({
  children,
  tone = "info",
  title,
  style = {}
}) {
  const c = TONES[tone] || TONES.info;
  return /*#__PURE__*/React.createElement("div", {
    role: "status",
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 2,
      padding: "9px 12px",
      background: "var(--graphite)",
      borderLeft: "3px solid " + c,
      border: "1px solid var(--line-2)",
      borderRadius: "var(--r)",
      maxWidth: 300,
      ...style
    }
  }, title && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 11,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: c
    }
  }, title), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11.5,
      color: "var(--mute)",
      lineHeight: 1.4
    }
  }, children));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Toast.jsx", error: String((e && e.message) || e) }); }

// components/instrument/CommandVerb.jsx
try { (() => {
/**
 * CommandVerb — the one action, periphery-caught. Huge Saira Semi Condensed
 * caps in a signal colour, with an optional direction arrow. This is the
 * loudest thing on any cockpit surface; there is only ever one.
 */
const TONES = {
  stop: "var(--brake)",
  warn: "var(--lift)",
  go: "var(--clear)"
};
function CommandVerb({
  children,
  tone = "stop",
  arrow = null,
  size = 66,
  style = {}
}) {
  const c = TONES[tone] || TONES.stop;
  const arrows = {
    down: "▼",
    up: "▲",
    left: "◀",
    right: "▶"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 800,
      fontSize: size,
      lineHeight: 0.82,
      letterSpacing: "0.01em",
      textTransform: "uppercase",
      color: c
    }
  }, children), arrow && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: size * 0.42,
      lineHeight: 0.6,
      color: c
    }
  }, arrows[arrow] || arrow));
}
Object.assign(__ds_scope, { CommandVerb });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/CommandVerb.jsx", error: String((e && e.message) || e) }); }

// components/instrument/DeltaBar.jsx
try { (() => {
/**
 * DeltaBar — the bidirectional pace block + big number. A thick block grows
 * from a centre reference: right = too fast (stop), left = too slow (warn),
 * centred = on line (go). Direction and amount land in one glance.
 */
function DeltaBar({
  value = 0,
  max = 20,
  slack = 4,
  unit = "",
  refLabel,
  style = {}
}) {
  const v = Math.max(-max, Math.min(max, value));
  const tone = v > slack ? "var(--brake)" : v < -slack ? "var(--lift)" : "var(--clear)";
  const half = Math.abs(v) / max * 50;
  const left = v >= 0 ? 50 : 50 - half;
  return /*#__PURE__*/React.createElement("div", {
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      position: "relative",
      height: "var(--delta-h)",
      background: "var(--raise)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      left: "50%",
      top: -3,
      bottom: -3,
      width: 2,
      background: "var(--mute)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 0,
      bottom: 0,
      left: left + "%",
      width: half + "%",
      background: tone
    }
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-read)",
      fontWeight: 700,
      fontSize: 40,
      lineHeight: 0.8,
      color: tone,
      fontVariantNumeric: "tabular-nums",
      minWidth: 84,
      textAlign: "right"
    }
  }, v > 0 ? "+" : "", v)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 9,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--dim)"
    }
  }, "\u2212", max), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 10,
      color: "var(--dim)"
    }
  }, refLabel || "0", unit), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 9,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--dim)"
    }
  }, "+", max)));
}
Object.assign(__ds_scope, { DeltaBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/DeltaBar.jsx", error: String((e && e.message) || e) }); }

// components/instrument/LevelSegments.jsx
try { (() => {
/**
 * LevelSegments — a discrete level read as lit cells (TC 2, ABS 1, wings 4/8).
 * Chunky cells, brass when lit. The cockpit way to show a small integer.
 */
function LevelSegments({
  value = 0,
  max = 6,
  tone = "brass",
  style = {}
}) {
  const lit = {
    brass: "var(--brass)",
    go: "var(--clear)",
    warn: "var(--lift)"
  }[tone] || "var(--brass)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 3,
      alignItems: "center",
      ...style
    }
  }, Array.from({
    length: max
  }).map((_, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      width: "var(--level-w)",
      height: "var(--level-h)",
      background: i < value ? lit : "var(--raise)"
    }
  })));
}
Object.assign(__ds_scope, { LevelSegments });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/LevelSegments.jsx", error: String((e && e.message) || e) }); }

// components/instrument/NavTile.jsx
try { (() => {
/**
 * NavTile — an OLED rig launcher tile. Saira caps title, muted subtitle, brass
 * chevron. Square, edge border, 60px tap floor. `disabled` dims placeholders.
 */
function NavTile({
  title,
  subtitle,
  disabled = false,
  onClick,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: disabled ? undefined : onClick,
    disabled: disabled,
    style: {
      display: "flex",
      flexDirection: "column",
      gap: subtitle ? 6 : 0,
      justifyContent: "center",
      width: "100%",
      minHeight: "var(--tap-min)",
      padding: "13px 15px",
      textAlign: "left",
      background: "var(--graphite)",
      border: "1px solid var(--edge)",
      borderRadius: "var(--r)",
      cursor: disabled ? "default" : "pointer",
      opacity: disabled ? 0.45 : 1,
      transition: "border-color var(--dur-press) var(--ease)"
    },
    onMouseDown: e => {
      if (!disabled) e.currentTarget.style.borderColor = "var(--brass)";
    },
    onMouseUp: e => {
      e.currentTarget.style.borderColor = "var(--edge)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--edge)";
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      width: "100%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 15,
      letterSpacing: "0.05em",
      textTransform: "uppercase",
      color: "var(--chalk)"
    }
  }, title), /*#__PURE__*/React.createElement("span", {
    style: {
      color: disabled ? "var(--dim)" : "var(--brass)",
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 16
    }
  }, "\u203A")), subtitle && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 10.5,
      color: "var(--mute)"
    }
  }, subtitle));
}
Object.assign(__ds_scope, { NavTile });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/NavTile.jsx", error: String((e && e.message) || e) }); }

// components/instrument/SegmentBar.jsx
try { (() => {
/**
 * SegmentBar — the shift-light magnitude bar. Chunky gapped segments read as a
 * COUNT, never a continuous slider. Fill rises toward a trailing red `zone`;
 * the leading filled segment goes amber. Built for periphery, not precision.
 */
function SegmentBar({
  count = 12,
  fill = 0.5,
  zone = 0.34,
  height,
  style = {}
}) {
  const f = Math.max(0, Math.min(1, fill));
  const filledCount = Math.round(f * count);
  const zoneStart = count - Math.round(zone * count);
  const cells = [];
  for (let i = 0; i < count; i++) {
    const inZone = i >= zoneStart;
    const filled = i < filledCount;
    const leading = i === filledCount - 1;
    let bg = "var(--seg-off)";
    if (filled && inZone) bg = "var(--seg-red)";else if (filled && leading) bg = "var(--seg-amb)";else if (filled) bg = "var(--seg-lit)";else if (inZone) bg = "var(--seg-zone)";
    cells.push(/*#__PURE__*/React.createElement("span", {
      key: i,
      style: {
        flex: 1,
        background: bg
      }
    }));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "var(--seg-gap)",
      height: height || "var(--seg-h)",
      ...style
    }
  }, cells);
}
Object.assign(__ds_scope, { SegmentBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/SegmentBar.jsx", error: String((e && e.message) || e) }); }

// components/instrument/SetupRow.jsx
try { (() => {
/**
 * SetupRow — a saved setup in Pocket Technician. Name + best-lap meta + compact
 * chips. The loaded setup gets a brass left-marker and tinted band.
 */
function SetupRow({
  name,
  meta,
  chips = [],
  active = false,
  onClick,
  last = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      width: "100%",
      textAlign: "left",
      padding: "9px 8px",
      background: active ? "linear-gradient(90deg, rgba(200,152,62,0.10), transparent)" : "transparent",
      border: 0,
      borderLeft: active ? "2px solid var(--brass)" : "2px solid transparent",
      borderBottom: last ? "none" : "1px solid var(--line)",
      cursor: "pointer",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 13,
      letterSpacing: "0.03em",
      textTransform: "uppercase",
      color: "var(--chalk)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, name), meta && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 9.5,
      color: "var(--dim)"
    }
  }, meta)), chips.map((c, i) => /*#__PURE__*/React.createElement(__ds_scope.Chip, {
    key: i,
    tone: c.tone
  }, c.text)));
}
Object.assign(__ds_scope, { SetupRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/SetupRow.jsx", error: String((e && e.message) || e) }); }

// components/instrument/StatusRow.jsx
try { (() => {
/**
 * StatusRow — one Game Point launcher line: tight-caps label, the verbatim
 * probe word coloured by tone, and a muted mono detail. Maps 1:1 to a
 * GamePointStatus field.
 */
const TONES = {
  go: "var(--clear)",
  warn: "var(--lift)",
  stop: "var(--brake)",
  idle: "var(--dim)",
  info: "var(--chalk)"
};
function StatusRow({
  label,
  state,
  tone = "idle",
  detail,
  last = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "11px 0",
      borderBottom: last ? "none" : "1px solid var(--line)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 96,
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 12,
      letterSpacing: "0.1em",
      textTransform: "uppercase",
      color: "var(--mute)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 13,
      letterSpacing: "0.04em",
      textTransform: "uppercase",
      color: TONES[tone] || TONES.idle
    }
  }, state), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--dim)"
    }
  }, detail));
}
Object.assign(__ds_scope, { StatusRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/instrument/StatusRow.jsx", error: String((e && e.message) || e) }); }

// components/track/CornerLine.jsx
try { (() => {
/**
 * CornerLine — one row in a corner list: mono id, Saira caps name, and a right-
 * aligned note. The compact Track Atlas index.
 */
function CornerLine({
  id,
  name,
  note,
  last = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 9,
      alignItems: "baseline",
      padding: "7px 0",
      borderBottom: last ? "none" : "1px solid var(--line)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--brass)",
      minWidth: 36
    }
  }, id), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 700,
      fontSize: 13,
      letterSpacing: "0.03em",
      textTransform: "uppercase"
    }
  }, name), note && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--mute)",
      textAlign: "right"
    }
  }, note));
}
Object.assign(__ds_scope, { CornerLine });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/track/CornerLine.jsx", error: String((e && e.message) || e) }); }

// components/track/CornerNote.jsx
try { (() => {
/**
 * CornerNote — the "now entering" pace-note panel: the corner read large with
 * its gear / minimum speed / throttle as big tabular readouts, and one line of
 * coaching. The Track Atlas's focal instrument.
 */
function CornerNote({
  eyebrow = "Now entering",
  id,
  name,
  gear,
  minSpeed,
  throttle,
  note,
  style = {}
}) {
  const stat = (label, value, color) => /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 9,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--dim)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-read)",
      fontWeight: 700,
      fontSize: 26,
      fontVariantNumeric: "tabular-nums",
      color: color || "var(--chalk)"
    }
  }, value));
  return /*#__PURE__*/React.createElement("div", {
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 600,
      fontSize: 11,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--brake)"
    }
  }, eyebrow, id ? " · " + id : ""), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-disp)",
      fontWeight: 800,
      fontSize: 34,
      letterSpacing: "0.01em",
      textTransform: "uppercase",
      marginTop: 6
    }
  }, name), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 16,
      marginTop: 12
    }
  }, gear != null && stat("gear", gear), minSpeed != null && stat("min speed", minSpeed), throttle != null && stat("throttle", throttle + "%", "var(--clear)")), note && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11.5,
      color: "var(--mute)",
      lineHeight: 1.6,
      marginTop: 14,
      borderTop: "1px solid var(--line)",
      paddingTop: 12
    }
  }, note));
}
Object.assign(__ds_scope, { CornerNote });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/track/CornerNote.jsx", error: String((e && e.message) || e) }); }

// components/track/ElevationProfile.jsx
try { (() => {
/**
 * ElevationProfile — the climb, drawn as a polyline. A nuance most dashes drop;
 * for tracks like Spa the elevation IS the character. Pass `points` as an SVG
 * polyline string; mark the key crest.
 */
function ElevationProfile({
  points,
  viewBox = "0 0 320 56",
  peakX,
  peakLabel,
  startLabel,
  endLabel,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: viewBox,
    fill: "none",
    style: {
      display: "block",
      width: "100%",
      ...style
    }
  }, /*#__PURE__*/React.createElement("polyline", {
    points: points,
    stroke: "var(--chalk)",
    strokeWidth: "2",
    fill: "none"
  }), peakX != null && /*#__PURE__*/React.createElement("line", {
    x1: peakX,
    y1: "8",
    x2: peakX,
    y2: "52",
    stroke: "var(--brake)",
    strokeWidth: "1.4",
    strokeDasharray: "3 3"
  }), peakLabel && /*#__PURE__*/React.createElement("text", {
    x: (peakX || 0) - 24,
    y: "9",
    fontFamily: "Spline Sans Mono",
    fontSize: "8",
    fill: "var(--brake)"
  }, peakLabel), startLabel && /*#__PURE__*/React.createElement("text", {
    x: "0",
    y: "54",
    fontFamily: "Spline Sans Mono",
    fontSize: "8",
    fill: "var(--dim)"
  }, startLabel), endLabel && /*#__PURE__*/React.createElement("text", {
    x: "262",
    y: "54",
    fontFamily: "Spline Sans Mono",
    fontSize: "8",
    fill: "var(--dim)"
  }, endLabel));
}
Object.assign(__ds_scope, { ElevationProfile });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/track/ElevationProfile.jsx", error: String((e && e.message) || e) }); }

// components/track/TrackMap.jsx
try { (() => {
/**
 * TrackMap — a schematic circuit line drawn from an SVG path. Generic: pass any
 * track's `path` (d string), optional `highlight` sub-path (red), corner
 * `markers`, a pulsing `here` position, and `labels`. The geometry is data, not
 * decoration — drive it from a real circuit dataset.
 */
function TrackMap({
  path,
  viewBox = "0 0 290 150",
  highlight,
  markers = [],
  here = null,
  labels = [],
  stroke = "var(--chalk)",
  strokeWidth = 2.4,
  opacity = 1,
  style = {}
}) {
  const toneColor = t => ({
    stop: "var(--brake)",
    warn: "var(--lift)",
    go: "var(--clear)",
    data: "var(--data)",
    house: "var(--brass)",
    chalk: "var(--chalk)"
  })[t] || "var(--brass)";
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: viewBox,
    fill: "none",
    style: {
      display: "block",
      width: "100%",
      height: "auto",
      ...style
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: path,
    stroke: stroke,
    strokeWidth: strokeWidth,
    strokeLinejoin: "round",
    opacity: opacity
  }), highlight && /*#__PURE__*/React.createElement("path", {
    d: highlight,
    stroke: "var(--brake)",
    strokeWidth: strokeWidth + 0.6,
    strokeLinecap: "round"
  }), markers.map((m, i) => /*#__PURE__*/React.createElement("circle", {
    key: i,
    cx: m.x,
    cy: m.y,
    r: m.r || 3,
    fill: toneColor(m.tone)
  })), here && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: here.x,
    cy: here.y,
    r: "5",
    fill: "var(--brake)"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: here.x,
    cy: here.y,
    r: "9",
    fill: "none",
    stroke: "var(--brake)",
    strokeWidth: "1.4",
    opacity: "0.6"
  })), labels.map((l, i) => /*#__PURE__*/React.createElement("text", {
    key: i,
    x: l.x,
    y: l.y,
    fontFamily: "Spline Sans Mono",
    fontSize: l.size || 8,
    fill: toneColor(l.tone || "chalk")
  }, l.text)));
}
Object.assign(__ds_scope, { TrackMap });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/track/TrackMap.jsx", error: String((e && e.message) || e) }); }

__ds_ns.SegMark = __ds_scope.SegMark;

__ds_ns.BrandMark = __ds_scope.BrandMark;

__ds_ns.CornerBracket = __ds_scope.CornerBracket;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Chip = __ds_scope.Chip;

__ds_ns.Label = __ds_scope.Label;

__ds_ns.Panel = __ds_scope.Panel;

__ds_ns.StatusField = __ds_scope.StatusField;

__ds_ns.Stepper = __ds_scope.Stepper;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.CommandVerb = __ds_scope.CommandVerb;

__ds_ns.DeltaBar = __ds_scope.DeltaBar;

__ds_ns.LevelSegments = __ds_scope.LevelSegments;

__ds_ns.NavTile = __ds_scope.NavTile;

__ds_ns.SegmentBar = __ds_scope.SegmentBar;

__ds_ns.SetupRow = __ds_scope.SetupRow;

__ds_ns.StatusRow = __ds_scope.StatusRow;

__ds_ns.CornerLine = __ds_scope.CornerLine;

__ds_ns.CornerNote = __ds_scope.CornerNote;

__ds_ns.ElevationProfile = __ds_scope.ElevationProfile;

__ds_ns.TrackMap = __ds_scope.TrackMap;

})();
