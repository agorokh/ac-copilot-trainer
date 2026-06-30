import * as React from "react";
/**
 * State as a flat colour field + verbatim word (`field`), or a dot + word
 * (`dot`). The periphery-caught status treatment. Colour = meaning.
 */
export interface StatusFieldProps {
  children?: React.ReactNode;
  /** @default "go" */
  tone?: "go" | "warn" | "stop" | "idle" | "brass";
  /** @default "field" */
  variant?: "field" | "dot";
  style?: React.CSSProperties;
}
export function StatusField(props: StatusFieldProps): JSX.Element;
