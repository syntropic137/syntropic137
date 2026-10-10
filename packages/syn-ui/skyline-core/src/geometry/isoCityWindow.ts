/**
 * `isoCity({ weeks, window, offset })` (plan 4a): the Overview's scrolling
 * city in one call. Finds the window `offset` months back (isoCityScroll)
 * and lays it out (isoCityFloor): blocks per weekday row and tone, label
 * transforms, hit boxes, draw order far rows first.
 */
import { type IsoCityDims, type IsoCityFloorLayout, type IsoCityWeek, type IsoWeekdayAxis, ISO_CITY_DESKTOP, layoutIsoCityFloor } from './isoCityFloor'
import { type IsoCityHistory, type IsoCityWindowRange, windowRange } from './isoCityScroll'
import { dayFromMs } from './skyline'

export interface IsoCityWindowInput {
  /** The whole history, oldest first (isoCityWeeks()); the last week holds `today`. */
  weeks: readonly IsoCityWeek[]
  /** Weeks shown (default dims.win). */
  window?: number
  /** Months back (0 = latest). */
  offset: number
  /** Default: today (UTC). */
  today?: string
  dims?: IsoCityDims
  pad?: number
  selected?: string | null
  maxSessions?: number
  weekdayAxis?: IsoWeekdayAxis
  loadedFrom?: string | null
}

export interface IsoCityWindowLayout extends IsoCityFloorLayout {
  history: IsoCityHistory
  range: IsoCityWindowRange
}

export function isoCityWindow(input: IsoCityWindowInput): IsoCityWindowLayout {
  const dims = input.dims ?? ISO_CITY_DESKTOP
  const window = input.window ?? dims.win
  const today = input.today ?? dayFromMs(Date.now())
  const history: IsoCityHistory = { start: input.weeks[0]?.start ?? today, weeks: Math.max(1, input.weeks.length), today }
  const range = windowRange(history, window, input.offset)
  const floor = layoutIsoCityFloor({ weeks: input.weeks, first: range.first, window, today, dims, pad: input.pad, selected: input.selected, maxSessions: input.maxSessions, weekdayAxis: input.weekdayAxis, loadedFrom: input.loadedFrom })
  return { ...floor, history, range }
}
