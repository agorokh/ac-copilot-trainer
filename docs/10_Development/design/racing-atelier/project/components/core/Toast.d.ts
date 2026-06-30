import * as React from "react";
/** Brief acknowledgement / failure notice. Flat field bar, state word + one line. */
export interface ToastProps {
  children?: React.ReactNode;
  /** @default "info" */
  tone?: "ok" | "error" | "info";
  title?: string;
  style?: React.CSSProperties;
}
export function Toast(props: ToastProps): JSX.Element;
