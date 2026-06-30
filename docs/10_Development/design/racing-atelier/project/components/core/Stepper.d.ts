import * as React from "react";
/**
 * Block −/+ adjust control for one parameter. Big Saira value, square block
 * buttons, optional fill bar (0..1) showing position in range.
 */
export interface StepperProps {
  label?: React.ReactNode;
  value: React.ReactNode;
  unit?: string;
  /** Fill fraction 0..1 for the position bar; omit to hide. */
  fill?: number | null;
  onDecrement?: () => void;
  onIncrement?: () => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}
export function Stepper(props: StepperProps): JSX.Element;
