/**
 * Usage Meter (UsageMeter board): what a session, execution or day spent.
 * Total cost and tokens, an extruded band of tokens by type, and cost by
 * model or by phase.
 */
import { formatCostPrecise } from '../format/cost'
import { formatInteger, formatPercent } from '../format/number'
import { formatTokens, TOKEN_SERIES, type TokenBreakdown } from '../format/tokens'

export type CostRowTone = 'accent' | 'neutral' | 'claude' | 'codex'

export interface CostRowInput {
  label: string
  /** USD; null when unpriced. */
  value: number | null
  /** Pre-formatted value from the API (`*_display`); wins over `value`. */
  display?: string
  tone?: CostRowTone
}

export interface UsageMeterProps {
  /** Total cost as shown: "$0.2162". Defaults to the sum of the cost rows. */
  cost?: string
  tokens: TokenBreakdown
  costRows: readonly CostRowInput[]
  /** Heading of the right zone. */
  costBy: 'model' | 'phase'
  /** Footnote under the cost rows, e.g. why the model is unknown. */
  note?: string
  /** Rate badges per series, e.g. { cacheRead: '0.1× rate' }. */
  rates?: Partial<Record<keyof TokenBreakdown, string>>
  /** Section heading (default "Usage"). */
  title?: string
}

export interface UsageSeriesRow {
  key: keyof TokenBreakdown
  label: string
  token: string
  value: number
  /** "144,128". */
  display: string
  /** "81.9%". */
  percent: string
  rate?: string
}

export interface UsageCostRow {
  label: string
  display: string
  /** Share of the total cost: "27%". */
  percent: string
  /** Bar fill relative to the largest row, 0..100. */
  fill: number
  tone: CostRowTone
}

export interface UsageModel {
  cost: string
  tokensTotal: number
  /** "176.0K tokens". */
  tokensLabel: string
  series: UsageSeriesRow[]
  costRows: UsageCostRow[]
  /** "Tokens by type: Cache read 81.9 percent, Input 17.0 percent, Output 1.1 percent". */
  bandLabel: string
}

export function usageModel(p: Pick<UsageMeterProps, 'cost' | 'tokens' | 'costRows' | 'rates' | 'costBy'>): UsageModel {
  const t = p.tokens
  const total = t.input + t.output + t.cacheWrite + t.cacheRead
  const series = TOKEN_SERIES.filter((s) => t[s.key] > 0).map((s) => {
    const ratio = total > 0 ? t[s.key] / total : 0
    const row: UsageSeriesRow = { key: s.key, label: s.label, token: s.token, value: t[s.key], display: formatInteger(t[s.key]), percent: formatPercent(ratio, 1) }
    const rate = p.rates?.[s.key]
    if (rate) row.rate = rate
    return row
  })
  const values = p.costRows.map((r) => (typeof r.value === 'number' && r.value > 0 ? r.value : 0))
  const sum = values.reduce((s, v) => s + v, 0)
  const max = Math.max(0, ...values)
  const costRows = p.costRows.map((r, i) => ({
    label: r.label,
    display: r.display ?? formatCostPrecise(r.value),
    percent: sum > 0 ? `${Math.round((values[i]! / sum) * 100)}%` : '—',
    fill: max > 0 ? Math.round((values[i]! / max) * 100) : 0,
    tone: r.tone ?? (p.costBy === 'phase' ? 'accent' : 'neutral'),
  }))
  return {
    cost: p.cost ?? formatCostPrecise(sum),
    tokensTotal: total,
    tokensLabel: `${formatTokens(total, { case: 'upper' })} tokens`,
    series,
    costRows,
    bandLabel:
      total > 0
        ? `Tokens by type: ${series.map((s) => `${s.label} ${s.percent.replace('%', ' percent')}`).join(', ')}`
        : 'No tokens recorded',
  }
}
