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
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { TrendingUp } from 'lucide-react'
import { Card, CardContent, CardHeader } from './Card'
import { formatCost, formatCostWithCoverage } from '../utils/formatters'

export interface ModelBreakdownProps {
  costByModel: Record<string, string>
  /**
   * What the scope actually cost, from the scope itself
   * (`total_cost_usd`) -- not re-derived from `costByModel`.
   */
  totalCost: number | string
  /**
   * Observations that carried no usable rate, from the same scope
   * (`unpriced_observation_count`). Non-zero means `totalCost` is incomplete,
   * not that the work was free (#890).
   */
  unpricedObservationCount: number | null | undefined
  /** Override the card heading. Defaults to "Cost by Model". */
  title?: string
  subtitle?: string
}

export function ModelBreakdown({
  costByModel,
  totalCost,
  unpricedObservationCount,
  title = 'Cost by Model',
  subtitle = 'Breakdown by model used',
}: ModelBreakdownProps) {
  const entries = Object.entries(costByModel)
    .map(([model, cost]) => ({ model, cost: Number.parseFloat(cost) }))
    .filter((e) => Number.isFinite(e.cost) && e.cost > 0)
    .sort((a, b) => b.cost - a.cost)

  if (entries.length === 0) return null

  const attributed = entries.reduce((s, e) => s + e.cost, 0)
  const scopeTotal = Number(totalCost)
  // A total that is missing or malformed cannot be a denominator; fall back to
  // what the rows account for so the bars stay meaningful rather than NaN.
  const basis = Number.isFinite(scopeTotal) && scopeTotal > attributed ? scopeTotal : attributed
  const unattributed = basis - attributed

  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--color-accent)]" />
            <span className="text-lg font-bold text-[var(--color-text-primary)]">
              {formatCostWithCoverage(totalCost, unpricedObservationCount)}
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">total</span>
          </div>
        }
      />
      <CardContent>
        <div className="space-y-2.5">
          {entries.map(({ model, cost }) => {
            const pct = basis > 0 ? (cost / basis) * 100 : 0
            const shortName = model.replace(/^claude-/, '').replace(/-\d{8}$/, '')
            return (
              <div key={model} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                    {shortName}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className="font-medium tabular-nums text-[var(--color-text-primary)]">
                      {formatCost(cost)}
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
            )
          })}
          {unattributed > 0 && (
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
                    {formatCost(unattributed)}
                  </span>
                  <span className="w-12 text-right tabular-nums text-xs text-[var(--color-text-muted)]">
                    {((unattributed / basis) * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
                <div
                  className="h-full rounded-full bg-slate-500 transition-all"
                  style={{ width: `${Math.max((unattributed / basis) * 100, 1)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
