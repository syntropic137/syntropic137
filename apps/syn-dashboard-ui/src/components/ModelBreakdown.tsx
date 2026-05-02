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
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { TrendingUp } from 'lucide-react'
import { Card, CardContent, CardHeader } from './Card'
import { formatCost } from '../utils/formatters'

export interface ModelBreakdownProps {
  costByModel: Record<string, string>
  /** Override the card heading. Defaults to "Cost by Model". */
  title?: string
  subtitle?: string
}

export function ModelBreakdown({
  costByModel,
  title = 'Cost by Model',
  subtitle = 'Breakdown by model used',
}: ModelBreakdownProps) {
  const entries = Object.entries(costByModel)
    .map(([model, cost]) => ({ model, cost: Number.parseFloat(cost) }))
    .filter((e) => Number.isFinite(e.cost) && e.cost > 0)
    .sort((a, b) => b.cost - a.cost)

  if (entries.length === 0) return null

  const totalCost = entries.reduce((s, e) => s + e.cost, 0)

  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--color-accent)]" />
            <span className="text-lg font-bold text-[var(--color-text-primary)]">
              {formatCost(totalCost)}
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">total</span>
          </div>
        }
      />
      <CardContent>
        <div className="space-y-2.5">
          {entries.map(({ model, cost }) => {
            const pct = totalCost > 0 ? (cost / totalCost) * 100 : 0
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
        </div>
      </CardContent>
    </Card>
  )
}
