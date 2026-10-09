/**
 * Brand visuals of the landing hero, shared with the app: the S mark and
 * the run city. Geometry lives in geometry/sMark.ts and geometry/isoCity.ts.
 */
import type { CityFill } from '../geometry/isoCity'
import type { SkylineDay } from '../geometry/skyline'

export interface SMarkProps {
  /** Width of the mark: a number is pixels, a string any CSS length ("15%", "2rem"). Default: the container width. */
  size?: number | string
  /** Drop the cubes in one by one (motion.css sky-sdrop); static when false or with reduced motion. */
  animate?: boolean
  /** Accessible name (default "Syntropic137"); "" makes the mark decorative. */
  label?: string
}

export interface IsoCityProps {
  /** Per-day activity, oldest first (the Overview skyline's series); the last cols * rows are shown. */
  days: readonly SkylineDay[]
  /** Block indexes to show as running now (they pulse a few times). */
  live?: readonly number[]
  /** Block indexes with failed runs (they flash twice). */
  failed?: readonly number[]
  /** Block indexes with scorer errors or mixed outcomes (amber). */
  errored?: readonly number[]
  /** Blocks rise into place, back to front. */
  animate?: boolean
  /** The whole city drifts and zooms once (30s). */
  drift?: boolean
  /** Quiet days: 'glass' fades the whole block (default, the board), 'solid' keeps it opaque and darkens its faces. */
  fill?: CityFill
  /** Grid size and cell width in viewBox units (default 26 x 11, 36: the desktop hero). */
  cols?: number
  rows?: number
  cell?: number
  /** Sessions that count as full height (default: the busiest day shown). */
  maxSessions?: number
  /** Accessible name. */
  label?: string
}
