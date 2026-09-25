/**
 * Exact arithmetic on USD amounts the API sends as decimal strings.
 *
 * Costs arrive as decimal strings ("0.43809100000000005") precisely so that no
 * layer has to round them. Parsing them into JS floats and subtracting undoes
 * that: `0.43809100000000005 - (0.30566780000000005 + 0.1324232)` is ~1e-17,
 * not 0, and a card that shows "whatever the rows do not account for" then
 * renders a phantom "$0.000000" row for money that does not exist.
 *
 * So amounts are converted to an integer count of atto-dollars (1e-18 USD) as a
 * BigInt, added and subtracted exactly, and only turned back into a number at
 * the edge where something needs to draw it.
 */

/** Digits kept after the decimal point. 18 covers every float repr the API emits. */
const SCALE = 18
const ONE = 10n ** BigInt(SCALE)

/** An exact USD amount, in atto-dollars (1e-18 USD). */
export type ExactUsd = bigint

const DECIMAL_RE = /^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/

/**
 * Parse a decimal string (or a number, via its shortest repr) into atto-dollars.
 *
 * Returns null for anything that is not a finite decimal, so a malformed cost
 * is never silently read as 0. Digits beyond the 18th decimal place are rounded
 * half away from zero.
 */
export function parseExactUsd(value: string | number): ExactUsd | null {
  if (typeof value === 'number' && !Number.isFinite(value)) return null
  const match = DECIMAL_RE.exec(String(value).trim())
  if (!match) return null
  const [, sign, intPart = '', fracPart = '', expPart] = match
  if (intPart === '' && fracPart === '') return null

  const digits = `${intPart}${fracPart}`.replace(/^0+(?=\d)/, '') || '0'
  // Position of the decimal point, counted in digits from the right.
  const exponent = (expPart ? Number.parseInt(expPart, 10) : 0) - fracPart.length
  const units = scaleToAtto(BigInt(digits), exponent + SCALE)
  return sign === '-' ? -units : units
}

/** `digits * 10^shift`, rounding half away from zero when `shift` is negative. */
function scaleToAtto(digits: bigint, shift: number): ExactUsd {
  if (shift >= 0) return digits * 10n ** BigInt(shift)
  const divisor = 10n ** BigInt(-shift)
  const rounded = (digits % divisor) * 2n >= divisor ? 1n : 0n
  return digits / divisor + rounded
}

/** Sum of exact amounts. */
export function sumExactUsd(values: Iterable<ExactUsd>): ExactUsd {
  let total = 0n
  for (const v of values) total += v
  return total
}

/** Back to a plain number, for widths, percentages and `formatCost`. */
export function exactUsdToNumber(value: ExactUsd): number {
  // Via the decimal string, so the result is the nearest double to the exact
  // value rather than the product of two already-rounded conversions.
  return Number(exactUsdToString(value))
}

/** Canonical decimal string ("0.438091"), no float noise, no trailing zeros. */
export function exactUsdToString(value: ExactUsd): string {
  const negative = value < 0n
  const abs = negative ? -value : value
  const whole = abs / ONE
  const frac = (abs % ONE).toString().padStart(SCALE, '0').replace(/0+$/, '')
  return `${negative ? '-' : ''}${whole}${frac ? `.${frac}` : ''}`
}

/**
 * The smallest amount `formatCost` can show as non-zero.
 *
 * It prints sub-cent values to 6 decimal places, so anything under half a
 * micro-dollar rounds to "$0.000000" - a row that says nothing.
 */
export const COST_DISPLAY_RESOLUTION: ExactUsd = ONE / 1_000_000n / 2n

/** Whether an amount would render as something other than zero. */
export function isVisibleCost(value: ExactUsd): boolean {
  return value >= COST_DISPLAY_RESOLUTION
}
