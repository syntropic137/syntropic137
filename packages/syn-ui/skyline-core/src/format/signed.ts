/**
 * Signed deltas: "+24 pts", "−$0.11", "±0 pts". The minus is a real minus
 * sign (U+2212), as everywhere in Skyline; zero reads "±".
 */
import { formatCost } from './cost'
import { UNKNOWN, toNumber } from './shared'

/** U+2212, the typographic minus. */
export const MINUS = '−'

/** "+" above zero, "−" below, "±" at zero. */
export function signOf(n: number): '+' | '−' | '±' {
  return n > 0 ? '+' : n < 0 ? MINUS : '±'
}

/** Sign plus `format` of the magnitude: formatSigned(-3, String) -> "−3". */
export function formatSigned(value: number | string | null | undefined, format: (magnitude: number) => string): string {
  const n = toNumber(value)
  return n === null ? UNKNOWN : `${signOf(n)}${format(Math.abs(n))}`
}

/** Score points, whole: 24 -> "+24 pts", -10 -> "−10 pts", 0 -> "±0 pts". */
export function formatSignedPoints(value: number | string | null | undefined): string {
  const n = toNumber(value)
  return n === null ? UNKNOWN : formatSigned(Math.round(n), (m) => `${m} pts`)
}

/** USD change: -0.11 -> "−$0.11", 0.11 -> "+$0.11" (formatCost of the magnitude). */
export function formatSignedCost(value: number | string | null | undefined): string {
  return formatSigned(value, formatCost)
}
