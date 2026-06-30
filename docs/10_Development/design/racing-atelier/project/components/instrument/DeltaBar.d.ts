import * as React from "react";
/**
 * The bidirectional pace block + big number. A thick block grows from a centre
 * reference: right = too fast (stop), left = too slow (warn), centred = on line.
 */
export interface DeltaBarProps {
  /** Signed delta (e.g. current - reference). @default 0 */
  value?: number;
  /** Scale half-range. @default 20 */
  max?: number;
  /** Tolerance band for "on line" (go). @default 4 */
  slack?: number;
  unit?: string;
  /** Centre label, e.g. "182 km/h ref". */
  refLabel?: React.ReactNode;
  style?: React.CSSProperties;
}
export function DeltaBar(props: DeltaBarProps): JSX.Element;
