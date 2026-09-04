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
  // Non-finite covers the NaN that `new Date('garbage').getTime()` propagates
  // into every arithmetic caller below; negative covers a start recorded after
  // the end. Both are unknown durations, and both used to render as literal
  // "NaNh NaNm" or a minus sign rather than saying so.
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '\u2014'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  const remainMins = mins % 60
  return remainMins > 0 ? `${hours}h ${remainMins}m` : `${hours}h`
}

/**
 * The duration to show for something that may still be running.
 *
 * The server already resolves this (`resolve_duration_seconds` in
 * `syn_shared.display`) and its answer is authoritative. The only thing the
 * client adds is a value that ticks between polls, so a live phase visibly
 * advances instead of stepping once per refetch. When that live reading is not
 * a usable measurement -- an unparseable or future `startedAt` -- the server's
 * value is used, so the two never disagree about a defect.
 *
 * Returns null for a genuinely unknown duration. Never 0.
 */
export function liveDurationSeconds(
  isRunning: boolean,
  startedAt: string | null | undefined,
  recordedSeconds: number | null | undefined,
  now: number,
): number | null {
  if (isRunning && startedAt) {
    const elapsed = (now - new Date(startedAt).getTime()) / 1000
    if (Number.isFinite(elapsed) && elapsed >= 0) return elapsed
  }
  return recordedSeconds ?? null
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
