import * as React from "react";
export interface SetupChip { text: React.ReactNode; tone?: "neutral" | "stop" | "warn" | "go" | "brass"; }
/**
 * A saved setup row: name + best-lap meta + compact chips. The loaded setup
 * gets a brass left-marker and tinted band.
 */
export interface SetupRowProps {
  name: React.ReactNode;
  meta?: React.ReactNode;
  chips?: SetupChip[];
  active?: boolean;
  onClick?: () => void;
  last?: boolean;
  style?: React.CSSProperties;
}
export function SetupRow(props: SetupRowProps): JSX.Element;
