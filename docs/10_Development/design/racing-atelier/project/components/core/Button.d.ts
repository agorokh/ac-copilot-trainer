import * as React from "react";
/**
 * The instrument action button. Flat field, square, tight bold caps.
 * `primary` = the single brass action; `ghost` = hairline secondary.
 * @startingPoint section="Core" subtitle="Field / brass / ghost action buttons" viewport="700x140"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** @default "field" */
  variant?: "field" | "primary" | "ghost";
  /** @default "md" */
  size?: "sm" | "md" | "lg";
  block?: boolean;
  iconLeft?: React.ReactNode;
  children?: React.ReactNode;
}
export function Button(props: ButtonProps): JSX.Element;
