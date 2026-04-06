import { Clock, Coins, TrendingUp, Wrench } from 'lucide-react'
import { Card, CardContent, CardHeader, MetricCard } from '../../components'
import { TokenBreakdown } from '../../components/TokenBreakdown'
import type { SessionResponse } from '../../types'
import { formatCost, formatDurationSeconds } from '../../utils/formatters'
import { TOOL_EVENT_TYPES } from './sessionConstants'

function ModelBreakdown({ costByModel }: { costByModel: Record<string, string> }) {
  const entries = Object.entries(costByModel)
    .map(([model, cost]) => ({ model, cost: parseFloat(cost) }))
    .sort((a, b) => b.cost - a.cost)
  const totalCost = entries.reduce((s, e) => s + e.cost, 0)

  if (entries.length === 0) return null

  return (
    <Card>
      <CardHeader
        title="Cost by Model"
        subtitle="Breakdown by model used"
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
                  <span className="text-[var(--color-text-secondary)] font-mono text-xs">{shortName}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-[var(--color-text-primary)] font-medium tabular-nums">
                      {formatCost(cost)}
                    </span>
                    <span className="text-xs text-[var(--color-text-muted)] w-12 text-right tabular-nums">
                      {pct.toFixed(1)}%
                    </span>
                  </div>
                </div>
                <div className="h-1.5 bg-[var(--color-surface-elevated)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full transition-all"
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

export function SessionMetrics({
  session,
  now,
}: {
  session: SessionResponse
  now: number
}) {
  const toolCallCount = session.operations.filter(op =>
    TOOL_EVENT_TYPES.includes(op.operation_type as typeof TOOL_EVENT_TYPES[number])
  ).length

  const durationValue =
    session.status === 'running' && session.started_at
      ? formatDurationSeconds((now - new Date(session.started_at).getTime()) / 1000)
      : formatDurationSeconds(session.duration_seconds)

  const hasCostByModel = session.cost_by_model && Object.keys(session.cost_by_model).length > 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          title="Total Cost"
          value={`$${Number(session.total_cost_usd).toFixed(4)}`}
          icon={Coins}
          color="warning"
        />
        <MetricCard
          title="Duration"
          value={durationValue}
          icon={Clock}
          color="default"
        />
        <MetricCard
          title="Tool Calls"
          value={toolCallCount.toString()}
          icon={Wrench}
          color="default"
        />
      </div>
      <TokenBreakdown
        inputTokens={session.input_tokens}
        outputTokens={session.output_tokens}
        cacheCreationTokens={session.cache_creation_tokens ?? 0}
        cacheReadTokens={session.cache_read_tokens ?? 0}
      />
      {hasCostByModel && <ModelBreakdown costByModel={session.cost_by_model} />}
    </div>
  )
}
