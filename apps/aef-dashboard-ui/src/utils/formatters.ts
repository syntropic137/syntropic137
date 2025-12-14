/**
 * Shared formatting utilities for cost tracking components.
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
