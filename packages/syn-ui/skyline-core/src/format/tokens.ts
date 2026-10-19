import { UNKNOWN, toNumber } from './shared'

export interface FormatTokensOptions {
  /** Suffix case. Canvas data rows use lowercase "261.7k"; "K" matches the React app. */
  case?: 'lower' | 'upper'
  /** Decimals for the k tier (default 1) and the M/B tiers (default 2). */
  digits?: { k?: number; m?: number }
}

const TIERS = [
  { suffix: 'k', size: 1_000, key: 'k' as const },
  { suffix: 'M', size: 1_000_000, key: 'm' as const },
  { suffix: 'B', size: 1_000_000_000, key: 'm' as const },
]

/**
 * Compact token count: 950 -> "950", 261_734 -> "261.7k", 2_790_000 -> "2.79M".
 *
 * Each tier rounds first and hands the count up when that rounds to 1000 of
 * itself, so 999_960 prints "1.00M", never "1000.0k".
 */
export function formatTokens(count: number | string | null | undefined, options: FormatTokensOptions = {}): string {
  const n = toNumber(count)
  if (n === null || n < 0) return UNKNOWN
  if (n < 1000) return String(Math.round(n))
  const upper = options.case === 'upper'
  const last = TIERS.length - 1
  for (const [i, tier] of TIERS.entries()) {
    const digits = tier.key === 'k' ? (options.digits?.k ?? 1) : (options.digits?.m ?? 2)
    const scale = 10 ** digits
    const rounded = Math.round((n / tier.size) * scale) / scale
    if (rounded < 1000 || i === last) {
      const suffix = upper ? tier.suffix.toUpperCase() : tier.suffix
      return `${rounded.toFixed(digits)}${suffix}`
    }
  }
  return String(n)
}

/** The four disjoint token buckets the API reports. */
export interface TokenBreakdown {
  input: number
  output: number
  cacheWrite: number
  cacheRead: number
}

/** Series order and labels used by the Usage Meter (data-1..4 colour tokens). */
export const TOKEN_SERIES = [
  { key: 'cacheRead', label: 'Cache read', token: '--sky-color-data-1' },
  { key: 'cacheWrite', label: 'Cache write', token: '--sky-color-data-2' },
  { key: 'output', label: 'Output', token: '--sky-color-data-3' },
  { key: 'input', label: 'Input', token: '--sky-color-data-4' },
] as const satisfies ReadonlyArray<{ key: keyof TokenBreakdown; label: string; token: string }>

export function totalTokens(b: TokenBreakdown): number {
  return b.input + b.output + b.cacheWrite + b.cacheRead
}

/** "12.1k in / 3.4k out / 240.0k cached"; the cached part only when non-zero. */
export function formatTokenBreakdown(b: TokenBreakdown, options?: FormatTokensOptions): string {
  const parts = [`${formatTokens(b.input, options)} in`, `${formatTokens(b.output, options)} out`]
  const cached = b.cacheWrite + b.cacheRead
  if (cached > 0) parts.push(`${formatTokens(cached, options)} cached`)
  return parts.join(' / ')
}
