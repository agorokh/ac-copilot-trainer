import * as React from "react";
/**
 * The shift-light magnitude bar: chunky gapped segments read as a count. Fill
 * rises toward a trailing red `zone`; the leading filled segment goes amber.
 */
export interface SegmentBarProps {
  /** @default 12 */
  count?: number;
  /** Fill fraction 0..1. @default 0.5 */
  fill?: number;
  /** Trailing red-zone fraction 0..1. @default 0.34 */
  zone?: number;
  height?: number | string;
  style?: React.CSSProperties;
}
export function SegmentBar(props: SegmentBarProps): JSX.Element;
