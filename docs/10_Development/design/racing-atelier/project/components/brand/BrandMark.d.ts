import * as React from "react";

/** The brand atom: a short brass bar set before a wordmark/section. */
export interface SegMarkProps { height?: string; width?: string; color?: string; style?: React.CSSProperties; }
export function SegMark(props: SegMarkProps): JSX.Element;

/**
 * The RACING ATELIER identity lockup: brass seg-mark + wordmark in tight Saira
 * caps. The single recognisable house signature; drop it in any header.
 * @startingPoint section="Brand" subtitle="RACING ATELIER lockup + seg-mark" viewport="700x130"
 */
export interface BrandMarkProps {
  /** @default "RACING ATELIER" */
  text?: string;
  /** @default "md" */
  size?: "sm" | "md" | "lg";
  color?: string;
  markHeight?: string;
  style?: React.CSSProperties;
}
export function BrandMark(props: BrandMarkProps): JSX.Element;

/** A single machined brass corner L. Place four inside a positioned container. */
export interface CornerBracketProps {
  /** @default "tl" */
  pos?: "tl" | "tr" | "bl" | "br";
  color?: string;
  size?: number;
  style?: React.CSSProperties;
}
export function CornerBracket(props: CornerBracketProps): JSX.Element;
