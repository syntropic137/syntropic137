import { UNKNOWN, toNumber } from './shared'

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

/**
 * Binary byte size with decimal-looking units, as the canvas shows them:
 * 211 -> "211 B", 2_970 -> "2.9 KB", 20_275 -> "19.8 KB", 1_572_864 -> "1.5 MB".
 */
export function formatBytes(value: number | string | null | undefined, digits = 1): string {
  const n = toNumber(value)
  if (n === null || n < 0) return UNKNOWN
  if (n < 1024) return `${Math.round(n)} B`
  let size = n
  let unit = 0
  while (size >= 1024 && unit < UNITS.length - 1) {
    size /= 1024
    unit++
  }
  // Rounding can reach 1024.0 of a unit; hand it up.
  if (Number(size.toFixed(digits)) >= 1024 && unit < UNITS.length - 1) {
    size /= 1024
    unit++
  }
  return `${size.toFixed(digits)} ${UNITS[unit]}`
}
