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
 * Format a cost that may be incomplete because some observations had no rate.
 *
 * A cost of $0.00 is ambiguous: it can mean "this really was free" or "we could
 * not price the model that ran". Rendering the second case as a dollar figure is
 * how unpriced codex runs looked identical to free ones (#890).
 *
 * `unpricedCount > 0` means the total omits real work, so show it as partial
 * rather than as a number a reader would trust. Mirrors `format_cost` in
 * syn_shared.display and `formatCostWithCoverage` in the CLI, so all three
 * surfaces render the same three states.
 */
export function formatCostWithCoverage(
  value: number | string,
  unpricedCount: number | undefined | null
): string {
  const n = typeof value === 'string' ? Number(value) : value

  // A malformed cost must never be laundered into a confident label. `!NaN` is
  // true, so a naive falsy check would render "not-a-number" as "unpriced".
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 0) return 'unknown'

  if (!unpricedCount) return formatCost(n)
  // Nothing could be priced at all.
  if (n === 0) return 'unpriced'
  // Some priced, some not: the figure is a real lower bound, not the total.
  return `\u2265${formatCost(n)} (partial)`
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

/** Token counts split into the four disjoint buckets the API reports. */
export interface TokenBreakdown {
  inputTokens: number
  outputTokens: number
  cacheCreationTokens: number
  cacheReadTokens: number
}

/**
 * Render a token breakdown whose parts add up to the total shown beside it.
 *
 * Cache tokens routinely account for over 90% of volume, so an "in / out"
 * sublabel beneath a total reads as though most of the tokens went missing.
 * The cached segment is omitted only when there genuinely was no cache
 * activity, never merely to shorten the label.
 */
export function formatTokenBreakdown(breakdown: TokenBreakdown): string {
  const cached = breakdown.cacheCreationTokens + breakdown.cacheReadTokens
  const segments = [
    `${formatTokens(breakdown.inputTokens)} in`,
    `${formatTokens(breakdown.outputTokens)} out`,
  ]
  if (cached > 0) {
    segments.push(`${formatTokens(cached)} cached`)
  }
  return segments.join(' / ')
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
  liveDurationSeconds,
} from './dateFormatters'
