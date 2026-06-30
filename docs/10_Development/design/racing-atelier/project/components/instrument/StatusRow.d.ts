import * as React from "react";
/**
 * One launcher status line: tight-caps label, verbatim probe word (tone-
 * coloured), muted mono detail. Maps 1:1 to a GamePointStatus field.
 */
export interface StatusRowProps {
  label: React.ReactNode;
  state: React.ReactNode;
  /** @default "idle" */
  tone?: "go" | "warn" | "stop" | "idle" | "info";
  detail?: React.ReactNode;
  last?: boolean;
  style?: React.CSSProperties;
}
export function StatusRow(props: StatusRowProps): JSX.Element;
