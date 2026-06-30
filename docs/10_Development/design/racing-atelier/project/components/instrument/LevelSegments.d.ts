import * as React from "react";
/** A discrete level as lit cells (TC 2, ABS 1). Chunky cells, brass when lit. */
export interface LevelSegmentsProps {
  value?: number;
  /** Total cells. @default 6 */
  max?: number;
  /** @default "brass" */
  tone?: "brass" | "go" | "warn";
  style?: React.CSSProperties;
}
export function LevelSegments(props: LevelSegmentsProps): JSX.Element;
