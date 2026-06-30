import * as React from "react";
/** Tight bold caps label (Saira Semi Condensed 600). Tone colours it for state. */
export interface LabelProps {
  children?: React.ReactNode;
  /** @default "md" */
  size?: "md" | "sm" | "xs";
  /** @default "label" */
  tone?: "label" | "dim" | "chalk" | "brass" | "stop" | "warn" | "go";
  style?: React.CSSProperties;
}
export function Label(props: LabelProps): JSX.Element;
