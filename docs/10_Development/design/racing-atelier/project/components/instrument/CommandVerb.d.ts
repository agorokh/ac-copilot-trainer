import * as React from "react";
/**
 * The one action, periphery-caught: huge Saira caps in a signal colour with an
 * optional direction arrow. Only ever one per surface.
 * @startingPoint section="Instrument" subtitle="The big cockpit command word" viewport="700x180"
 */
export interface CommandVerbProps {
  children?: React.ReactNode;
  /** @default "stop" */
  tone?: "stop" | "warn" | "go";
  /** Direction arrow under the word. */
  arrow?: "down" | "up" | "left" | "right" | null;
  /** Font size in px. @default 66 */
  size?: number;
  style?: React.CSSProperties;
}
export function CommandVerb(props: CommandVerbProps): JSX.Element;
