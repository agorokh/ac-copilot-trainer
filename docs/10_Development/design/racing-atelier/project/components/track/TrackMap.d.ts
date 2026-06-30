import * as React from "react";
export interface TrackMarker { x: number; y: number; r?: number; tone?: "stop" | "warn" | "go" | "data" | "house" | "chalk"; }
export interface TrackLabel { x: number; y: number; text: string; size?: number; tone?: string; }
/**
 * A schematic circuit line from an SVG path. Generic — pass any track's `path`,
 * an optional red `highlight` sub-path, corner `markers`, a pulsing `here`
 * position, and `labels`. Geometry is data; drive it from a real dataset.
 * @startingPoint section="Track" subtitle="Schematic circuit map" viewport="420x240"
 */
export interface TrackMapProps {
  path: string;
  viewBox?: string;
  highlight?: string;
  markers?: TrackMarker[];
  here?: { x: number; y: number } | null;
  labels?: TrackLabel[];
  stroke?: string;
  strokeWidth?: number;
  opacity?: number;
  style?: React.CSSProperties;
}
export function TrackMap(props: TrackMapProps): JSX.Element;
