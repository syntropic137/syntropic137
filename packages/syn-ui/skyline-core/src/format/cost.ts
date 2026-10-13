import { UNKNOWN, toNumber } from './shared'

const grouped = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/**
 * Compact USD for rows and headers: "$0.33", "$1,204.50", "<$0.01", "$0.00".
 * Accepts the API's Decimal strings. Negative or unparseable -> em dash.
 */
export function formatCost(value: number | string | null | undefined): string {
  const n = toNumber(value)
  if (n === null || n < 0) return UNKNOWN
  if (n === 0) return '$0.00'
  if (n < 0.01) return '<$0.01'
  return `$${grouped.format(n)}`
}

/**
 * Precise USD for detail views (ports the React app's formatCost):
 * < $0.01 six decimals, < $1 four decimals ("$0.0798"), else two.
 */
export function formatCostPrecise(value: number | string | null | undefined): string {
  const n = toNumber(value)
  if (n === null || n < 0) return UNKNOWN
  if (n < 0.01) return `$${n.toFixed(6)}`
  if (n < 1) return `$${n.toFixed(4)}`
  return `$${grouped.format(n)}`
}

/**
 * A cost that may be incomplete because some observations had no rate (#890).
 * unpriced 0 -> the cost; all unpriced -> "unpriced"; some -> "≥$0.21 (partial)".
 */
export function formatCostWithCoverage(
  value: number | string | null | undefined,
  unpricedCount: number | null | undefined,
  format: (v: number) => string = formatCost,
): string {
  const n = toNumber(value)
  if (n === null || n < 0) return 'unknown'
  if (!unpricedCount) return format(n)
  if (n === 0) return 'unpriced'
  return `≥${format(n)} (partial)`
}

/**
 * Quality per dollar for ranking verifiers: score 87 at $0.52 a run ->
 * "168 pts/$". Unknown, zero or negative cost -> em dash.
 */
export function pointsPerDollar(score: number | string | null | undefined, costUsd: number | string | null | undefined): string {
  const per = pointsPerDollarValue(score, costUsd)
  return per === null ? UNKNOWN : `${Math.round(per)} pts/$`
}

/** The number behind pointsPerDollar(), for sorting; null when it can't be computed. */
export function pointsPerDollarValue(score: number | string | null | undefined, costUsd: number | string | null | undefined): number | null {
  const s = toNumber(score)
  const c = toNumber(costUsd)
  return s === null || c === null || c <= 0 ? null : s / c
}
