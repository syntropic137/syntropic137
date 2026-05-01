/**
 * Date and time formatting utilities.
 */

/**
 * Format an ISO timestamp to a locale time string (e.g. "1:23:45 PM"), or the browser default.
 */
export function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString()
}

/**
 * Format an ISO date string to a full locale date+time string, or '\u2014' if null/empty.
 */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '\u2014'
  return new Date(dateStr).toLocaleString()
}

/**
 * Format an ISO timestamp to a compact locale string (Mon DD, HH:MM:SS), or '\u2014' if null/empty.
 */
export function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '\u2014'
  const d = new Date(ts)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * Format a duration in seconds as "Xh Ym Zs" or shorter forms.
 */
export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return '\u2014'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  const remainMins = mins % 60
  return remainMins > 0 ? `${hours}h ${remainMins}m` : `${hours}h`
}

/**
 * Format a duration between two ISO timestamps (or now) as a human-readable string.
 * Returns '\u2014' if startedAt is null.
 */
export function formatDurationFromRange(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
  now?: number,
): string {
  if (!startedAt) return '\u2014'
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : (now ?? Date.now())
  return formatDurationSeconds((end - start) / 1000)
}

/**
 * Format an ISO timestamp as a relative time ("4m ago", "in 2m", "just now").
 * Returns '\u2014' if iso is null/empty. Pass `now` for deterministic tests.
 *
 * Client-side rendering keeps the string current to wall-clock time without the
 * server needing to know when the response will be displayed.
 */
export function formatRelativeTime(iso: string | null | undefined, now?: number): string {
  if (!iso) return '\u2014'
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return '\u2014'
  const diffMs = (now ?? Date.now()) - ts
  const past = diffMs >= 0
  const absSeconds = Math.abs(diffMs) / 1000
  if (absSeconds < 5) return 'just now'

  const units: Array<[number, string]> = [
    [60, 's'],
    [60, 'm'],
    [24, 'h'],
    [7, 'd'],
    [Number.POSITIVE_INFINITY, 'w'],
  ]
  let value = absSeconds
  let unit = 's'
  for (const [step, label] of units) {
    if (value < step) {
      unit = label
      break
    }
    value /= step
    unit = label
  }
  const rounded = Math.max(1, Math.round(value))
  return past ? `${rounded}${unit} ago` : `in ${rounded}${unit}`
}

/**
 * Format an ISO timestamp into the user's locale + time zone.
 *
 * Server returns ISO 8601 UTC; the browser is the only place that knows where
 * the viewer actually is, so locale/time-zone formatting belongs here.
 */
export function formatTimestampLocale(iso: string | null | undefined): string {
  if (!iso) return '\u2014'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '\u2014'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(d)
}
