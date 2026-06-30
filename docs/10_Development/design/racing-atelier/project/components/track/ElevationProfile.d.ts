import * as React from "react";
/**
 * The climb drawn as a polyline. Pass `points` as an SVG polyline string and
 * mark the key crest with `peakX` / `peakLabel`.
 */
export interface ElevationProfileProps {
  points: string;
  viewBox?: string;
  peakX?: number;
  peakLabel?: string;
  startLabel?: string;
  endLabel?: string;
  style?: React.CSSProperties;
}
export function ElevationProfile(props: ElevationProfileProps): JSX.Element;
