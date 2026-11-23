/**
 * Cost-by-model breakdown card.
 *
 * Renders one row per model with cost, percentage, and a thin progress bar.
 * Used on both the Session and Execution detail pages so the visualisation
 * is identical regardless of which scope you're looking at.
 *
 * Accepts the API's ``cost_by_model: Record<string, string>`` shape directly
 * (values are decimal strings).
 *
 * The per-model map is NOT a complete account of what a scope cost. An
 * execution's map is aggregated from its phases, and the domain leaves that
 * empty for a phase still running, so mid-run the rows add up to less than the
 * scope's real total -- sometimes to nothing at all. This card used to compute
 * its own header figure by summing the rows and label it "total", which meant a
 * live run showed a smaller, confident number here than on the Total Cost card
 * a few hundred pixels above it, with percentages implying the rows were
 * everything (#1048).
 *
 * So the scope's authoritative total is a required input, not an optional
 * override: the card reports THAT as the total, scales the bars against it, and
 * shows whatever it cannot attribute as its own row rather than quietly
 * dropping it. Same rule as `inProgressTokens` in `executionTokens` -- the
 * parts must add up to the headline (#873).
 *
 * Every dollar figure on the card is the API's text, rendered verbatim (#897):
 * the total, each row, and the "not yet attributed" remainder, which the server
 * reconciles and the card draws only when it is sent. The decimal amounts are
 * read for one thing only, the bar widths and percentages.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { TrendingUp } from 'lucide-react'
import { Card, CardContent, CardHeader } from './Card'
import {
  type ExactUsd,
  exactUsdToNumber,
  parseExactUsd,
  sumExactUsd,
} from '../utils/exactUsd'
import { costByModelKeyLabel } from '../utils/modelLabels'

const EM_DASH = '—'

export interface ModelBreakdownProps {
  costByModel: Record<string, string>
  /**
   * What the scope actually cost, from the scope itself
   * (`total_cost_usd`) -- not re-derived from `costByModel`.
   */
  totalCost: number | string
  /** The scope's `total_cost_display`, coverage included (#890). */
  totalCostDisplay: string
  /** The scope's `cost_by_model_display`; a row it has no entry for shows an em dash. */
  costByModelDisplay: Record<string, string>
  /** The scope's `unattributed_cost_display`; null means the card draws no remainder row. */
  unattributedCostDisplay: string | null
  /**
   * Models that ran but nothing priced (#1743), listed after the split with
   * `unpricedLabel` (backend text) in place of a cost, never as $0.
   */
  unpricedModels?: string[]
  unpricedLabel?: string
  /** Override the card heading. Defaults to "Cost by Model". */
  title?: string
  subtitle?: string
}

export function ModelBreakdown({
  costByModel,
  totalCost,
  totalCostDisplay,
  costByModelDisplay,
  unattributedCostDisplay,
  unpricedModels = [],
  unpricedLabel = '',
  title = 'Cost by Model',
  subtitle = 'Breakdown by model used',
}: ModelBreakdownProps) {
  // Widths in exact decimal, not floats: the rows and the total are decimal
  // strings, and float subtraction of an exactly-attributed total leaves ~1e-17.
  const exactEntries = Object.entries(costByModel)
    .map(([model, cost]) => ({ model, exact: parseExactUsd(cost) }))
    .filter((e): e is { model: string; exact: ExactUsd } => e.exact !== null && e.exact > 0n)
    .sort((a, b) => (a.exact === b.exact ? 0 : a.exact < b.exact ? 1 : -1))

  if (exactEntries.length === 0 && unpricedModels.length === 0) return null

  const attributedExact = sumExactUsd(exactEntries.map((e) => e.exact))
  const scopeTotal = parseExactUsd(totalCost)
  // A total that is missing or malformed cannot be a denominator; fall back to
  // what the rows account for so the bars stay meaningful rather than NaN.
  const basisExact = scopeTotal !== null && scopeTotal > attributedExact ? scopeTotal : attributedExact
  const basis = exactUsdToNumber(basisExact)
  const share = (exact: ExactUsd) => (basis > 0 ? (exactUsdToNumber(exact) / basis) * 100 : 0)

  const entries = exactEntries.map((e) => ({ model: e.model, pct: share(e.exact) }))
  const unattributedPct = share(basisExact - attributedExact)

  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--color-accent)]" />
            <span className="text-lg font-bold text-[var(--color-text-primary)]">
              {totalCostDisplay}
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">total</span>
          </div>
        }
      />
      <CardContent>
        <div className="space-y-2.5">
          {entries.map(({ model, pct }) => (
            <div key={model} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                  {costByModelKeyLabel(model)}
                </span>
                <div className="flex items-center gap-3">
                  <span className="font-medium tabular-nums text-[var(--color-text-primary)]">
                    {costByModelDisplay[model] ?? EM_DASH}
                  </span>
                  <span className="w-12 text-right tabular-nums text-xs text-[var(--color-text-muted)]">
                    {pct.toFixed(1)}%
                  </span>
                </div>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all"
                  style={{ width: `${Math.max(pct, 1)}%` }}
                />
              </div>
            </div>
          ))}
          {unattributedCostDisplay !== null && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span
                  className="font-mono text-xs text-[var(--color-text-muted)]"
                  title="Counted in the total but not yet attributed to a model — a phase still running has no per-model breakdown"
                >
                  not yet attributed
                </span>
                <div className="flex items-center gap-3">
                  <span className="font-medium tabular-nums text-[var(--color-text-secondary)]">
                    {unattributedCostDisplay}
                  </span>
                  <span className="w-12 text-right tabular-nums text-xs text-[var(--color-text-muted)]">
                    {unattributedPct.toFixed(1)}%
                  </span>
                </div>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
                <div
                  className="h-full rounded-full bg-slate-500 transition-all"
                  style={{ width: `${Math.max(unattributedPct, 1)}%` }}
                />
              </div>
            </div>
          )}
          {unpricedModels.map((model) => (
            <div key={model} className="flex items-center justify-between text-sm">
              <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                {costByModelKeyLabel(model)}
              </span>
              <span className="text-xs text-[var(--color-text-muted)]">{unpricedLabel}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
