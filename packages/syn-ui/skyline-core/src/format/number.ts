import { UNKNOWN, toNumber } from './shared'

const integer = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** 396791 -> "396,791". */
export function formatInteger(value: number | string | null | undefined): string {
  const n = toNumber(value)
  return n === null ? UNKNOWN : integer.format(Math.round(n))
}

/** 0.4217 -> "42%"; `digits` adds decimals. Input is a ratio, not a percentage. */
export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  const n = toNumber(ratio)
  if (n === null) return UNKNOWN
  return `${(n * 100).toFixed(digits)}%`
}

/**
 * Shorten an ID for display: drops a known prefix ("exec-", "sess-", ...) and
 * keeps the first `length` characters. "exec-66e14f235942" -> "66e14f23".
 */
export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return UNKNOWN
  const bare = id.replace(/^(exec|execution|sess|session|wf|workflow|art|artifact|trig|trigger|eval|run)[-_]/i, '')
  return bare.slice(0, length)
}
