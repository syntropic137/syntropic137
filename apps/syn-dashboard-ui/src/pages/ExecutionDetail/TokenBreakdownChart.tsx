import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'

import { TrendingUp } from 'lucide-react'

import { Card, CardContent, CardHeader, ChartTooltip } from '../../components'
import type { PhaseExecutionDetail } from '../../types'
import { formatCost, formatTokens } from '../../utils/formatters'

interface TokenBreakdownChartProps {
  inputTokens: number
  outputTokens: number
  cacheCreationTokens: number
  cacheReadTokens: number
  phases?: PhaseExecutionDetail[]
}

function TokenSegment({ label, total, rows, accentColor }: {
  label: string
  total: number
  rows: { label: string; value: number; color?: string }[]
  accentColor: string
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] overflow-hidden">
      <div className={`flex items-center justify-between px-3 py-1.5 ${accentColor}`}>
        <span className="text-xs font-medium">{label}</span>
        <span className="text-sm font-semibold text-[var(--color-text-primary)]">{formatTokens(total)}</span>
      </div>
      <div className="px-3 py-1.5 space-y-0.5 text-xs">
        {rows.map(row => (
          <div key={row.label} className="flex justify-between">
            <span className={row.color ?? 'text-[var(--color-text-muted)]'}>{row.label}</span>
            <span className={row.color ?? 'text-[var(--color-text-secondary)]'}>{formatTokens(row.value)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function aggregateModelCosts(phases: PhaseExecutionDetail[]): Record<string, number> {
  const merged: Record<string, number> = {}
  for (const phase of phases) {
    if (!phase.cost_by_model) continue
    for (const [model, cost] of Object.entries(phase.cost_by_model)) {
      merged[model] = (merged[model] ?? 0) + parseFloat(cost)
    }
  }
  return merged
}

export function TokenBreakdownChart({
  inputTokens,
  outputTokens,
  cacheCreationTokens,
  cacheReadTokens,
  phases,
}: TokenBreakdownChartProps) {
  const tokenChartData = [
    { name: 'Input', tokens: inputTokens, fill: '#6366f1' },
    { name: 'Cache Write', tokens: cacheCreationTokens, fill: '#f59e0b' },
    { name: 'Cache Read', tokens: cacheReadTokens, fill: '#22c55e' },
    { name: 'Output', tokens: outputTokens, fill: '#8b5cf6' },
  ].filter(d => d.tokens > 0)

  const totalTokens = inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens
  const modelCosts = phases ? aggregateModelCosts(phases) : {}
  const hasModelBreakdown = Object.keys(modelCosts).length > 0

  return (
    <Card>
      <CardHeader
        title="Token Breakdown"
        subtitle={`${formatTokens(totalTokens)} total — distribution by type`}
      />
      <CardContent>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <TokenSegment
              label="In"
              total={inputTokens + cacheReadTokens}
              accentColor="bg-indigo-500/10 text-indigo-400"
              rows={[
                { label: 'Fresh', value: inputTokens },
                { label: 'Cache read', value: cacheReadTokens, color: 'text-emerald-400' },
              ]}
            />
            <TokenSegment
              label="Out"
              total={outputTokens + cacheCreationTokens}
              accentColor="bg-violet-500/10 text-violet-400"
              rows={[
                { label: 'Output', value: outputTokens },
                { label: 'Cache write', value: cacheCreationTokens, color: 'text-amber-400' },
              ]}
            />
        </div>
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tokenChartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <YAxis
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                tickFormatter={(v: number) => formatTokens(v)}
              />
              <ChartTooltip
                position={{ y: 0 }}
                offset={20}
                formatter={(value: number) => [formatTokens(value), 'tokens']}
              />
              <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
                {tokenChartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {hasModelBreakdown && (() => {
          const totalModelCost = Object.values(modelCosts).reduce((s, c) => s + c, 0)
          return (
            <div className="mt-4 pt-4 border-t border-[var(--color-border)]">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="h-4 w-4 text-[var(--color-text-secondary)]" />
                <span className="text-xs font-medium text-[var(--color-text-secondary)]">Cost by Model</span>
              </div>
              <div className="space-y-2.5">
                {Object.entries(modelCosts)
                  .sort(([, a], [, b]) => b - a)
                  .map(([model, cost]) => {
                    const pct = totalModelCost > 0 ? (cost / totalModelCost) * 100 : 0
                    return (
                      <div key={model} className="space-y-1">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-[var(--color-text-muted)] font-mono text-xs truncate flex-1">
                            {model.replace(/^claude-/, '').replace(/-\d{8}$/, '')}
                          </span>
                          <span className="text-[var(--color-text-primary)] font-medium ml-4">
                            {formatCost(cost)} ({pct.toFixed(1)}%)
                          </span>
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
            </div>
          )
        })()}
      </CardContent>
    </Card>
  )
}
