import { UNKNOWN, toTime } from './shared'

type TimeInput = string | number | Date | null | undefined

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

export interface RelativeTimeOptions {
  /** Reference time in ms (default Date.now()); pass it for deterministic output. */
  now?: number
  /** IANA zone for the absolute fallback; default the runtime's zone. */
  timeZone?: string
}

/**
 * "just now", "5m ago", "1h ago", "3d ago", "2w ago"; beyond 5 weeks an
 * absolute date ("Sep 12", or "Sep 12, 2025" in another year). Future
 * times read "in 5m".
 */
export function formatRelativeTime(value: TimeInput, options: RelativeTimeOptions = {}): string {
  const t = toTime(value)
  if (t === null) return UNKNOWN
  const now = options.now ?? Date.now()
  const diff = now - t
  const abs = Math.abs(diff)
  if (abs < 45_000) return 'just now'
  const text = relativeSpan(abs)
  if (text === null) return formatDate(t, { now, timeZone: options.timeZone })
  return diff >= 0 ? `${text} ago` : `in ${text}`
}

/** Below each limit, the span is counted in that unit; beyond the last, null (absolute date). */
const RELATIVE_UNITS: readonly { below: number; count: (abs: number) => number; unit: string }[] = [
  { below: HOUR, count: (abs) => Math.max(1, Math.round(abs / MINUTE)), unit: 'm' },
  { below: DAY, count: (abs) => Math.floor(abs / HOUR), unit: 'h' },
  { below: WEEK, count: (abs) => Math.floor(abs / DAY), unit: 'd' },
  { below: 5 * WEEK, count: (abs) => Math.floor(abs / WEEK), unit: 'w' },
]

function relativeSpan(abs: number): string | null {
  const u = RELATIVE_UNITS.find((r) => abs < r.below)
  return u ? `${u.count(abs)}${u.unit}` : null
}

/** "Sep 12" in the current year, "Sep 12, 2025" otherwise. */
export function formatDate(value: TimeInput, options: RelativeTimeOptions = {}): string {
  const t = toTime(value)
  if (t === null) return UNKNOWN
  const zone = options.timeZone
  const year = (ms: number) => new Intl.DateTimeFormat('en-US', { year: 'numeric', timeZone: zone }).format(ms)
  const sameYear = year(t) === year(options.now ?? Date.now())
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
    timeZone: zone,
  }).format(t)
}

/** "Sep 12, 14:05" (24h). */
export function formatDateTime(value: TimeInput, options: { timeZone?: string } = {}): string {
  const t = toTime(value)
  if (t === null) return UNKNOWN
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: options.timeZone,
  }).format(t)
}

/** "14:05:09" (24h), for operation timelines. */
export function formatClock(value: TimeInput, options: { timeZone?: string } = {}): string {
  const t = toTime(value)
  if (t === null) return UNKNOWN
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    timeZone: options.timeZone,
  }).format(t)
}

/** ISO date key "2026-10-07" in the given zone (UTC by default): Skyline day buckets. */
export function dayKey(value: TimeInput, timeZone = 'UTC'): string | null {
  const t = toTime(value)
  if (t === null) return null
  return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone }).format(t)
}
