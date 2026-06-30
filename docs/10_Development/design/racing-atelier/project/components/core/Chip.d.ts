import * as React from "react";
/** Compact mono data token (BB 54 · TC 2). Hairline square, tabular. */
export interface ChipProps {
  children?: React.ReactNode;
  /** @default "neutral" */
  tone?: "neutral" | "stop" | "warn" | "go" | "brass";
  style?: React.CSSProperties;
}
export function Chip(props: ChipProps): JSX.Element;
