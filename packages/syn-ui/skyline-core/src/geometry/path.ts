export type Point = readonly [x: number, y: number]

/** Round to 2 decimals so SVG paths stay short and stable in snapshots. */
export function round2(v: number): number {
  return Math.round(v * 100) / 100
}

/** Closed SVG path through the points: "M0,0L10,0L10,10Z". Empty input -> "". */
export function polygonPath(points: readonly Point[]): string {
  if (points.length === 0) return ''
  return 'M' + points.map(([x, y]) => `${round2(x)},${round2(y)}`).join('L') + 'Z'
}

/** SVG `points` attribute for <polygon>: "0,0 10,0 10,10". */
export function polygonPoints(points: readonly Point[]): string {
  return points.map(([x, y]) => `${round2(x)},${round2(y)}`).join(' ')
}
