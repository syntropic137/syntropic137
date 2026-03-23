/**
 * Date and time formatting utilities.
 */

/**
 * Format an ISO timestamp to HH:MM:SS local time.
 */
export function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString()
}

/**
 * Format an ISO date string to a locale date string, or '\u2014' if null/empty.
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
