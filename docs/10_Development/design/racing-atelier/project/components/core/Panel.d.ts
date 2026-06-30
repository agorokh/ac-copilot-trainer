import * as React from "react";
/**
 * The carbon instrument surface. Square, flat, edge border. `brackets` adds
 * the machined brass corner L's; `glass` is the in-game translucent variant
 * (web/desktop only, never on the ESP32).
 */
export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode;
  /** @default "panel" */
  variant?: "panel" | "flat" | "raised" | "glass";
  /** Machined brass corner brackets. @default false */
  brackets?: boolean;
  pad?: number | string;
}
export function Panel(props: PanelProps): JSX.Element;
