import { UNKNOWN, toTime } from './shared'

/**
 * Whole-unit duration from milliseconds: "0s", "8s", "3m 47s", "1h 4m", "2d 3h".
 * Two units at most; the smaller is dropped when zero ("4m", "2h").
 */
export function formatDuration(ms: number | null | undefined): string {
  if (!isValidMs(ms)) return UNKNOWN
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total}s`
  const totalMin = Math.floor(total / 60)
  if (totalMin < 60) return twoUnits(totalMin, 'm', total % 60, 's')
  const totalH = Math.floor(totalMin / 60)
  if (totalH < 24) return twoUnits(totalH, 'h', totalMin % 60, 'm')
  return twoUnits(Math.floor(totalH / 24), 'd', totalH % 24, 'h')
}

function isValidMs(ms: number | null | undefined): ms is number {
  return ms !== null && ms !== undefined && Number.isFinite(ms) && ms >= 0
}

/** "3m 47s", or "4m" when the smaller unit is zero. */
function twoUnits(big: number, bigUnit: string, small: number, smallUnit: string): string {
  return small ? `${big}${bigUnit} ${small}${smallUnit}` : `${big}${bigUnit}`
}

/** Same as formatDuration, from seconds (the API's `duration_seconds`). */
export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return UNKNOWN
  return formatDuration(seconds * 1000)
}

/**
 * Sub-minute precision for tool calls and phases: "340ms", "24.3s", then
 * falls back to formatDuration ("3m 47s").
 */
export function formatDurationPrecise(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return UNKNOWN
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return formatDuration(ms)
}

/**
 * Milliseconds between two timestamps; an open end uses `now` (a running
 * thing). Null when the start is unknown or the range is negative.
 */
export function durationBetween(
  start: string | number | Date | null | undefined,
  end: string | number | Date | null | undefined,
  now: number = Date.now(),
): number | null {
  const s = toTime(start)
  if (s === null) return null
  const e = end === null || end === undefined ? now : toTime(end)
  if (e === null || e < s) return null
  return e - s
}
