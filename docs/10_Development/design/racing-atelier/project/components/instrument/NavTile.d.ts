import * as React from "react";
/**
 * An OLED rig launcher tile: Saira caps title, muted subtitle, brass chevron.
 * Square, 60px tap floor. `disabled` dims placeholders.
 */
export interface NavTileProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
}
export function NavTile(props: NavTileProps): JSX.Element;
