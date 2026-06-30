import * as React from "react";
/** One row in a corner list: mono id, Saira caps name, right-aligned note. */
export interface CornerLineProps {
  id: React.ReactNode;
  name: React.ReactNode;
  note?: React.ReactNode;
  last?: boolean;
  style?: React.CSSProperties;
}
export function CornerLine(props: CornerLineProps): JSX.Element;
