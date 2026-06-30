import * as React from "react";
/**
 * The "now entering" pace-note panel: corner read large + gear / min speed /
 * throttle readouts + one coaching line. The Track Atlas focal instrument.
 */
export interface CornerNoteProps {
  /** @default "Now entering" */
  eyebrow?: string;
  id?: React.ReactNode;
  name: React.ReactNode;
  gear?: React.ReactNode;
  minSpeed?: React.ReactNode;
  throttle?: React.ReactNode;
  note?: React.ReactNode;
  style?: React.CSSProperties;
}
export function CornerNote(props: CornerNoteProps): JSX.Element;
