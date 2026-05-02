/**
 * Shared formatting utilities.
 *
 * Most numeric and currency formatting is now produced server-side as
 * `*_display` fields on API responses (see ADR-064); the locale-dependent
 * helpers below are the only formatting still owned by the client because the
 * server cannot know the viewer's locale or rendering time.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

/**
 * Format a cost value in USD with appropriate decimal precision.
 * - Values < $0.01: 6 decimal places
 * - Values < $1.00: 4 decimal places
 * - Values >= $1.00: 2 decimal places
 */
export function formatCost(value: number): string {
  if (value < 0.01) {
    return `$${value.toFixed(6)}`
  }
  if (value < 1) {
    return `$${value.toFixed(4)}`
  }
  return `$${value.toFixed(2)}`
}

/**
 * Format a duration in milliseconds to a human-readable string.
 * Returns ms, seconds, minutes, or hours depending on magnitude.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)}ms`
  }
  const seconds = ms / 1000
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`
  }
  const minutes = seconds / 60
  if (minutes < 60) {
    return `${minutes.toFixed(1)}m`
  }
  const hours = minutes / 60
  return `${hours.toFixed(1)}h`
}

/**
 * Format a token count with K/M suffixes for large values.
 */
export function formatTokens(count: number): string {
  if (count >= 1000000) {
    return `${(count / 1000000).toFixed(1)}M`
  }
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}K`
  }
  return String(count)
}

// Re-export date/time formatters for backwards compatibility
export {
  formatTime,
  formatDate,
  formatTimestamp,
  formatTimestampLocale,
  formatRelativeTime,
  formatDurationSeconds,
  formatDurationFromRange,
} from './dateFormatters'
