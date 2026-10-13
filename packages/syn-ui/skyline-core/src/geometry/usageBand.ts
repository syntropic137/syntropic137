/**
 * Usage Meter band (UsageMeter board): tokens by type as one extruded strip,
 * one segment per non-empty series, in series order.
 *
 * The SVG is drawn in a 1000 x 46 box and stretched to the container width
 * (preserveAspectRatio="none"), so segment widths are shares of 1000 minus
 * the extrusion depth and the gaps. A non-empty series never shrinks below
 * `minWidth`, so a 93-token input still shows.
 */
import { type FacePaths, obliqueBox } from './extrude'
import { shareWidths } from './phaseBlocks'
import { round2 } from './path'

export interface UsageBandDims {
  width: number
  height: number
  /** Extrusion depth. */
  dx: number
  dy: number
  gap: number
  minWidth: number
}

export const USAGE_BAND: UsageBandDims = { width: 1000, height: 46, dx: 16, dy: 12, gap: 4, minWidth: 8 }

export interface UsageBandSegment<K extends string = string> {
  key: K
  value: number
  /** Share of the total, 0..1. */
  share: number
  x: number
  width: number
  paths: FacePaths
}

export interface UsageBandLayout<K extends string = string> {
  viewBox: string
  segments: UsageBandSegment<K>[]
  total: number
}

export function layoutUsageBand<K extends string>(
  values: readonly { key: K; value: number | null | undefined }[],
  dims: UsageBandDims = USAGE_BAND,
): UsageBandLayout<K> {
  const live = values.filter((v): v is { key: K; value: number } => typeof v.value === 'number' && v.value > 0)
  const total = live.reduce((s, v) => s + v.value, 0)
  const available = dims.width - dims.dx - dims.gap * Math.max(0, live.length - 1)
  const widths = shareWidths(
    live.map((v) => v.value),
    available,
    dims.minWidth,
  )
  const front = dims.height - dims.dy
  let x = 0
  const segments = live.map((v, i) => {
    const width = widths[i]!
    const seg: UsageBandSegment<K> = {
      key: v.key,
      value: v.value,
      share: total > 0 ? v.value / total : 0,
      x: round2(x),
      width,
      paths: obliqueBox({ x, y: dims.height - 2, width, height: front - 2, dx: dims.dx, dy: dims.dy }),
    }
    x = round2(x + width + dims.gap)
    return seg
  })
  return { viewBox: `0 0 ${dims.width} ${dims.height}`, segments, total }
}
